"""Desktop sidecar entrypoint.

The Tauri shell (see desktop/) launches this as a bundled PyInstaller one-dir
binary. It runs the same FastAPI kernel as `make dev`, but:

  - bound to 127.0.0.1 (loopback only — never a routable interface),
  - on a port the shell picks (a free port, passed via --port),
  - behind a per-launch bearer token (passed via --token) enforced by a tiny
    pure-ASGI middleware.

Security model: the token is generated fresh by the shell on every launch,
lives only in process memory + the injected `window.__YUNAKI_API__`, and is
never persisted or logged. Absent --token = dev mode: no enforcement, so this
file is also runnable by hand for debugging (`python desktop_entry.py`).

CORS: the webview origin (tauri://localhost on macOS, http://tauri.localhost on
Windows) differs from the loopback API origin, so the shell passes the correct
FRONTEND_ORIGIN env var, which the kernel's existing CORSMiddleware honors. No
CORS handling lives here.

The middleware is pure ASGI (not BaseHTTPMiddleware) on purpose: the screener
serves SSE streams via response.body streaming, and BaseHTTPMiddleware buffers
responses, which would break those streams. A pure-ASGI passthrough leaves the
response path untouched.
"""
import argparse
import hmac
import json
import logging
from urllib.parse import parse_qs

import uvicorn

logger = logging.getLogger("yunaki.desktop")

# Loopback only. The sidecar must never bind a routable interface.
_DEFAULT_HOST = "127.0.0.1"
_DEFAULT_PORT = 8000  # standalone/dev default; the shell always passes --port.

_UNAUTHORIZED_BODY = json.dumps(
    {"success": False, "data": None, "error": "missing or invalid desktop token"}
).encode()


class BearerTokenMiddleware:
    """Reject any HTTP request lacking `Authorization: Bearer <token>`.

    Exemptions:
      - non-HTTP scopes (lifespan, websocket) pass through untouched,
      - CORS preflight (OPTIONS) carries no Authorization header by spec, so it
        passes through to the CORS layer,
      - GET of an artifact download that carries a ?t= query token: an <a href>
        download cannot set an Authorization header, so this route accepts a
        short-lived signed token instead. This is a STRUCTURAL exemption only —
        the middleware just lets the request reach the handler, which does the
        cryptographic validation and 403s a forged/expired token. A request
        with neither bearer nor ?t= is still rejected here.
      - token is None (dev mode) → enforcement disabled entirely.
    """

    def __init__(self, app, token: str | None):
        self.app = app
        self.token = token
        self._expected = f"Bearer {token}" if token else None

    async def __call__(self, scope, receive, send):
        if self.token is None or scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        if scope.get("method") == "OPTIONS":
            await self.app(scope, receive, send)
            return
        if self._is_signed_download(scope):
            await self.app(scope, receive, send)
            return

        header_map = dict(scope.get("headers") or [])
        provided = header_map.get(b"authorization", b"").decode("latin-1")
        # Constant-time compare so a rejected token leaks no timing signal.
        if not hmac.compare_digest(provided, self._expected):
            await self._reject(send)
            return
        await self.app(scope, receive, send)

    @staticmethod
    def _is_signed_download(scope) -> bool:
        """True for `GET /api/population-artifact/<id>?...t=<token>...` — the
        one browser-download route allowed to authenticate via ?t= instead of a
        bearer header. Only presence is checked here; the handler validates the
        token itself."""
        if scope.get("method") != "GET":
            return False
        path = scope.get("path", "")
        if not path.startswith("/api/population-artifact/"):
            return False
        params = parse_qs(scope.get("query_string", b"").decode("latin-1"))
        token = params.get("t", [""])[0]
        return bool(token)

    @staticmethod
    async def _reject(send) -> None:
        await send(
            {
                "type": "http.response.start",
                "status": 401,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(_UNAUTHORIZED_BODY)).encode()),
                ],
            }
        )
        await send({"type": "http.response.body", "body": _UNAUTHORIZED_BODY})


def build_app(token: str | None):
    """Construct the kernel app and wrap it in the token gate.

    Imported lazily so `--help` and arg parsing never pay the (heavy) import
    cost of the LLM/graph stack — and so a frozen binary surfaces import
    failures with a clear traceback at startup, not at module import.
    """
    from app.main import create_app

    app = create_app()
    # add_middleware wraps outermost, so the token check runs before CORS; the
    # OPTIONS exemption lets the CORS layer still answer preflight.
    app.add_middleware(BearerTokenMiddleware, token=token)
    return app


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Yunaki desktop FastAPI sidecar")
    parser.add_argument("--host", default=_DEFAULT_HOST, help="bind host (loopback)")
    parser.add_argument("--port", type=int, default=_DEFAULT_PORT, help="bind port")
    parser.add_argument(
        "--token",
        default=None,
        help="per-launch bearer token; omit for dev mode (no enforcement)",
    )
    parser.add_argument("--log-level", default="info")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    logging.basicConfig(level=args.log_level.upper())
    if args.token is None:
        logger.warning("desktop sidecar starting in DEV MODE — token enforcement OFF")
    else:
        # Never log the token itself.
        logger.info("desktop sidecar starting with token enforcement ON")

    app = build_app(args.token)
    uvicorn.run(app, host=args.host, port=args.port, log_level=args.log_level)


if __name__ == "__main__":
    main()
