"""Kernel configuration. Every tunable lives here or in the environment —
nothing is hardcoded at call sites.

Phase-1 state: the flat Settings class moved here unchanged (env names are
stable). The per-package split (each package ships its own BaseSettings with
an env_prefix, assembled into a SettingsBundle) lands with the package
contract in Phase 2 — SettingsBundle below is the seam it will fill.
"""
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Mapping

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Vision extraction
    gemini_api_key: str | None = None
    # Model ids verified against https://ai.google.dev/gemini-api/docs/models (2026-07-01):
    # gemini-3.5-flash is the current stable flash-tier model; gemini-3.1-pro-preview is
    # the current recommended pro-tier id (there is no stable 3.x pro id as of that date).
    gemini_model: str = "gemini-3.5-flash"
    gemini_model_escalation: str = "gemini-3.1-pro-preview"  # used when default returns null-heavy result
    extraction_temperature: float = 0.0
    extraction_max_retries: int = 1

    # Storage (Supabase when set, local disk otherwise)
    supabase_url: str | None = None
    supabase_service_key: str | None = None
    supabase_bucket: str = "documents"
    local_storage_dir: str = "uploads"

    # Matter store — firm-scoped data layer (matters, runs, interrupts, memory).
    # Supabase is the firm-sync plane when configured; local SQLite otherwise.
    matter_store_path: str = "uploads/matters.db"

    # Upload guardrails
    max_file_mb: int = 10
    max_pdf_pages: int = 10
    allowed_formats: tuple[str, ...] = ("pdf", "jpeg", "png")
    min_image_dimension: int = 500        # px, shorter side
    blur_threshold: float = 40.0          # variance of Laplacian below this → reject

    # PDF rendering
    render_dpi: int = 220

    # Population. Headless is the default: it yields the downloadable PDF
    # artifact instead of a browser window that closes the moment the run
    # ends. Set POPULATE_HEADED=true to watch the fill live (the artifact
    # then degrades to a full-page PNG — Chromium prints PDFs headless-only).
    target_form_url: str = "https://mendrika-alma.github.io/form-submission/"
    populate_headed: bool = False
    populate_timeout_ms: int = 60_000

    # Frontend origin for CORS
    frontend_origin: str = "http://localhost:3000"

    # Workflow-run checkpointing (per package; one DB each until the matter
    # store consolidates them)
    autofill_checkpoint_path: str = "uploads/autofill/checkpoints.db"
    preflight_checkpoint_path: str = "uploads/preflight/checkpoints.db"

    # Screener (O-1A / EB-1A eligibility decision support)
    screener_checkpoint_path: str = "uploads/screener/checkpoints.db"
    screener_max_evidence_docs: int = 8
    screener_web_enrichment: bool = True   # gates the verification agent; AND gemini key present
    screener_agent_max_tool_calls: int = 10  # search_web + fetch_page budget per run
    screener_intake_max_chars: int = 2000  # per free-text answer (schema-enforced)

    # Observability (Langfuse) — tracing is a no-op until both keys are set.
    langfuse_public_key: str | None = None
    langfuse_secret_key: str | None = None
    langfuse_host: str = "https://cloud.langfuse.com"

    def require_gemini_key(self) -> str:
        if not self.gemini_api_key:
            raise RuntimeError(
                "GEMINI_API_KEY is not set. Copy .env.example to backend/.env and add your key."
            )
        return self.gemini_api_key

    @property
    def supabase_enabled(self) -> bool:
        return bool(self.supabase_url and self.supabase_service_key)

    @property
    def langfuse_enabled(self) -> bool:
        return bool(self.langfuse_public_key and self.langfuse_secret_key)


@dataclass(frozen=True)
class SettingsBundle:
    """Kernel settings plus each installed package's own settings, keyed by
    package_id. Populated by the app factory once the package contract lands
    (Phase 2); until then the bundle carries the flat kernel settings only."""

    kernel: Settings
    packages: Mapping[str, BaseSettings] = field(default_factory=dict)


@lru_cache
def get_settings() -> Settings:
    return Settings()
