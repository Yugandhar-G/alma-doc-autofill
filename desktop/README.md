# Yunaki Desktop (Tauri 2)

Native desktop packaging of Yunaki. A Tauri 2 shell renders the Next.js static
export in the system webview and runs the FastAPI kernel as a local sidecar. All
agent work and document processing happen on-device; nothing is uploaded and
nothing is submitted or signed.

macOS is the current target. Windows is scaffolded (bundle target + per-OS
branches are in place) but unverified — it needs a Windows machine and a signing
certificate.

## Architecture

```
┌─ Yunaki.app ─────────────────────────────────────────────┐
│  Tauri shell (Rust, src-tauri/src/main.rs)                │
│   1. reserve a free 127.0.0.1 port                        │
│   2. mint a per-launch bearer token (uuid v4)             │
│   3. spawn the sidecar: --port <p> --token <t>            │
│   4. poll GET /api/health (with token) until ready        │
│   5. create the window, inject window.__YUNAKI_API__      │
│   6. load the exported frontend (frontendDist)            │
│   7. kill the sidecar on exit                             │
│                                                            │
│  WebView  ── fetch http://127.0.0.1:<p> (Bearer <t>) ──▶  │
│                                                            │
│  Sidecar (PyInstaller one-dir, backend/desktop_entry.py)  │
│   uvicorn app.main:app on 127.0.0.1:<p>, token-gated      │
└────────────────────────────────────────────────────────────┘
```

Population uses the native PDF fill engine (`backend/app/forms/fill.py`), so the
desktop build does **not** bundle Chromium or require any browser download.
Playwright stays a backend dependency for the legacy HTML form target only.

## Prerequisites

- **Rust toolchain** — <https://rustup.rs> (`rustc`, `cargo`).
- **Tauri CLI v2** — `cargo install tauri-cli --version '^2'` (gives `cargo tauri`).
- **Platform toolchain**
  - macOS: Xcode Command Line Tools (`xcode-select --install`).
  - Windows: MSVC Build Tools + WebView2 runtime (ships with Win 11).
- **Backend desktop extra** — `cd backend && .venv/bin/pip install -e ".[dev,desktop]"`
  (adds PyInstaller).
- **Node** for the frontend export (already required by the repo).

## Build steps

From the repo root:

```bash
# 1. Static frontend export (writes frontend/out/, zero dynamic segments)
cd frontend && npm run build:desktop

# 2. Freeze the FastAPI kernel into the sidecar (writes desktop/dist/yunaki-sidecar/)
desktop/scripts/build-sidecar.sh

# 3. Bundle the app (dmg + nsis)
cd desktop/src-tauri && cargo tauri build
```

Or the one-shot make target that runs all three in order:

```bash
make desktop-build
```

Dev loop (Next dev server + live Tauri window, sidecar run from the venv so no
freeze is needed):

```bash
make desktop-dev
```

## Token / port handshake

There is no fixed port and no persisted credential. On every launch the shell:

1. binds `127.0.0.1:0` to get a free port, then releases it;
2. generates a uuid v4 bearer token;
3. spawns the sidecar with `--port <p> --token <t>`;
4. injects, before any page script runs:
   ```js
   window.__YUNAKI_API__ = { base: "http://127.0.0.1:<p>", token: "<t>" };
   ```

The frontend reads this at runtime (`frontend/src/lib/config.ts` → `getApiConfig`)
and attaches `Authorization: Bearer <t>` to every request (`lib/api.ts`). The
sidecar's `BearerTokenMiddleware` (`backend/desktop_entry.py`) rejects any HTTP
request without the exact token with a 401 — except CORS preflight (`OPTIONS`),
which carries no auth header. When no `--token` is passed (running the sidecar by
hand for debugging) enforcement is off.

On the web there is no shell, `window.__YUNAKI_API__` is undefined, the
build-time `NEXT_PUBLIC_API_URL` base is used, and no token header is sent —
behavior is identical to before.

## Static-export routing

Static export cannot prerender the two dynamic routes (`/matters/[id]`,
`/matters/[id]/runs/[runId]`) for arbitrary ids. The desktop build
(`NEXT_PUBLIC_DESKTOP=1`) therefore routes through static query-param twins that
render the exact same client components:

| Web (path style)                  | Desktop (query style)                     |
| --------------------------------- | ----------------------------------------- |
| `/matters/<id>`                   | `/matter?id=<id>`                         |
| `/matters/<id>/runs/<runId>?pkg=` | `/run?matterId=<id>&runId=<runId>&pkg=`   |

All internal links go through `frontend/src/lib/nav.ts` (`matterHref` /
`runHref`), which emits the correct style per build. The dynamic routes still
work in dev/web by delegating to the same shared components; under export they
emit a single inert `_` sentinel page each (never navigated to) so the exporter
accepts them — no `[id]` folders appear in `out/`.

## Secrets

`GEMINI_API_KEY` (and `SUPABASE_*`, `LANGFUSE_*`) reach the sidecar via inherited
process environment — set them in the shell that launches the app, or in
`backend/.env`, which the kernel's settings loader reads. Nothing is baked into
the bundle.

