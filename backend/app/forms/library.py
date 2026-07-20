"""Form library downloader — stores official blank USCIS PDFs locally.

Discipline mirrors the upload boundary: https + exact-host allow-list (the
registry schemas already enforce uscis.gov for pdf_url; re-checked here per
request), magic-byte sniff (%PDF), size cap, sha256 manifest. Blank public
forms carry no PII; they are still referenced by content hash like every
other stored document.

Run: cd backend && python -m app.forms.library
Exit 1 if any registry pdf_url failed to download or verify — a partial
library must be loud, never silent.
"""
import asyncio
import hashlib
import json
import logging
import sys
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

import httpx

from app.forms.registry import load_registry
from app.forms.schemas import FormRef

logger = logging.getLogger("yunaki.forms.library")

_ALLOWED_HOSTS = frozenset({"www.uscis.gov", "uscis.gov"})
_MAX_PDF_BYTES = 20 * 1024 * 1024  # official form PDFs run large (I-129)
_TIMEOUT = httpx.Timeout(30.0)
_CONCURRENCY = 4

LIBRARY_DIR = Path("uploads") / "forms_library"


def _safe_name(form: FormRef) -> str:
    edition = (form.edition_date or "na").replace("/", "-")
    return f"{form.form_id.replace('/', '_')}__{edition}.pdf"


async def _fetch_one(
    client: httpx.AsyncClient, form: FormRef, dest_dir: Path
) -> dict:
    """Download + verify one form PDF. Returns its manifest entry; entries
    with an 'error' key mark failures (never partial files on disk)."""
    url = form.pdf_url or ""
    host = urlparse(url).hostname or ""
    entry: dict = {"form_id": form.form_id, "edition_date": form.edition_date, "url": url}
    if host not in _ALLOWED_HOSTS:
        return {**entry, "error": f"host not allow-listed: {host}"}
    try:
        response = await client.get(url, follow_redirects=True)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        return {**entry, "error": f"http error: {exc}"}
    body = response.content
    if len(body) > _MAX_PDF_BYTES:
        return {**entry, "error": f"exceeds size cap ({len(body)} bytes)"}
    if not body.startswith(b"%PDF"):
        return {**entry, "error": "magic bytes are not %PDF (blocked or moved?)"}
    path = dest_dir / _safe_name(form)
    path.write_bytes(body)
    return {
        **entry,
        "file": path.name,
        "bytes": len(body),
        "sha256": hashlib.sha256(body).hexdigest(),
    }


async def fetch_library(dest_dir: Path = LIBRARY_DIR) -> dict:
    """Download every unique registry form PDF; write manifest.json.
    Returns the manifest dict."""
    registry = load_registry()
    forms = registry.unique_pdf_forms()
    dest_dir.mkdir(parents=True, exist_ok=True)
    semaphore = asyncio.Semaphore(_CONCURRENCY)

    async with httpx.AsyncClient(
        timeout=_TIMEOUT, headers={"User-Agent": "yunaki-forms-library/0.1"}
    ) as client:

        async def bounded(form: FormRef) -> dict:
            async with semaphore:
                return await _fetch_one(client, form, dest_dir)

        entries = await asyncio.gather(*(bounded(f) for f in forms))

    manifest = {
        "registry_version": registry.version,
        "fetched_on": date.today().isoformat(),
        "forms": sorted(entries, key=lambda e: e["form_id"]),
        "failed": sorted(
            (e["form_id"] for e in entries if "error" in e)
        ),
    }
    (dest_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    return manifest


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    manifest = asyncio.run(fetch_library())
    ok = [e for e in manifest["forms"] if "error" not in e]
    logger.info("stored %d/%d form PDFs in %s", len(ok), len(manifest["forms"]), LIBRARY_DIR)
    for entry in manifest["forms"]:
        if "error" in entry:
            logger.error("FAILED %s: %s", entry["form_id"], entry["error"])
    return 1 if manifest["failed"] else 0


if __name__ == "__main__":
    sys.exit(main())
