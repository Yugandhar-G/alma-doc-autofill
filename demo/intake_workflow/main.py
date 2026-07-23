"""FastAPI shell. FROZEN for parallel work: router module paths and the
``router`` variable names below are the contract with the web layer."""
from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from intake_workflow.store import Store


def create_app() -> FastAPI:
    app = FastAPI(title="Yunaki — Intake Workflow")
    app.state.store = Store()

    uploads_dir = Path(os.environ.get("YUNAKI_UPLOADS", "uploads/intake"))
    uploads_dir.mkdir(parents=True, exist_ok=True)
    app.state.uploads_dir = uploads_dir

    from intake_workflow.web.auth import auth_router
    from intake_workflow.web.routes_client import router as client_router
    from intake_workflow.web.routes_staff import router as staff_router

    app.include_router(auth_router)
    app.include_router(staff_router)
    app.include_router(client_router)

    from intake_workflow.integration import config as _bridge
    if _bridge.enabled():
        from intake_workflow.integration.handoff_consumer import HandoffConsumer
        _consumer = HandoffConsumer()
        # Start on the ASGI startup event, not in create_app()'s body: bare
        # create_app() calls (tests, tooling) must never leak a poller thread
        # against whatever DB_PATH happens to be ambient.
        app.router.add_event_handler(
            "startup", lambda: _consumer.start(app.state.store)
        )
        app.router.add_event_handler("shutdown", _consumer.stop)

    static_dir = Path(__file__).parent / "static"
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    @app.get("/", include_in_schema=False)
    def index() -> RedirectResponse:
        return RedirectResponse("/staff")

    return app


app = create_app()
