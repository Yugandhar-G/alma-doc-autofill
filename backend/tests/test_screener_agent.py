"""Verification agent offline: scripted model turns + fake tools. Proves the
loop mechanics — budget, fetch allow-listing, transcript audit — without
network or a key."""
from types import SimpleNamespace

import pytest
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage

from app.schemas import ClaimVerification, EvidenceMatrix, IntakeAnswers, ProfileVerification
from app.screener import agent as agent_module
from app.screener.agent import AgentTranscript, _audit_verification, run_verification_agent
from app.screener.tools.fetch_page import check_url_allowed, html_to_text

MATRIX = EvidenceMatrix(
    items=[
        {
            "claim": "Received the MICCAI Best Paper Award 2023",
            "criterion_ids": ["awards"],
            "sources": [{"kind": "answer", "ref": "awards[0]"}],
        }
    ]
)
INTAKE = IntakeAnswers(field_of_endeavor="Medical imaging ML")


# ---- fetch_page SSRF guards (pure, no network) ----

@pytest.mark.parametrize(
    "url,reason_fragment",
    [
        ("ftp://example.com/x", "http/https"),
        ("http://localhost/admin", "non-public"),
        ("http://127.0.0.1/", "non-public"),
        ("http://169.254.169.254/latest/meta-data", "non-public"),
        ("http://10.0.0.5/internal", "non-public"),
        ("http://example.com:8080/", "port"),
        ("http:///nohost", "no host"),
    ],
)
def test_fetch_refuses_unsafe_urls(url, reason_fragment):
    reason = check_url_allowed(url)
    assert reason is not None and reason_fragment in reason


def test_html_to_text_strips_script_and_style():
    html = "<html><head><style>x{}</style></head><body><script>evil()</script><p>Real  text</p></body></html>"
    assert html_to_text(html) == "Real text"


# ---- transcript audit (pure) ----

def _verification(status, urls):
    return ProfileVerification(
        identity_confidence="high",
        verifications=[
            ClaimVerification(claim="c", status=status, evidence_urls=urls)
        ],
    )


def test_audit_strips_urls_never_seen_and_downgrades():
    transcript = AgentTranscript(seen_urls=["https://real.example/a"], tool_calls=3)
    v = _verification("verified", ["https://real.example/a", "https://invented.example/b"])
    audited = _audit_verification(v, transcript)
    assert audited.verifications[0].evidence_urls == ["https://real.example/a"]
    assert audited.verifications[0].status == "verified"
    assert audited.tool_calls_used == 3

    ghost = _verification("contradicted", ["https://invented.example/b"])
    audited = _audit_verification(ghost, transcript)
    assert audited.verifications[0].evidence_urls == []
    assert audited.verifications[0].status == "unverified"  # strong status needs evidence


def test_audit_leaves_unverified_alone():
    audited = _audit_verification(
        _verification("unverified", []), AgentTranscript()
    )
    assert audited.verifications[0].status == "unverified"


# ---- the loop itself, with a scripted model ----

def _tool_call_msg(*calls):
    return AIMessage(
        content="",
        tool_calls=[
            {"name": name, "args": args, "id": f"call_{i}"}
            for i, (name, args) in enumerate(calls)
        ],
    )


class ScriptedChatModel(FakeMessagesListChatModel):
    """Scripted turns for the deepagents loop; tool binding is a no-op so
    the script alone decides what the 'model' calls."""

    def bind_tools(self, tools, **kwargs):
        return self


