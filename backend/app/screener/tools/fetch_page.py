"""fetch_page tool: retrieve one public web page as plain text for the
verification agent.

Security posture (this is the only place the agent touches the raw network):
- http/https only, standard ports only.
- Host must resolve to a public IP — loopback, RFC1918, link-local, and
  metadata ranges are refused BEFORE any request (SSRF guard). Redirects are
  followed manually so every hop re-passes the same guard.
- Response text is length-capped and returned to the model wrapped in
  <untrusted_web_content> delimiters — data, never instructions.
"""
import ipaddress
import logging
import re
import socket
from html.parser import HTMLParser
from urllib.parse import urlparse

import httpx

logger = logging.getLogger("yunaki.screener.fetch")

MAX_PAGE_CHARS = 6000
_MAX_REDIRECTS = 3
_TIMEOUT_S = 10.0
_ALLOWED_PORTS = {80, 443}

_SKIP_CONTENT = re.compile(r"\s+")


class _TextExtractor(HTMLParser):
    """Minimal HTML→text: drops script/style/nav noise, keeps visible text."""

    _SKIP_TAGS = {"script", "style", "noscript", "svg", "iframe", "head"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._skip_depth = 0
        self.chunks: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in self._SKIP_TAGS:
            self._skip_depth += 1

    def handle_endtag(self, tag):
        if tag in self._SKIP_TAGS and self._skip_depth:
            self._skip_depth -= 1

    def handle_data(self, data):
        if not self._skip_depth and data.strip():
            self.chunks.append(data.strip())


def html_to_text(html: str) -> str:
    parser = _TextExtractor()
    try:
        parser.feed(html)
    except Exception:
        pass
    return _SKIP_CONTENT.sub(" ", " ".join(parser.chunks))


def _refuse(url: str, reason: str) -> str:
    logger.warning("fetch refused url_host=%s reason=%s", urlparse(url).hostname, reason)
    return f"FETCH_REFUSED: {reason}"


def check_url_allowed(url: str) -> str | None:
    """None when safe to fetch; otherwise a refusal reason. Resolves the host
    and rejects anything that is not a public unicast IP."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return "only http/https URLs are fetchable"
    host = parsed.hostname
    if not host:
        return "URL has no host"
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    if port not in _ALLOWED_PORTS:
        return "non-standard ports are not fetchable"
    try:
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except OSError:
        return "host did not resolve"
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if not ip.is_global or ip.is_multicast:
            return "host resolves to a non-public address"
    return None


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
