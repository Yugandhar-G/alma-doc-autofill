# Field Map — target form recon + mapping spec

Target: https://mendrika-alma.github.io/form-submission/ ("Form A-28").
Static HTML (no JS rendering). Snapshot: `backend/tests/data/form_snapshot.html` (fetched 2026-07-01).
Machine-readable mapping: `backend/app/population/field_map.py` (the allow-list the fill routine iterates).

## Recon findings (why the mapping looks the way it does)

1. **Duplicate-id trap.** Part 3 `1.b First Name(s)` and `1.c Middle Name(s)` both have `id="passport-given-names"` and `name="passport-given-names"`; both labels point `for=` the same id. Label- or id-based selection targets the wrong input or throws strict-mode. Middle name is filled positionally: `locator('input[name="passport-given-names"]').nth(1)`.
2. **Pseudo-radio.** Part 2 1.c ("am" / "am not" subject to discipline) is two independent checkboxes `#am-subject` / `#not-subject` with no exclusivity. Exactly one is checked based on the extracted boolean; null → neither.
3. **State select** (`#state`): option values are 2-letter codes (`CA`), labels full names (`California`). Extraction normalizes to full names → population uses `select_option(label=...)`.
4. **Sex select** (`#passport-sex`): values `M`/`F`/`X` — extraction normalizes to single letters → `select_option(value=...)`.
5. **Date inputs** are `input[type="date"]` everywhere → Playwright `fill()` requires `YYYY-MM-DD`, which extraction produces by contract.
6. **`<span for=>` pseudo-labels** on Part 2 checkboxes 1.a/2.a — invisible to `get_by_label`. Hence the id-keyed allow-list instead of label-first selectors.
7. **No submit button exists** anywhere in the form. Part 4/5 contain `#client-signature-date` / `#attorney-signature-date` (never touched) and empty signature divs.

## Source → form mapping

| Form control | Type | Source (schema path) |
|---|---|---|
| `#online-account` | text | g28.attorney.online_account_number |
| `#family-name` / `#given-name` / `#middle-name` | text | g28.attorney.{family,given,middle}_name |
| `#street-number` | text | g28.attorney.street_number_and_name |
| `#apt` `#ste` `#flr` + `#apt-number` | checkbox + text | g28.attorney.apt_ste_flr(_number) — N/A → all skipped |
| `#city` / `#zip` / `#country` | text | g28.attorney.{city,zip_code,country} |
| `#state` | select (label match) | g28.attorney.state |
| `#daytime-phone` / `#mobile-phone` / `#email` | text | g28.attorney.{daytime_phone,mobile_phone,email} |
| `#attorney-eligible` | checkbox | g28.eligibility.is_attorney |
| `#licensing-authority` / `#bar-number` / `#law-firm` | text | g28.eligibility.{licensing_authority,bar_number,law_firm} |
| `#not-subject` / `#am-subject` | checkbox pair | g28.eligibility.subject_to_discipline (False / True) |
| `#accredited-rep` … `#student-name` | mixed | g28.eligibility.* (usually null for attorney filings) |
| `#passport-surname` | text | passport.surname |
| `input[name=passport-given-names]` nth=0 / nth=1 | text | passport.given_names / passport.middle_names |
| `#passport-number` / `#passport-country` / `#passport-nationality` | text | passport.{passport_number,country_of_issue,nationality} |
| `#passport-dob` / `#passport-issue-date` / `#passport-expiry-date` | date | passport ISO dates |
| `#passport-pob` | text | passport.place_of_birth |
| `#passport-sex` | select (value M/F/X) | passport.sex |

**Never touched:** Part 4 (consent checkboxes `#notices-to-attorney`, `#documents-to-attorney`, `#docs-to-me` — client elections, not extractable data — and `#client-signature-date`), Part 5 (`#attorney-signature-date`), signature fields.

**Dropped gracefully (no target on form):** G-28 fax number, non-US province/postal code fields.

**Cross-document join:** beneficiary name on the G-28 ↔ passport name (fuzzy compare → review-table warning on mismatch).