**Phase E2 seam:** a keychain-backed secret provider (macOS Keychain / Windows
Credential Manager) should replace the env passthrough so users enter the key
once in-app. The injection point is `resolve_sidecar()` in `src-tauri/src/main.rs`
(set `.env(...)` on the sidecar `Command`).

## Updater & signing

Producing a signed, auto-updating build requires real certificates and keys that
are deliberately **not** committed. The config placeholders (`plugins.updater`
inert, empty signing identities) ship inert so an unsigned local build still
runs; the checklists below turn each on. Do each once, then keep the secrets in
CI, never in the repo.

### macOS — Developer ID signing + notarization

Prerequisite: an Apple Developer account and a **Developer ID Application**
certificate installed in the login keychain.

1. Find the identity name: `security find-identity -v -p codesigning`
   → `Developer ID Application: Your Firm LLC (TEAMID)`.
2. Set `bundle.macOS.signingIdentity` in `tauri.conf.json` to that string (or
   export `APPLE_SIGNING_IDENTITY`).
3. Provide notarization credentials as env before `cargo tauri build` — use an
   app-specific password (create at appleid.apple.com), never your Apple ID
   password:
   ```bash
   export APPLE_ID="you@firm.com"
   export APPLE_PASSWORD="abcd-efgh-ijkl-mnop"   # app-specific password
   export APPLE_TEAM_ID="TEAMID"
   ```
   (Alternatively an API key: `APPLE_API_ISSUER`, `APPLE_API_KEY`,
   `APPLE_API_KEY_PATH`.)
4. `cargo tauri build` signs, submits to Apple's notary service, and staples the
   ticket to the `.dmg`/`.app`.
5. Verify: `spctl -a -vv Yunaki.app` → `accepted, source=Notarized Developer ID`
   and `codesign --verify --deep --strict Yunaki.app`.

Without this, Gatekeeper blocks the app on other machines ("cannot be opened
because the developer cannot be verified").

### Windows — Authenticode signing

Prerequisite: an **OV or EV code-signing certificate** (EV is required to avoid
SmartScreen warnings on first download).

1. Import the cert; note its SHA-1 thumbprint
   (`certutil -store My` or the Certificates MMC snap-in).
2. Set `bundle.windows.certificateThumbprint` in `tauri.conf.json` (or export
   `WINDOWS_CERTIFICATE` / `WINDOWS_CERTIFICATE_PASSWORD` for a PFX in CI).
3. Optional but recommended — pin the timestamp server so signatures outlive the
   cert: `bundle.windows.timestampUrl = "http://timestamp.digicert.com"`.
4. Build on Windows (`cargo tauri build`); the NSIS installer and `.exe` are
   signed via `signtool`.
5. Verify: `signtool verify /pa /v Yunaki_x64-setup.exe`.

### Tauri updater (auto-update channel)

1. Generate the signing keypair (private key stays OUT of the repo — store it in
   the CI secret store):
   ```bash
   cargo tauri signer generate -w ~/.tauri/yunaki-updater.key
   ```
   This prints a **public key** (minisign format) and writes the private key.
2. In `tauri.conf.json → plugins.updater`: set `active: true`, replace `pubkey`
   with the generated public key, and point `endpoints` at your release manifest
   URL (e.g. `https://releases.yourfirm.com/yunaki/{{target}}/{{arch}}/{{current_version}}`).
3. Add the plugin dependency and register it in `src-tauri/src/main.rs`
   (`tauri_plugin_updater::Builder`). Add `tauri-plugin-updater` to `Cargo.toml`.
4. Set `bundle.createUpdaterArtifacts: true` so the build emits the signed
   `.sig` files alongside each artifact.
5. On release, sign artifacts with the private key
   (`TAURI_SIGNING_PRIVATE_KEY` env during build) and publish them plus a
   `latest.json` manifest to the endpoint. The app checks the endpoint on launch
   and verifies each update's signature against the embedded public key before
   applying it — a tampered update is rejected.

## Windows notes (scaffolded, unverified)

- `bundle.targets` includes `nsis`; the shell branches use
  `http://tauri.localhost` as the webview origin and resolve the sidecar from
  `resource_dir()/yunaki-sidecar/yunaki-sidecar.exe`.
- Requires building `build-sidecar.sh`'s equivalent on Windows (PyInstaller
  produces a `.exe`; the shell script is bash — port it to PowerShell or run
  under Git Bash), plus WebView2 and a code-signing cert.
- Not run on a Windows machine yet — treat as a starting point.

## Layout

```
desktop/
├── README.md
├── scripts/build-sidecar.sh      # PyInstaller one-dir freeze
├── dist/                          # sidecar output (gitignored)
└── src-tauri/
    ├── Cargo.toml
    ├── build.rs
    ├── tauri.conf.json
    ├── capabilities/default.json
    ├── icons/                     # generated; regenerate via `cargo tauri icon`
    └── src/main.rs                # shell lifecycle
```
