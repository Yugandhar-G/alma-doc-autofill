"""Network guards — the SSRF policy every outbound fetch must pass.

- http/https only, standard ports only.
- Host must resolve to a public IP — loopback, RFC1918, link-local, and
  metadata ranges are refused BEFORE any request. Callers follow redirects
  manually so every hop re-passes this same check.
"""
import ipaddress
import re
import socket
from html.parser import HTMLParser
from urllib.parse import urlparse

_ALLOWED_PORTS = {80, 443}
_WHITESPACE = re.compile(r"\s+")


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
    return _WHITESPACE.sub(" ", " ".join(parser.chunks))


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
