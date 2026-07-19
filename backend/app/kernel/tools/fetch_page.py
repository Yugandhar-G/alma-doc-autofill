"""fetch_page driver: retrieve one public web page as plain text.

This is the only place agents touch the raw network. Every redirect hop
re-passes the SSRF guard (guards.check_url_allowed); response text is
length-capped and returned wrapped in <untrusted_web_content> delimiters —
data, never instructions.
"""
import logging
from urllib.parse import urlparse

import httpx

from app.kernel.tools.guards import check_url_allowed, html_to_text

logger = logging.getLogger("yunaki.kernel.fetch")

MAX_PAGE_CHARS = 6000
_MAX_REDIRECTS = 3
_TIMEOUT_S = 10.0


def _refuse(url: str, reason: str) -> str:
    logger.warning("fetch refused url_host=%s reason=%s", urlparse(url).hostname, reason)
    return f"FETCH_REFUSED: {reason}"


async def fetch_page(url: str) -> str:
    """Fetch one page → plain text (capped), or a FETCH_REFUSED/FETCH_FAILED
    string the agent can reason about. Never raises."""
    current = url
    try:
        async with httpx.AsyncClient(
            timeout=_TIMEOUT_S, follow_redirects=False,
            headers={"User-Agent": "yunaki-screener-verification/1.0"},
        ) as client:
            for _ in range(_MAX_REDIRECTS + 1):
                reason = check_url_allowed(current)
                if reason is not None:
                    return _refuse(current, reason)
                response = await client.get(current)
                if response.is_redirect:
                    location = response.headers.get("location")
                    if not location:
                        return "FETCH_FAILED: redirect without location"
                    current = str(httpx.URL(current).join(location))
                    continue
                if response.status_code != 200:
                    return f"FETCH_FAILED: HTTP {response.status_code}"
                content_type = response.headers.get("content-type", "")
                if "html" not in content_type and "text" not in content_type:
                    return f"FETCH_FAILED: unsupported content type {content_type[:60]}"
                text = html_to_text(response.text)[:MAX_PAGE_CHARS]
                if not text.strip():
                    return "FETCH_FAILED: page had no extractable text"
                return f"<untrusted_web_content url={current!r}>\n{text}\n</untrusted_web_content>"
            return "FETCH_FAILED: too many redirects"
    except Exception as exc:
        logger.warning("fetch failed host=%s err=%s", urlparse(url).hostname, type(exc).__name__)
        return f"FETCH_FAILED: {type(exc).__name__}"
