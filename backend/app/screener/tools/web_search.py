"""Grounded web search backend for the verification agent's search_web tool.

Uses Gemini's built-in google_search grounding (no extra vendor, no extra
API key). One nested request per tool call: grounded free-text research plus
the URLs the grounding actually consulted — those URLs are the deterministic
allow-list for fetch_page and for the citation audit.

Retrieved text is data, never instructions; the agent prompt and the
distillation step both treat it as untrusted.
"""
import logging

from google.genai import types as genai_types

from app.config import Settings
from app.observability import llm_generation, record_usage
from app.screener.nodes.common import make_client

logger = logging.getLogger("yunaki.screener.web")

_MAX_RESEARCH_CHARS = 8000


async def grounded_search(query: str, settings: Settings) -> tuple[str, list[str]]:
    """(research text, source urls). Degrades to an error string + no urls —
    the agent can reason about a failed search; it never crashes the run."""
    client = make_client(settings)
    try:
        with llm_generation(
            "gemini.screener.web_search",
            model=settings.gemini_model,
            metadata={"query_chars": len(query)},
        ) as generation:
            response = await client.aio.models.generate_content(
                model=settings.gemini_model,
                contents=query,
                config=genai_types.GenerateContentConfig(
                    tools=[genai_types.Tool(google_search=genai_types.GoogleSearch())],
                ),
            )
            record_usage(generation, getattr(response, "usage_metadata", None))
    except Exception as exc:
        logger.warning("grounded search failed err=%s", type(exc).__name__)
        return f"SEARCH_FAILED: {type(exc).__name__}", []
    return (response.text or "")[:_MAX_RESEARCH_CHARS], _grounding_urls(response)


def _grounding_urls(response) -> list[str]:
    """URLs the grounding call actually consulted, from grounding_metadata."""
    urls: list[str] = []
    for candidate in response.candidates or []:
        meta = getattr(candidate, "grounding_metadata", None)
        if meta is None:
            continue
        for chunk in getattr(meta, "grounding_chunks", None) or []:
            web = getattr(chunk, "web", None)
            uri = getattr(web, "uri", None) if web else None
            if uri and uri not in urls:
                urls.append(uri)
    return urls
