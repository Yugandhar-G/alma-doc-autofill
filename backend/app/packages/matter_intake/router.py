"""Matter-intake HTTP surface — mounted under /api/packages/matter_intake.

Carries the ask-the-matter research endpoint (the chase + planner graphs run on
the matter path via WorkflowService, so they need no router of their own).

POST /matters/{matter_id}/ask {question} → a sync, firm-scoped, ref-audited
ResearchAnswer. The acting firm scope comes from the same auth principal every
matter route uses; the matter is confirmed in-firm before the agent runs, so a
question about another firm's matter is a plain not-found."""
import logging

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.config import Settings, get_settings
from app.kernel.auth import Principal, get_principal, scope_of
from app.kernel.store.base import MatterStore, get_matter_store
from app.packages.matter_intake.ask import ask_matter
from app.schemas import ApiResponse

logger = logging.getLogger("yunaki.matter_intake.router")


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)


def router_factory() -> APIRouter:
    router = APIRouter()

    @router.post("/matters/{matter_id}/ask")
    async def ask(
        matter_id: str,
        req: AskRequest,
        principal: Principal = Depends(get_principal),
        settings: Settings = Depends(get_settings),
        store: MatterStore = Depends(get_matter_store),
    ) -> ApiResponse:
        scope = scope_of(principal)
        matter = await store.get_matter(scope, matter_id)
        if matter is None:
            return ApiResponse(success=False, error="Matter not found.")
        answer = await ask_matter(scope, matter_id, req.question, settings, store)
        return ApiResponse(success=True, data=answer.model_dump())

    return router
