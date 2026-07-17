"""Verification agent offline: scripted model turns + fake tools. Proves the
loop mechanics — budget, fetch allow-listing, transcript audit — without
network or a key."""
from types import SimpleNamespace

import pytest

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

def _fc(name, **args):
    return SimpleNamespace(
        text=None, thought=False,
        function_call=SimpleNamespace(name=name, args=args),
    )


def _text_part(text):
    return SimpleNamespace(text=text, thought=False, function_call=None)


def _response(parts):
    content = SimpleNamespace(parts=parts, role="model")
    return SimpleNamespace(
        candidates=[SimpleNamespace(content=content)], usage_metadata=None
    )


@pytest.fixture
def scripted_agent(monkeypatch):
    """Model turns: search → fetch(seen url) + fetch(unseen url) → done."""
    turns = [
        _response([_fc("search_web", query="MICCAI Best Paper Award 2023 winner")]),
        _response([
            _fc("fetch_page", url="https://miccai.example/awards"),
            _fc("fetch_page", url="https://attacker.example/exfil"),
        ]),
        _response([_text_part("Investigation complete.")]),
    ]
    calls = {"n": 0}

    class FakeModels:
        async def generate_content(self, model, contents, config):
            turn = turns[min(calls["n"], len(turns) - 1)]
            calls["n"] += 1
            return turn

    class FakeClient:
        aio = SimpleNamespace(models=FakeModels())

    monkeypatch.setattr(agent_module, "make_client", lambda s: FakeClient())

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
    return calls


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