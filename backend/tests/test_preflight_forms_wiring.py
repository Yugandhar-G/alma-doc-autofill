"""Wiring tests for the visa→forms registry feeding the preflight knowledge
plane: the form-edition adapter and the case-type requirements adapter.

These exercise the adapters against the REAL registry data (no mocks, no
network) and prove the two contracts that matter: null editions are never
defaulted, and every derived source_url stays on an official agency host.
"""
from urllib.parse import urlparse

from app.forms.registry import load_registry
from app.forms.schemas import _ALLOWED_PAGE_HOSTS
from app.packages.preflight.checks import evidence_completeness, form_edition_currency
from app.packages.preflight.knowledge import form_editions
from app.packages.preflight.knowledge.requirements import requirements_for
from app.packages.preflight.packet import PacketDoc, PacketView


# --- form-edition adapter -------------------------------------------------- #


def test_edition_adapter_includes_only_non_null_editions():
    # I-129 carries a verified edition in the registry; DS-160 is null-everywhere
    # ("not verifiable at research time") and must be absent, never defaulted.
    derived = form_editions._derived_registry()
    # Keys are casefolded (lookup must never miss on case); entries keep the
    # registry's official casing in form_id.
    assert "i-129" in derived
    assert derived["i-129"].form_id == "I-129"
    assert derived["i-129"].current_edition == "02/27/26"
    assert "ds-160" not in derived
    assert "eta-9035" not in derived  # another pure-null form


def test_edition_adapter_matches_registry_non_null_forms_exactly():
    registry = load_registry()
    expected_ids = {
        form.form_id.casefold()
        for profile in registry.visas
        for form in profile.forms
        if form.edition_date is not None
    }
    assert set(form_editions._derived_registry().keys()) == expected_ids


def test_every_edition_source_url_is_on_an_official_host():
    for entry in form_editions._derived_registry().values():
        host = urlparse(entry.source_url).hostname
        assert host in _ALLOWED_PAGE_HOSTS, (entry.form_id, entry.source_url)


def test_edition_for_is_none_for_null_and_unknown_forms():
    assert form_editions.edition_for("DS-160") is None  # null edition
    assert form_editions.edition_for("NOT-A-FORM") is None  # unknown form


def test_edition_lookup_is_case_insensitive():
    # Packet plane cases g28 as "g-28"; the registry cases it "G-28". A case
    # mismatch must never silently disable the edition check.
    hit = form_editions.edition_for("g-28")
    assert hit is not None and hit.form_id == "G-28"
    assert form_editions.edition_for("G-28") == hit


def test_form_edition_currency_fires_against_real_registry_data():
    # A synthetic stale-edition packet whose form_id matches the registry's own
    # casing ("G-28", real current edition 09/17/18). No mock: this hits the
    # derived registry and must fire, citing G-28's official form page.
    packet = PacketView(
        case_type="g28_filing",
        docs=(PacketDoc(doc_type="g28", source_hash="z" * 64, data={}, form_id="G-28"),),
        declared_editions={"G-28": "01/01/10"},
    )
    findings = form_edition_currency(packet)
    assert len(findings) == 1
    assert findings[0].check_id == "form_edition_currency"
    assert findings[0].severity == "warning"
    assert findings[0].refs[0].ref == "https://www.uscis.gov/g-28"


def test_form_edition_currency_silent_when_declared_matches_real_edition():
    packet = PacketView(
        case_type="g28_filing",
        docs=(PacketDoc(doc_type="g28", source_hash="z" * 64, data={}, form_id="G-28"),),
        declared_editions={"G-28": "09/17/18"},  # the real current edition
    )
    assert form_edition_currency(packet) == []


# --- case-type requirements adapter ---------------------------------------- #


def test_derived_requirements_exist_for_real_visa_codes():
    h1b = requirements_for("h-1b")
    eb1a = requirements_for("eb-1a")
    assert h1b is not None and eb1a is not None
    assert h1b.case_type == "h-1b"
    # Only primary_petition/supplement/prerequisite forms are required; the
    # optional I-907 and beneficiary DS-160 must be excluded.
    h1b_types = {r.doc_type for r in h1b.required}
    assert "I-129" in h1b_types  # primary_petition
    assert "ETA-9035" in h1b_types  # prerequisite
    assert "I-907" not in h1b_types  # optional → not required
    assert "DS-160" not in h1b_types  # beneficiary → not required
    assert "G-28" not in h1b_types  # attorney_rep → not required


def test_evidence_completeness_flags_missing_docs_for_derived_case_type():
    empty_packet = PacketView(case_type="h-1b", docs=(), declared_editions={})
    findings = evidence_completeness(empty_packet)
    required = requirements_for("h-1b").required
    assert len(findings) == len(required)  # empty packet → every doc missing
    assert all(f.check_id == "evidence_completeness" for f in findings)
    assert all(f.severity == "critical" for f in findings)
    assert all(f.refs == [] for f in findings)  # absence findings carry no refs


def test_evidence_completeness_second_visa_code():
    # A second real visa code proves the mapping is not a one-off.
    empty_packet = PacketView(case_type="eb-1a", docs=(), declared_editions={})
    findings = evidence_completeness(empty_packet)
    assert len(findings) == len(requirements_for("eb-1a").required)
    assert len(findings) >= 1


def test_derived_supporting_docs_respect_required_flag():
    # L-1A has one non-required supporting doc; it must not appear as required.
    registry = load_registry()
    l1a_profile = registry.profile("L-1A")
    optional_names = {
        sd.name for sd in l1a_profile.supporting_documents if not sd.required
    }
    derived_types = {r.doc_type for r in requirements_for("l-1a").required}
    assert optional_names  # guard: the fixture actually has an optional doc
    assert derived_types.isdisjoint(optional_names)


# --- hand-seeded g28_filing unchanged -------------------------------------- #


def test_hand_seeded_g28_filing_unchanged():
    reqs = requirements_for("g28_filing")
    assert reqs is not None
    assert reqs.case_type == "g28_filing"
    assert [r.doc_type for r in reqs.required] == ["passport", "g28"]
    assert all(r.condition is None for r in reqs.required)


def test_unknown_case_type_yields_no_requirements():
    assert requirements_for("definitely-not-a-case") is None
