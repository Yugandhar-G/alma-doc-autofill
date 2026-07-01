# Test fixtures (gitignored — contain example PII)

Drop these files here to enable the golden extraction tests:

- `Example_G-28.pdf` — the example G-28 from the assignment (alma-public-assets S3)
- `passport_sample.jpg` (or `.png` / `.pdf`) — any specimen passport image

`tests/test_extraction_golden.py` skips cleanly when these are absent.
Extraction results are cached in `tests/.extraction_cache/` (also gitignored) so
repeated test runs don't burn vision-API calls; delete the cache to force re-extraction.
