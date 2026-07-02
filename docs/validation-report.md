# Validation Report — 20 Synthetic G-28 Samples

Generated variants of the example G-28 (names with diacritics/apostrophes/
hyphens, 15+ states, N/A traps on email and bar number, filled-mobile,
abbreviation normalization) run through live Gemini extraction, scored
field-by-field against known ground truth, then populated into the form
snapshot with post-fill read-back verification.

| # | Sample | Fields OK | Wrong | Missed | Fabricated | Populate |
|---|--------|-----------|-------|--------|------------|----------|
| 01 | 01-baseline-texas | 29/29 | 0 | 0 | 0 | 17 filled / 0 mm / 0 err ✓ |
| 02 | 02-apostrophe-newyork | 29/29 | 0 | 0 | 0 | 17 filled / 0 mm / 0 err ✓ |
| 03 | 03-hyphenated-florida | 29/29 | 0 | 0 | 0 | 17 filled / 0 mm / 0 err ✓ |
| 04 | 04-na-email-illinois | 29/29 | 0 | 0 | 0 | 16 filled / 0 mm / 0 err ✓ |
| 05 | 05-mobile-filled-washington | 29/29 | 0 | 0 | 0 | 18 filled / 0 mm / 0 err ✓ |
| 06 | 06-diacritics-massachusetts | 29/29 | 0 | 0 | 0 | 17 filled / 0 mm / 0 err ✓ |
| 07 | 07-dc-district | 29/29 | 0 | 0 | 0 | 17 filled / 0 mm / 0 err ✓ |
| 08 | 08-long-firm-georgia | 29/29 | 0 | 0 | 0 | 17 filled / 0 mm / 0 err ✓ |
| 09 | 09-na-bar-arizona | 29/29 | 0 | 0 | 0 | 16 filled / 0 mm / 0 err ✓ |
| 10 | 10-colorado-street | 29/29 | 0 | 0 | 0 | 17 filled / 0 mm / 0 err ✓ |
| 11 | 11-oregon-email-plus | 29/29 | 0 | 0 | 0 | 17 filled / 0 mm / 0 err ✓ |
| 12 | 12-michigan-beneficiary | 29/29 | 0 | 0 | 0 | 17 filled / 0 mm / 0 err ✓ |
| 13 | 13-northcarolina-numbers | 29/29 | 0 | 0 | 0 | 17 filled / 0 mm / 0 err ✓ |
| 14 | 14-newjersey-country | 29/29 | 0 | 0 | 0 | 17 filled / 0 mm / 0 err ✓ |
| 15 | 15-virginia-licensing | 29/29 | 0 | 0 | 0 | 17 filled / 0 mm / 0 err ✓ |
| 16 | 16-pennsylvania-all-caps | 29/29 | 0 | 0 | 0 | 17 filled / 0 mm / 0 err ✓ |
| 17 | 17-minnesota-short-names | 29/29 | 0 | 0 | 0 | 17 filled / 0 mm / 0 err ✓ |
| 18 | 18-nevada-email-na-mobile | 29/29 | 0 | 0 | 0 | 18 filled / 0 mm / 0 err ✓ |
| 19 | 19-ohio-firm-punctuation | 29/29 | 0 | 0 | 0 | 17 filled / 0 mm / 0 err ✓ |
| 20 | 20-california-control | 29/29 | 0 | 0 | 0 | 17 filled / 0 mm / 0 err ✓ |

## Aggregate

- **Field accuracy:** 580/580 (100.0%)
- **Document accuracy (all fields correct):** 20/20
- **Fabricated values (expected null, got value):** 0
- **Missed values (expected value, got null):** 0
- **Wrong values:** 0
- **Population runs clean (0 mismatch / 0 error):** 20/20

No field errors across any sample.
