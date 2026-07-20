"""FastAPI app factory — integration layer. Owns HTTP concerns only;
extraction/population/storage logic lives in the respective planes, and
workflow packages mount their own routers from the registry.

PII rule: request/response bodies carry extracted values by design; logs
never do — documents are referenced by content hash only.
"""
import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from app.config import get_settings
from app.kernel.auth import (
    DownloadTokenResult,
    Principal,
    get_principal,
    install_auth,
    mint_download_token,
    verify_download_token,
)
from app.kernel.config import Settings, get_settings as get_kernel_settings
from app.kernel.observability import (
    TelemetryValue,
    flush as observability_flush,
    record_frontend_event,
    request_trace,
)
from app.kernel.ratelimit import install_rate_limit
from app.observability import envelope_stats, report_stats
from app.packages.autofill.service import extract_slots
from app.population import populate_form
from app.population.artifact import stored_artifact_path
from app.schemas import ApiResponse, G28Data, PassportData

logger = logging.getLogger("yunaki")


@asynccontextmanager
async def _lifespan(_: FastAPI):
    yield
    observability_flush()  # drain the trace export queue on shutdown


class PopulateRequest(BaseModel):
    passport: PassportData | None = None
    g28: G28Data | None = None
    headed: bool | None = None


class TelemetryEvent(BaseModel):
    """UI event from the frontend. Names are namespaced and metadata values
    are scalar-only so nothing free-form (or PII-shaped) can be relayed."""

    name: str = Field(min_length=4, max_length=64, pattern=r"^ui\.[a-z0-9_.]+$")
    session_id: str | None = Field(None, max_length=64)
    metadata: dict[str, TelemetryValue] = Field(default_factory=dict)


_ARTIFACT_MEDIA_TYPES = {".pdf": "application/pdf", ".png": "image/png"}


