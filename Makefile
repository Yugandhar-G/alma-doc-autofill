.PHONY: install dev backend frontend test populate-demo \
        desktop-sidecar desktop-dev desktop-build

install:
	cd backend && python3 -m venv .venv && .venv/bin/pip install -e ".[dev]" && .venv/bin/playwright install chromium
	cd frontend && npm install

backend:
	cd backend && .venv/bin/uvicorn app.main:app --reload --port 8000

frontend:
	cd frontend && npm run dev

dev:
	$(MAKE) -j2 backend frontend

test:
	cd backend && .venv/bin/pytest -v

populate-demo:
	cd backend && .venv/bin/python -m app.population.demo

# --- Desktop (Tauri 2) -------------------------------------------------------
# Prereqs: Rust toolchain + tauri-cli (`cargo install tauri-cli --version '^2'`),
# and the backend desktop extra (`cd backend && .venv/bin/pip install -e ".[desktop]"`).

# Freeze the FastAPI kernel into the PyInstaller one-dir sidecar.
desktop-sidecar:
	desktop/scripts/build-sidecar.sh

# Dev loop: Next dev server (:3000) + Tauri window against it. The sidecar runs
# straight from the backend venv (no freeze needed) — see src-tauri/src/main.rs.
desktop-dev:
	cd frontend && npm run dev &
	cd desktop/src-tauri && cargo tauri dev

# Full production build: static Next export -> sidecar freeze -> Tauri bundle
# (dmg + nsis). frontend/out must exist before generate_context! runs.
desktop-build:
	cd frontend && npm run build:desktop
	$(MAKE) desktop-sidecar
	cd desktop/src-tauri && cargo tauri build

# --- Demo week: integrated firm flow (our lane + Nanda's Yunaki-Yew) ---------
# Prereqs: clone github.com/Nanda-Kiran/Yunaki-Yew to ~/Yunaki-Yew, check out
# integration/yunaki-core-bridge, create .venv (python3.13) and install his
# requirements + our demo package editable (see demo/README.md).
YEW_REPO ?= $(HOME)/Yunaki-Yew

# Nanda's app wired to the shared DB: sends route through our sendgate,
# handoffs open his cases, accepted intake lands in our case_history.
yew:
	cd $(YEW_REPO) && \
	YUNAKI_DB=yew.db \
	YUNAKI_SHARED_DB=$(CURDIR)/demo/yunaki.db \
	YUNAKI_EMAIL_PROVIDER=sendgate \
	YUNAKI_PORTAL_BASE=http://localhost:8801 \
	.venv/bin/python -m uvicorn app.main:app --port 8801

# Our Slack agent process (Bolt Socket Mode; needs tokens in demo/.env).
slack:
	cd demo && .venv/bin/python -m slack_agent.main

# The whole firm demo: his portal + our Slack agent on one shared DB.
firm-demo:
	$(MAKE) -j2 yew slack

# Live end-to-end proof of every bridge seam (no Slack/Gmail creds needed).
flow-smoke:
	cd demo && YEW_REPO=$(YEW_REPO) .venv/bin/python -m scripts.integrated_flow_smoke
