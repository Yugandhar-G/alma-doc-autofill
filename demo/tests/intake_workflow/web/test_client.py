"""Client magic-link portal route tests. Domain is monkeypatched."""
from __future__ import annotations

from datetime import date, datetime, timezone

from intake_workflow.domain import api
from intake_workflow.schemas import (
    AutoCheckFinding,
    FilingRecord,
    FilingUpdate,
    ItemState,
    Milestone,
    Submission,
)

_FIXED = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)


def test_portal_shows_only_this_partys_items(client, make_case, make_progress, monkeypatch):
    case = make_case()
    client.app.state.store.save_case(case)
    monkeypatch.setattr(api, "record_activity", lambda store, c, role, now=None: c)
    monkeypatch.setattr(api, "case_progress", lambda c, now=None: make_progress())

    r = client.get("/c/petitok")

    assert r.status_code == 200
    assert "Petitioner — Biographic questionnaire" in r.text
    assert "Marriage certificate" in r.text
    # The beneficiary's item must not leak into the petitioner's portal.
    assert "Beneficiary — Passport bio page" not in r.text
    # Greeting uses the party first name.
    assert "Ada" in r.text


def test_portal_records_activity(client, make_case, make_progress, monkeypatch):
    case = make_case()
    client.app.state.store.save_case(case)
    calls: list = []

    def fake_record(store, c, role, now=None):
        calls.append(role)
        return c

    monkeypatch.setattr(api, "record_activity", fake_record)
    monkeypatch.setattr(api, "case_progress", lambda c, now=None: make_progress())

    r = client.get("/c/petitok")

    assert r.status_code == 200
    assert calls  # record_activity was called on the GET


def test_unknown_token_renders_friendly_404(client):
    r = client.get("/c/not-a-real-token")
    assert r.status_code == 404
    assert "couldn't find that link" in r.text


def test_upload_saves_file_and_calls_submit_document(client, make_case, monkeypatch):
    case = make_case()
    client.app.state.store.save_case(case)
    captured: dict = {}

    monkeypatch.setattr(api, "record_activity", lambda store, c, role, now=None: c)

    def fake_submit_document(store, c, item_key, role, *, filename, stored_path, now=None):
        captured.update(item_key=item_key, filename=filename, stored_path=stored_path, role=role)
        return c.item(item_key)

    monkeypatch.setattr(api, "submit_document", fake_submit_document)

    uploads_dir = client.app.state.uploads_dir
    before = {p.name for p in uploads_dir.iterdir()} if uploads_dir.exists() else set()

    r = client.post(
        "/c/petitok/item/marriage_cert/upload",
        files={"file": ("cert.pdf", b"%PDF-1.4 pretend pdf bytes", "application/pdf")},
        follow_redirects=False,
    )

    assert r.status_code == 303
    assert r.headers["location"] == "/c/petitok"

    after = {p.name for p in uploads_dir.iterdir()}
    new_files = after - before
    assert len(new_files) == 1
    saved = new_files.pop()
    assert saved.endswith(".pdf")          # original extension kept
    assert saved != "cert.pdf"             # stored under a uuid-prefixed safe name

    assert captured["item_key"] == "marriage_cert"
    assert captured["filename"] == "cert.pdf"
    assert captured["stored_path"].endswith(saved)


def test_answers_post_collects_section_fields(client, make_case, monkeypatch):
    case = make_case()
    client.app.state.store.save_case(case)
    captured: dict = {}

    monkeypatch.setattr(api, "record_activity", lambda store, c, role, now=None: c)

    def fake_submit_answers(store, c, item_key, role, answers, now=None):
        captured.update(item_key=item_key, answers=answers)
        return c.item(item_key)

    monkeypatch.setattr(api, "submit_answers", fake_submit_answers)

    r = client.post(
        "/c/petitok/item/pet_bio/answers",
        data={"full_name": "Ada Ramirez", "dob": "1990-05-01"},
        follow_redirects=False,
    )

    assert r.status_code == 303
    assert captured["item_key"] == "pet_bio"
    assert captured["answers"] == {"full_name": "Ada Ramirez", "dob": "1990-05-01"}


def test_upload_unknown_token_404(client):
    r = client.post(
        "/c/bogus/item/marriage_cert/upload",
        files={"file": ("x.pdf", b"data", "application/pdf")},
        follow_redirects=False,
    )
    assert r.status_code == 404


# =========================================================== (B) filing timeline

def test_portal_shows_filing_timeline_and_uscis_link_when_filings(
    client, make_case, make_progress, monkeypatch
):
    case = make_case()
    case.filings.append(
        FilingRecord(
            form_type="I-130", filed_on=date(2026, 5, 1),
            receipt_number="IOE0123456789", status=Milestone.biometrics,
            updates=[
                FilingUpdate(milestone=Milestone.receipt, at=_FIXED),
                FilingUpdate(milestone=Milestone.biometrics, at=_FIXED),
            ],
        )
    )
    client.app.state.store.save_case(case)
    monkeypatch.setattr(api, "record_activity", lambda store, c, role, now=None: c)
    monkeypatch.setattr(api, "case_progress", lambda c, now=None: make_progress())

    r = client.get("/c/petitok")
    assert r.status_code == 200
    assert "Your filing status" in r.text
    assert "I-130" in r.text
    assert "Filed" in r.text          # step timeline milestones
    assert "Biometrics" in r.text
    assert "Interview" in r.text
    assert "IOE0123456789" in r.text  # receipt number
    assert "https://egov.uscis.gov/casestatus/landing.do" in r.text  # self-track link
    assert "keep you posted" in r.text  # warm reassurance


def test_portal_omits_filing_section_when_no_filings(
    client, make_case, make_progress, monkeypatch
):
    case = make_case()  # no filings
    client.app.state.store.save_case(case)
    monkeypatch.setattr(api, "record_activity", lambda store, c, role, now=None: c)
    monkeypatch.setattr(api, "case_progress", lambda c, now=None: make_progress())

    r = client.get("/c/petitok")
    assert r.status_code == 200
    assert "Your filing status" not in r.text


def test_portal_never_renders_internal_flags_or_attorney_review(
    client, make_case, make_progress, monkeypatch
):
    """A red-flagged case must look exactly like a normal in-review case to the
    client: no internal flag text, no attorney-review affordance."""
    case = make_case()
    item = case.item("pet_bio")            # petitioner-owned -> shows in petitok portal
    item.attorney_review = True
    item.state = ItemState.submitted        # normal in-review state
    item.submissions.append(
        Submission(
            submitted_at=_FIXED,
            answers={"full_name": "Ada Ramirez"},
            internal_flags=[
                AutoCheckFinding(
                    code="criminal_history",
                    message="INTERNAL_REDFLAG_SHOULD_NOT_SHOW",
                )
            ],
        )
    )
    client.app.state.store.save_case(case)
    monkeypatch.setattr(api, "record_activity", lambda store, c, role, now=None: c)
    monkeypatch.setattr(api, "case_progress", lambda c, now=None: make_progress())

    r = client.get("/c/petitok")
    assert r.status_code == 200
    # The item is still visible, as an ordinary in-review item.
    assert "Petitioner — Biographic questionnaire" in r.text
    # But none of the attorney-only content leaks into the portal.
    assert "INTERNAL_REDFLAG_SHOULD_NOT_SHOW" not in r.text
    assert "criminal_history" not in r.text
    assert "Attorney review" not in r.text
    assert "attorney_review" not in r.text
    assert "internal_flags" not in r.text
