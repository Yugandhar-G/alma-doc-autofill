# Frontend — Yunaki G-28 Document Autofill

Next.js (App Router, TypeScript, Tailwind v4) UI for the document-automation pipeline. This is the human-in-the-loop gate: upload passport + G-28, review and edit every extracted field, then trigger population and inspect the verification report.

## Run

```bash
npm install
npm run dev        # http://localhost:3000
```

The backend is expected at `http://localhost:8000`. Override with `NEXT_PUBLIC_API_URL` (see `.env.example`).

## Structure

- `src/lib/config.ts` — the only place the backend origin and upload limits live
- `src/lib/types.ts` — TypeScript mirrors of the backend Pydantic schemas (backend is source of truth)
- `src/lib/api.ts` — typed client for `/api/health`, `/api/extract`, `/api/populate`
- `src/components/flow/` — stage orchestration and progress indicator
- `src/components/upload/` — drag-and-drop slots with magic-byte validation and previews
- `src/components/review/` — editable review sections (Part 1–3 + passport) with warnings
- `src/components/report/` — population report: summary chips + read-back diff table

## Checks

```bash
npm run build
npm run lint
```
