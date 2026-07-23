"""Staff dashboard + case-detail route tests. Domain is monkeypatched."""
from __future__ import annotations

from datetime import date

from intake_workflow.domain import api, eligibility, filings, packets
from intake_workflow.schemas import (
    FilingRecord,
    FilingUpdate,
    Milestone,
    OutreachEvent,
    OutreachStatus,
    PartyRole,
    Rung,
)


def test_dashboard_renders_with_case_titles(client, make_case, make_progress, monkeypatch):
    case = make_case()
    client.app.state.store.save_case(case)
    monkeypatch.setattr(api, "case_progress", lambda c, now=None: make_progress())
    monkeypatch.setattr(api, "i751_radar", lambda store, now=None: [])

    r = client.get("/staff")

    assert r.status_code == 200
    assert "Ramirez–Osei" in r.text
    assert "Case dashboard" in r.text


def test_dashboard_empty_state(client, monkeypatch):
    monkeypatch.setattr(api, "i751_radar", lambda store, now=None: [])
    r = client.get("/staff")
    assert r.status_code == 200
    assert "No cases yet" in r.text


def test_create_case_calls_domain_with_kwargs_and_redirects(client, make_case, monkeypatch):
    captured: dict = {}

    def fake_create_case(store, **kwargs):
        captured.update(kwargs)
        return make_case(case_id="newcase")

    monkeypatch.setattr(api, "create_case", fake_create_case)

    r = client.post(
        "/staff/case/new",
        data={
            "title": "Nguyen–Park",
            "petitioner_name": "Lan Nguyen",
            "petitioner_email": "lan@example.com",
            "beneficiary_name": "Jun Park",
            "beneficiary_email": "jun@example.com",
            "consult_notes": "referred by prior client",
            "i485_approved_on": "",
        },
        follow_redirects=False,
    )

    assert r.status_code == 303
    assert r.headers["location"] == "/staff/case/newcase"
    assert captured["title"] == "Nguyen–Park"
    assert captured["petitioner_name"] == "Lan Nguyen"
    assert captured["beneficiary_email"] == "jun@example.com"
    assert captured["consult_notes"] == "referred by prior client"
    assert captured["i485_approved_on"] is None


def test_create_case_parses_i485_date(client, make_case, monkeypatch):
    from datetime import date

    captured: dict = {}

    def fake_create_case(store, **kwargs):
        captured.update(kwargs)
        return make_case(case_id="withdate")

    monkeypatch.setattr(api, "create_case", fake_create_case)

    r = client.post(
        "/staff/case/new",
        data={
            "title": "Has date",
            "petitioner_name": "A", "petitioner_email": "a@example.com",
            "beneficiary_name": "B", "beneficiary_email": "b@example.com",
            "i485_approved_on": "2024-03-15",
        },
        follow_redirects=False,
    )

    assert r.status_code == 303
    assert captured["i485_approved_on"] == date(2024, 3, 15)


def test_case_detail_renders_items_and_drafted_outreach(client, make_case, make_progress, monkeypatch, now):
    case = make_case()
    case.outreach.append(
        OutreachEvent(
            party_role=PartyRole.petitioner, rung=Rung.nudge,
            subject="Quick nudge on your documents",
            body="Hi Ada — just three items left.",
            status=OutreachStatus.drafted, created_at=now,
        )
    )
    client.app.state.store.save_case(case)
    monkeypatch.setattr(api, "case_progress", lambda c, now=None: make_progress())

    r = client.get(f"/staff/case/{case.id}")

    assert r.status_code == 200
    assert "Marriage certificate" in r.text
    assert "Beneficiary — Passport bio page" in r.text
    assert "Quick nudge on your documents" in r.text
    assert "Hi Ada — just three items left." in r.text
    # Magic links are shown for both parties.
    assert "/c/petitok" in r.text
    assert "/c/bentok" in r.text


def test_case_detail_unknown_case_404(client, monkeypatch):
    monkeypatch.setattr(api, "case_progress", lambda c, now=None: None)
    r = client.get("/staff/case/does-not-exist")
    assert r.status_code == 404


