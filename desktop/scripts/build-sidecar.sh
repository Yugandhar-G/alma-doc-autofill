#!/usr/bin/env bash
#
# Build the FastAPI kernel into a self-contained PyInstaller one-dir binary that
# the Tauri shell spawns as a sidecar. Output: desktop/dist/yunaki-sidecar/ with
# an executable named `yunaki-sidecar`.
#
# Why one-dir (not one-file): faster cold start (no per-launch unpack to a temp
# dir), and Tauri bundles the whole directory as a resource cleanly.
#
# Run from a machine with the backend venv + the desktop extra installed:
#     cd backend && .venv/bin/pip install -e ".[dev,desktop]"
#     desktop/scripts/build-sidecar.sh
#
set -euo pipefail

# Resolve repo paths relative to this script so it runs from anywhere.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DESKTOP_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO_ROOT="$(cd "$DESKTOP_DIR/.." && pwd)"
BACKEND_DIR="$REPO_ROOT/backend"

PYINSTALLER="${PYINSTALLER:-$BACKEND_DIR/.venv/bin/pyinstaller}"
if [[ ! -x "$PYINSTALLER" ]]; then
  echo "error: pyinstaller not found at $PYINSTALLER" >&2
  echo "install it:  cd backend && .venv/bin/pip install -e \".[desktop]\"" >&2
  exit 1
fi

DIST_DIR="$DESKTOP_DIR/dist"
BUILD_DIR="$DESKTOP_DIR/build"

echo "==> Building yunaki-sidecar (one-dir) into $DIST_DIR"
cd "$BACKEND_DIR"

# Data files the app reads at runtime via Path(__file__).parent — PyInstaller
# preserves the package tree, but non-.py files are not auto-collected.
#   forms_registry.json : the forms knowledge base (app/forms/registry.py)
# The maps/ package (g28.py etc.) is ordinary Python and is collected as code.
#
# Hidden imports / collect-all: langgraph, deepagents, and the langchain
# integration packages import submodules dynamically (entrypoints, registries),
# which PyInstaller's static analysis misses. --collect-all pulls their code +
# data + metadata. google.genai and supabase also ship dynamic submodules.
# The langgraph_checkpoint* and langgraph_prebuilt distributions install INTO
# the `langgraph` namespace tree (langgraph/checkpoint/sqlite, langgraph/prebuilt),
# so --collect-all langgraph pulls their code. They still need their dist
# metadata copied because langgraph/langchain look up versions via
# importlib.metadata at import time.
"$PYINSTALLER" \
  --noconfirm \
  --name yunaki-sidecar \
  --distpath "$DIST_DIR" \
  --workpath "$BUILD_DIR" \
  --specpath "$BUILD_DIR" \
  --add-data "$BACKEND_DIR/app/forms/data/forms_registry.json:app/forms/data" \
  --collect-submodules app \
  --collect-all langgraph \
  --collect-all langchain_core \
  --collect-all langchain_google_genai \
  --collect-all deepagents \
  --collect-all google.genai \
  --collect-all supabase \
  --collect-all langfuse \
  --copy-metadata langgraph \
  --copy-metadata langgraph-checkpoint \
  --copy-metadata langgraph-checkpoint-sqlite \
  --copy-metadata langgraph-prebuilt \
  --copy-metadata deepagents \
  "$BACKEND_DIR/desktop_entry.py"

echo "==> Built: $DIST_DIR/yunaki-sidecar/yunaki-sidecar"
echo "    Smoke-test it with: desktop/scripts/build-sidecar.sh --verify"