def create_app(registry: tuple | None = None) -> FastAPI:
    """Build the app over the installed package registry. Packages mount
    their routers under /api/packages/{package_id}; legacy endpoints
    (/api/extract, /api/populate, /api/screener/*) stay until Phase C1."""
    from app.api import router as matter_router
    from app.registry import INSTALLED_PACKAGES
    from app.screener.api import router as screener_router

    packages = INSTALLED_PACKAGES if registry is None else registry
    settings = get_settings()

    app = FastAPI(title="yunaki-doc-autofill", lifespan=_lifespan)
    install_auth(app)  # AuthError → 401 in the ApiResponse envelope
    install_rate_limit(app)  # RateLimitError → 429 in the same envelope
    app.include_router(screener_router)  # legacy screener session API
    app.include_router(matter_router)  # matter API (matters/documents/runs/inbox)
    for package in packages:
        if package.router_factory is not None:
            app.include_router(
                package.router_factory(),
                prefix=f"/api/packages/{package.manifest.package_id}",
                tags=[package.manifest.package_id],
            )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.frontend_origin],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/api/packages")
    async def list_packages() -> ApiResponse:
        """The installed workflow packages — the OS process catalog."""
        return ApiResponse(
            success=True,
            data={"packages": [p.manifest.summary() for p in packages]},
        )

    @app.get("/api/health")
    async def health() -> ApiResponse:
        return ApiResponse(
            success=True,
            data={
                "storage": "supabase" if settings.supabase_enabled else "local",
                "model": settings.gemini_model,
                "gemini_key_present": settings.gemini_api_key is not None,
                "packages": [p.manifest.package_id for p in packages],
            },
        )

    @app.post("/api/extract")
    async def extract(
        request: Request,
        passport_front: UploadFile | None = None,
        passport_back: UploadFile | None = None,
        g28: UploadFile | None = None,
    ) -> ApiResponse:
        """Extract whichever documents were uploaded (legacy path; the
        package run path adds checkpointed review on top of the same
        service). Slot-level problems come back under the slot's key so one
        bad file never discards another's result."""
        if passport_front is None and g28 is None:
            return ApiResponse(
                success=False, error="Upload at least a passport front or a G-28."
            )
        try:
            with request_trace(
                "extract",
                request.headers.get("x-session-id"),
                metadata={
                    "slot_passport_front": passport_front is not None,
                    "slot_passport_back": passport_back is not None,
                    "slot_g28": g28 is not None,
                },
            ) as trace:
                data = await extract_slots(passport_front, passport_back, g28)
                if trace is not None:
                    output: dict = {}
                    for key in ("passport", "passport_back", "g28"):
                        slot = data.get(key)
                        if isinstance(slot, dict):
                            # Rejection reasons are fixed guardrail templates
                            # (size, blur, page cap, wrong type) — they name
                            # limits, never document content.
                            output[key] = (
                                {"rejected": True, "reason": slot["error"]}
                                if "error" in slot
                                else envelope_stats(slot)
                            )
                    trace.update(output=output)
                return ApiResponse(success=True, data=data)
        except RuntimeError as exc:  # model/config failures — message is hash-only
            logger.exception("extraction runtime failure")
            return ApiResponse(success=False, error=str(exc))
        except Exception:
            logger.exception("extraction failed")
            return ApiResponse(
                success=False, error="Extraction failed. Check server logs."
            )

    @app.post("/api/populate")
    async def populate(request: Request, req: PopulateRequest) -> ApiResponse:
        if req.passport is None and req.g28 is None:
            return ApiResponse(success=False, error="Nothing to populate.")
        try:
            with request_trace(
                "populate",
                request.headers.get("x-session-id"),
                metadata={
                    "has_passport": req.passport is not None,
                    "has_g28": req.g28 is not None,
                },
            ) as trace:
                report = await populate_form(req.passport, req.g28, headed=req.headed)
                if trace is not None:
                    trace.update(output=report_stats(report))
                return ApiResponse(success=True, data=report.model_dump())
        except Exception:
            logger.exception("population failed")
            return ApiResponse(
                success=False, error="Form population failed. Check server logs."
            )

    @app.get("/api/population-artifact/{artifact_id}")
    async def population_artifact(artifact_id: str, download: bool = False, t: str | None = None):
        """Serve the captured filled-form artifact (PDF or PNG). The id is a
        bare content hash; anything else resolves to None inside
        stored_artifact_path, so no path input ever reaches the filesystem.

        Two access paths, one route:
        - Programmatic: the desktop sidecar's bearer middleware has already
          authorized the request; no ?t= is needed.
        - Browser download: an <a href> carries no Authorization header, so it
          instead carries a short-lived signed ?t= token scoped to THIS id
          (minted via POST .../link). A present-but-invalid token is a hard 403
          — a forged/expired token never serves. No token in dev (no signing
          secret) serves as before."""
        if t is not None:
            result = verify_download_token(artifact_id, t, get_settings())
            if result is DownloadTokenResult.INVALID:
                return JSONResponse(
                    status_code=403,
                    content=ApiResponse(
                        success=False, error="Invalid or expired download link."
                    ).model_dump(),
                )
        path = stored_artifact_path(artifact_id)
        if path is None:
            return JSONResponse(
                status_code=404,
                content=ApiResponse(
                    success=False, error="No such artifact. Populate the form first."
                ).model_dump(),
            )
        return FileResponse(
            path,
            media_type=_ARTIFACT_MEDIA_TYPES[path.suffix],
            filename=f"a28-filled{path.suffix}",
            content_disposition_type="attachment" if download else "inline",
        )

    @app.post("/api/population-artifact/{artifact_id}/link")
    async def population_artifact_link(
        artifact_id: str,
        _principal: Principal = Depends(get_principal),
        settings: Settings = Depends(get_kernel_settings),
    ) -> ApiResponse:
        """Mint a browser-usable download URL for an artifact the caller is
        authorized to fetch. Behind get_principal, so an unauthenticated caller
        cannot mint links; the returned ?t= token then lets the packaged app's
        <a href> download without an Authorization header. Returns a token-free
        URL in dev (no signing secret — the route needs no token there)."""
        if stored_artifact_path(artifact_id) is None:
            return ApiResponse(success=False, error="No such artifact.")
        token = mint_download_token(artifact_id, settings)
        base = f"/api/population-artifact/{artifact_id}?download=true"
        url = f"{base}&t={token}" if token else base
        return ApiResponse(
            success=True,
            data={"url": url, "expires_in": settings.download_token_ttl_seconds if token else None},
        )

    @app.post("/api/telemetry")
    async def telemetry(event: TelemetryEvent) -> ApiResponse:
        """Relay a frontend event into the trace timeline (no-op when disabled)."""
        trimmed = {
            key[:40]: (value[:200] if isinstance(value, str) else value)
            for key, value in list(event.metadata.items())[:20]
        }
        recorded = record_frontend_event(event.name, event.session_id, trimmed)
        return ApiResponse(success=True, data={"recorded": recorded})

    return app


app = create_app()