def test_scheduler_tick_redirects_with_draft_count(client, monkeypatch):
    # provider=None mirrors the real run_scheduler signature; the native default
    # provider (SendgateProvider) makes the staff route pass provider= through.
    monkeypatch.setattr(api, "run_scheduler",
                        lambda store, now=None, provider=None: ["a", "b"])
    r = client.post("/staff/tick", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/staff?drafted=2"


def test_review_accept_calls_domain(client, make_case, monkeypatch):
    case = make_case()
    client.app.state.store.save_case(case)
    captured: dict = {}

    def fake_review(store, c, item_key, *, action, reviewer, reason=None, now=None):
        captured.update(item_key=item_key, action=action, reviewer=reviewer, reason=reason)
        return c.item(item_key)

    monkeypatch.setattr(api, "review_item", fake_review)

    r = client.post(
        f"/staff/case/{case.id}/item/marriage_cert/review",
        data={"action": "accepted"},
        follow_redirects=False,
    )

    assert r.status_code == 303
    assert captured["item_key"] == "marriage_cert"
    assert captured["action"] == "accepted"
    assert captured["reviewer"] == "Isaiah"


def test_approve_outreach_calls_domain(client, make_case, monkeypatch, now):
    case = make_case()
    ev = OutreachEvent(
        party_role=PartyRole.petitioner, rung=Rung.nudge,
        subject="s", body="b", status=OutreachStatus.drafted, created_at=now,
    )
    case.outreach.append(ev)
    client.app.state.store.save_case(case)
    captured: dict = {}

    def fake_approve(store, c, outreach_id, approver, now=None, provider=None):
        captured.update(outreach_id=outreach_id, approver=approver)
        return ev

    monkeypatch.setattr(api, "approve_outreach", fake_approve)

    r = client.post(
        f"/staff/case/{case.id}/outreach/{ev.id}/approve",
        follow_redirects=False,
    )

    assert r.status_code == 303
    assert captured["outreach_id"] == ev.id
    assert captured["approver"] == "Isaiah"


# =========================================================== (A) filings panel

def test_filings_panel_renders_records_and_forms(client, make_case, make_progress, monkeypatch, now):
    case = make_case()
    case.filings.append(
        FilingRecord(
            form_type="I-130", filed_on=date(2026, 5, 1),
            receipt_number="IOE0123456789", status=Milestone.receipt,
            updates=[FilingUpdate(milestone=Milestone.receipt, at=now, note="Receipt notice arrived")],
        )
    )
    client.app.state.store.save_case(case)
    monkeypatch.setattr(api, "case_progress", lambda c, now=None: make_progress())

    r = client.get(f"/staff/case/{case.id}")

    assert r.status_code == 200
    assert "I-130" in r.text
    assert "IOE0123456789" in r.text          # receipt (monospace)
    assert "Receipt notice arrived" in r.text  # update history
    fid = case.filings[0].id
    assert f"/staff/case/{case.id}/filings" in r.text                    # add-filing form
    assert f"/staff/case/{case.id}/filings/{fid}/receipt" in r.text      # set-receipt form
    assert f"/staff/case/{case.id}/filings/{fid}/status" in r.text       # status form
    assert f"/staff/case/{case.id}/packet/I-130" in r.text              # packet link


def test_record_filing_calls_domain_with_parsed_date_and_redirects(client, make_case, monkeypatch):
    case = make_case()
    client.app.state.store.save_case(case)
    captured: dict = {}

    def fake_record(store, c, *, form_type, filed_on, receipt_number=None, now=None):
        captured.update(form_type=form_type, filed_on=filed_on, receipt_number=receipt_number)
        return FilingRecord(form_type=form_type, filed_on=filed_on, receipt_number=receipt_number)

    monkeypatch.setattr(filings, "record_filing", fake_record)

    r = client.post(
        f"/staff/case/{case.id}/filings",
        data={"form_type": "i-485", "filed_on": "2026-06-15", "receipt_number": ""},
        follow_redirects=False,
    )

    assert r.status_code == 303
    assert r.headers["location"] == f"/staff/case/{case.id}"
    assert captured["form_type"] == "i-485"
    assert captured["filed_on"] == date(2026, 6, 15)
    assert captured["receipt_number"] is None


def test_record_filing_bad_receipt_flashes_not_500(client, make_case, make_progress, monkeypatch):
    case = make_case()
    client.app.state.store.save_case(case)
    monkeypatch.setattr(api, "case_progress", lambda c, now=None: make_progress())

    def boom(store, c, *, form_type, filed_on, receipt_number=None, now=None):
        raise ValueError("That receipt number is not valid (need 3 letters + 10 digits).")

    monkeypatch.setattr(filings, "record_filing", boom)

    r = client.post(
        f"/staff/case/{case.id}/filings",
        data={"form_type": "I-130", "filed_on": "2026-06-15", "receipt_number": "nope"},
        follow_redirects=False,
    )
    assert r.status_code == 303  # redirected, not a 500
    location = r.headers["location"]
    assert location.startswith(f"/staff/case/{case.id}?")

    r2 = client.get(location)
    assert r2.status_code == 200
    assert "receipt number is not valid" in r2.text  # readable flash


def test_set_receipt_calls_domain(client, make_case, monkeypatch):
    case = make_case()
    fr = FilingRecord(form_type="I-130", filed_on=date(2026, 5, 1))
    case.filings.append(fr)
    client.app.state.store.save_case(case)
    captured: dict = {}

    def fake_set(store, c, filing_id, receipt_number, now=None):
        captured.update(filing_id=filing_id, receipt_number=receipt_number)
        return fr

    monkeypatch.setattr(filings, "set_receipt_number", fake_set)

    r = client.post(
        f"/staff/case/{case.id}/filings/{fr.id}/receipt",
        data={"receipt_number": "ioe0123456789"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert captured["filing_id"] == fr.id
    assert captured["receipt_number"] == "ioe0123456789"


def test_status_update_with_checkbox_calls_update_and_draft(client, make_case, monkeypatch, now):
    case = make_case()
    fr = FilingRecord(form_type="I-130", filed_on=date(2026, 5, 1))
    case.filings.append(fr)
    client.app.state.store.save_case(case)
    calls: list = []

    def fake_update(store, c, filing_id, *, milestone, note="", now=None):
        calls.append(("update", filing_id, milestone, note))
        return fr

    def fake_draft(store, c, filing_id, now=None):
        calls.append(("draft", filing_id))
        # The route ignores the return value; the real one appends to
        # case.outreach itself. Returning None keeps the fake honest.
        return None

    monkeypatch.setattr(filings, "update_filing_status", fake_update)
    monkeypatch.setattr(filings, "draft_status_update", fake_draft)

    r = client.post(
        f"/staff/case/{case.id}/filings/{fr.id}/status",
        data={"milestone": "biometrics", "note": "Bio appt scheduled", "notify": "on"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert [c[0] for c in calls] == ["update", "draft"]
    assert calls[0][2] == Milestone.biometrics
    assert calls[0][3] == "Bio appt scheduled"


def test_status_update_without_checkbox_calls_only_update(client, make_case, monkeypatch):
    case = make_case()
    fr = FilingRecord(form_type="I-130", filed_on=date(2026, 5, 1))
    case.filings.append(fr)
    client.app.state.store.save_case(case)
    calls: list = []

    monkeypatch.setattr(
        filings, "update_filing_status",
        lambda store, c, filing_id, *, milestone, note="", now=None: (calls.append("update"), fr)[1],
    )
    monkeypatch.setattr(
        filings, "draft_status_update",
        lambda store, c, filing_id, now=None: calls.append("draft"),
    )

    r = client.post(
        f"/staff/case/{case.id}/filings/{fr.id}/status",
        data={"milestone": "interview", "note": ""},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert calls == ["update"]  # draft NOT called


def test_status_update_rung_label_renders_nicely(client, make_case, make_progress, monkeypatch, now):
    case = make_case()
    case.outreach.append(
        OutreachEvent(
            party_role=PartyRole.beneficiary, rung=Rung.status_update,
            subject="Update on your I-130", body="Good news about your case.",
            status=OutreachStatus.drafted, created_at=now,
        )
    )
    client.app.state.store.save_case(case)
    monkeypatch.setattr(api, "case_progress", lambda c, now=None: make_progress())

    r = client.get(f"/staff/case/{case.id}")
    assert r.status_code == 200
    assert "Status update" in r.text          # rendered nicely
    assert "status_update" not in r.text      # raw enum value never leaks


# =========================================================== (C) packet view

def test_packet_view_renders_sections_and_missing(client, make_case, monkeypatch):
    case = make_case()
    client.app.state.store.save_case(case)
    packet = {
        "form_type": "I-130",
        "case_title": case.title,
        "sections": [
            {"title": "Part 1 — Petitioner", "fields": [
                {"label": "Full legal name", "value": "Ada Ramirez", "source": "pet_bio.full_name"},
                {"label": "A-number", "value": "", "source": "pet_bio.a_number"},
            ]},
        ],
        "missing": ["A-number"],
    }
    monkeypatch.setattr(packets, "build_packet", lambda c, ft: packet)

    r = client.get(f"/staff/case/{case.id}/packet/I-130")
    assert r.status_code == 200
    assert "Part 1 — Petitioner" in r.text
    assert "Ada Ramirez" in r.text
    assert "pet_bio.full_name" in r.text  # source shown for auditability
    assert "Missing information" in r.text
    assert "A-number" in r.text


def test_packet_unknown_form_404(client, make_case, monkeypatch):
    case = make_case()
    client.app.state.store.save_case(case)

    def boom(c, ft):
        raise ValueError("Unknown form_type 'XYZ'; expected one of I-130, I-485")

    monkeypatch.setattr(packets, "build_packet", boom)

    r = client.get(f"/staff/case/{case.id}/packet/XYZ")
    assert r.status_code == 404


# =========================================================== (D) attorney queue

def test_attorney_queue_renders_entries(client, monkeypatch, now):
    entries = [{
        "case_id": "case1",
        "case_title": "Ramirez–Osei · Marriage AOS",
        "item_key": "ben_eligibility",
        "item_label": "Beneficiary — Eligibility questionnaire",
        "flags": ["Criminal history disclosed", "Prior denial disclosed"],
        "since": now,
    }]
    monkeypatch.setattr(eligibility, "attorney_queue", lambda store: entries)

    r = client.get("/staff/attorney-queue")
    assert r.status_code == 200
    assert "Ramirez–Osei" in r.text
    assert "Beneficiary — Eligibility questionnaire" in r.text
    assert "Criminal history disclosed" in r.text
    assert "Prior denial disclosed" in r.text
    assert "/staff/case/case1/item/ben_eligibility/clear-review" in r.text


def test_clear_review_calls_domain_and_redirects(client, make_case, monkeypatch):
    case = make_case()
    client.app.state.store.save_case(case)
    captured: dict = {}

    def fake_clear(store, c, item_key, *, reviewer, note="", now=None):
        captured.update(item_key=item_key, reviewer=reviewer, note=note)
        return c.item("pet_bio")

    monkeypatch.setattr(eligibility, "clear_attorney_review", fake_clear)

    r = client.post(
        f"/staff/case/{case.id}/item/pet_bio/clear-review",
        data={"reviewer": "Allison", "note": "Reviewed — cleared to proceed"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert r.headers["location"] == "/staff/attorney-queue"
    assert captured["item_key"] == "pet_bio"
    assert captured["reviewer"] == "Allison"
    assert captured["note"] == "Reviewed — cleared to proceed"


def test_attorney_review_chip_on_staff_item(client, make_case, make_progress, monkeypatch):
    case = make_case()
    case.item("ben_passport").attorney_review = True
    client.app.state.store.save_case(case)
    monkeypatch.setattr(api, "case_progress", lambda c, now=None: make_progress())

    r = client.get(f"/staff/case/{case.id}")
    assert r.status_code == 200
    assert "chip--attorney" in r.text
    assert "Attorney review" in r.text


def test_dashboard_attorney_badge_shown_when_queue_nonempty(client, monkeypatch):
    monkeypatch.setattr(api, "i751_radar", lambda store, now=None: [])
    monkeypatch.setattr(eligibility, "attorney_queue", lambda store: [{"a": 1}, {"b": 2}])

    r = client.get("/staff")
    assert r.status_code == 200
    assert "/staff/attorney-queue" in r.text
    assert ">2<" in r.text  # count badge


def test_dashboard_attorney_badge_hidden_when_queue_empty(client, monkeypatch):
    monkeypatch.setattr(api, "i751_radar", lambda store, now=None: [])
    monkeypatch.setattr(eligibility, "attorney_queue", lambda store: [])

    r = client.get("/staff")
    assert r.status_code == 200
    assert "/staff/attorney-queue" not in r.text
