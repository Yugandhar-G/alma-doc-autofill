# Security Model — Yunaki

Yunaki runs as a local-first desktop app: a Tauri shell renders the frontend and
spawns the FastAPI kernel as an on-device sidecar. Documents are processed
locally; nothing is uploaded, submitted, or signed. This document summarizes the
security seams and where each is enforced. It is a map, not a substitute for
reading the code.

## 1. Tenancy wall (defense in depth)

Firm isolation is enforced at **two independent layers**, so a bug in one does
not open cross-firm access.

- **Store layer (primary).** Every data-access method on `MatterStore`
  (`backend/app/kernel/store/`) except the three firm-bootstrap calls takes a
  `TenantScope` as its first argument and filters every query by
  `scope.firm_id` *inside* the implementation. A router or service cannot
  express a cross-firm read — there is no code path that fetches a row without
  its `firm_id` being matched first. The acting scope is derived from the
  request `Principal` (`backend/app/kernel/auth.py`) and is frozen for the
  request's lifetime.
- **Database layer (RLS, defense in depth).** `supabase/migrations/0002_rls_policies.sql`
  enables row-level security and firm-scoped policies on all eight tables. The
  **backend uses the service-role key, which bypasses RLS by design** — the
  store layer is the wall for backend traffic. RLS protects the *other* client:
  the anon/authenticated Supabase client used by the frontend (`@supabase/ssr`),
  which authenticates as the signed-in firm user. Policies resolve the caller's
  firm through a `SECURITY DEFINER` helper (`current_firm_id()`) that joins
  `users.auth_provider_id = auth.uid()` — mirroring exactly how `auth.py` maps a
  token subject to a firm member. The app does **not** put `firm_id` in the JWT.

## 2. Token model

- **Per-launch sidecar bearer.** On every launch the Tauri shell reserves a
  loopback port, mints a fresh uuid-v4 bearer token, and spawns the sidecar with
  it. The frontend reads it from the injected `window.__YUNAKI_API__` and sends
  `Authorization: Bearer <token>` on every request. `BearerTokenMiddleware`
  (`backend/desktop_entry.py`) rejects any request without the exact token
  (constant-time compare). The token is never persisted or logged. Running the
  sidecar by hand with no `--token` disables enforcement (dev only).
- **Firm auth (server / synced mode).** When Supabase is configured, requests
  carry a GoTrue HS256 access token verified statelessly (signature, expiry,
  audience) and mapped to a provisioned `User`. When Supabase is not configured,
  the app runs in no-account local mode with a single auto-provisioned firm and
  no header required — the local desktop path needs no credentials it cannot
  have.
- **Scoped download tokens.** A browser `<a href>` download carries no
  Authorization header. The single artifact-GET route
  (`GET /api/population-artifact/{id}`) therefore also accepts a short-lived
  HMAC token as `?t=` (`mint_download_token` / `verify_download_token` in
  `auth.py`), signed over `(artifact_id, expiry)` and scoped to one id for a few
  minutes. Minting is behind `get_principal` (`POST .../link`); a
  present-but-invalid token is a hard 403; a forged token for another id never
  serves. The sidecar middleware structurally exempts only this route when a
  `?t=` is present, and the handler does the cryptographic check.

## 3. Rate limiting

An in-process fixed-window limiter (`backend/app/kernel/ratelimit.py`), keyed by
`(firm_id, route_class)`, throttles write / run-start / auth-adjacent endpoints
(matter create, document upload, run start/resume, ask-the-matter); reads are
unthrottled. Breaches return `429` in the standard `ApiResponse` envelope.
In-memory is correct for the single-process desktop sidecar; a Redis-backed
counter is the documented seam for a future multi-node server (same
`RateLimiter.check` signature).

## 4. Agent guardrails

- **Grant enforcement.** Tool access is gated by recorded `tool_grants`; an
  agent can only call the firm-data and web tools it was granted.
- **Citation audit.** Every screener claim/verdict better than `not_met` must
  cite a source (intake `answer_id`, a document hash + verbatim excerpt, or a
  grounded URL). `backend/app/screener/citations.py` audits deterministically:
  invalid refs are stripped and uncited positive verdicts are downgraded to
  `not_met` with a warning.
- **Overclaim gate.** An overclaim is the worst defect class. Live screener
  validation exits non-zero on any overclaim, and verification statuses without
  surviving evidence downgrade to `unverified` (absence of evidence is never
  "contradicted").
- **Untrusted web content.** The verification agent may only fetch URLs surfaced
  by its own searches, every hop re-passes the SSRF guard, fetched content is
  length-capped and delimiter-wrapped, and evidence URLs are transcript-audited
  (a URL the agent never saw is stripped).
- **Population safety.** Selectors come only from an allow-list
  (`backend/app/population/field_map.py`); submit/sign selectors never appear in
  population code. Nulls are skipped, never typed; the app never submits or
  signs.

## 5. PII channels (two, kept separate)

- **Product channel.** Response bodies and the session-owner SSE stream may
  carry the caller's own extracted values, excerpts, and model thinking — that
  is the product (a genuine activity feed).
- **Observability channel.** Langfuse traces and server logs carry only content
  hashes, criterion ids, counts, and **masked** field previews (dates →
  `****-**-**`, other values first-character-only —
  `backend/app/kernel/observability.py`). Documents are referenced by content
  hash. The same event object is never sent to both channels. `uploads/` and
  test fixtures are gitignored; secrets live in `.env` only.

## 6. Upload guardrails

Magic-byte format sniffing (never by extension), a 10 MB size cap, a 10-page PDF
cap, and a resolution/blur gate run before any LLM call. Pydantic validates all
LLM output; invalid JSON gets one retry then a loud failure. A wrong document in
a slot surfaces a `document_type_detected` mismatch rather than being extracted
anyway.

## Reporting

This is a take-home / prototype build. For a production deployment, route
security reports to a monitored inbox and rotate any exposed secret immediately.