@pytest.fixture
def scripted_agent(monkeypatch):
    """Model turns: search → fetch(seen url) + fetch(unseen url) → done."""
    turns = [
        _tool_call_msg(
            ("search_web", {"query": "MICCAI Best Paper Award 2023 winner"}),
        ),
        _tool_call_msg(
            ("fetch_page", {"url": "https://miccai.example/awards"}),
            ("fetch_page", {"url": "https://attacker.example/exfil"}),
        ),
        AIMessage(content="Investigation complete."),
    ]

    monkeypatch.setattr(
        agent_module,
        "make_agent_model",
        lambda settings, live=False: ScriptedChatModel(responses=list(turns)),
    )
    # Distillation client is unused by the faked call_gemini below.
    monkeypatch.setattr(agent_module, "make_client", lambda s: None)

    async def fake_search(query, settings):
        return "The award page confirms the 2023 winner.", ["https://miccai.example/awards"]

    monkeypatch.setattr(agent_module, "grounded_search", fake_search)

    async def fake_fetch(url):
        return f"<untrusted_web_content url={url!r}>\nWinner list 2023\n</untrusted_web_content>"

    monkeypatch.setattr(agent_module, "fetch_page", fake_fetch)

    async def fake_distill(client, model, prompt, wrapper, settings, **kwargs):
        return ProfileVerification(
            identity_confidence="high",
            verifications=[
                ClaimVerification(
                    claim=MATRIX.items[0].claim,
                    status="verified",
                    evidence_urls=["https://miccai.example/awards", "https://made-up.example/x"],
                )
            ],
        )

    monkeypatch.setattr(agent_module, "call_gemini", fake_distill)


async def test_agent_loop_budget_allowlist_and_audit(scripted_agent):
    settings = SimpleNamespace(
        screener_agent_max_tool_calls=10, gemini_model="fake", gemini_api_key="k",
        extraction_temperature=0.0, extraction_max_retries=1,
    )
    events = []
    verification, transcript = await run_verification_agent(
        INTAKE, MATRIX, settings, events.append, live=False
    )
    # search happened, allowed fetch happened, unseen-url fetch was refused.
    assert transcript.tool_calls == 3
    assert transcript.seen_urls == ["https://miccai.example/awards"]
    assert transcript.fetched_urls == ["https://miccai.example/awards"]
    refused = [
        e for e in events
        if e["type"] == "tool_result" and "FETCH_REFUSED" in e.get("summary", "")
    ]
    assert len(refused) == 1  # the attacker.example fetch never left the process
    # Audit stripped the invented url from the distilled verification.
    assert verification.verifications[0].evidence_urls == ["https://miccai.example/awards"]
    assert verification.tool_calls_used == 3
    # Activity feed saw genuine tool activity.
    kinds = [e["type"] for e in events]
    assert "tool_call" in kinds and "tool_result" in kinds


async def test_non_granted_tool_call_is_blocked():
    """Grants are structural: a model call to a deepagents builtin outside
    the granted registry is refused at the execution layer, not just hidden
    from the declarations."""
    from app.kernel.agent import AgentBudget, run_tool_loop
    from app.kernel.tools.registry import ToolContext
    from app.screener.agent import _build_registry

    turns = [
        _tool_call_msg(("write_file", {"file_path": "/tmp/pwn", "content": "x"})),
        AIMessage(content="done."),
    ]
    transcript = AgentTranscript()
    ctx = ToolContext(
        settings=SimpleNamespace(), transcript=transcript,
        emit=lambda e: None, node="t",
    )
    await run_tool_loop(
        model=ScriptedChatModel(responses=turns),
        task_prompt="p",
        tools=_build_registry(),
        budget=AgentBudget(max_tool_calls=5),
        ctx=ctx,
    )
    assert transcript.tool_calls == 0  # nothing granted was ever dispatched


async def test_agent_respects_tool_budget(scripted_agent, monkeypatch):
    settings = SimpleNamespace(
        screener_agent_max_tool_calls=1, gemini_model="fake", gemini_api_key="k",
        extraction_temperature=0.0, extraction_max_retries=1,
    )
    events = []
    _, transcript = await run_verification_agent(
        INTAKE, MATRIX, settings, events.append, live=False
    )
    assert transcript.tool_calls == 1  # budget hard-stops the loop