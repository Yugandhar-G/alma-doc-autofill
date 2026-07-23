"""Follow-up email/note body generation (private helper for app.domain.api).

Bodies are generated from *live* checklist state, so they are always specific:
returned items (with the paralegal's verbatim reason) first, then still-pending
required items, then any thin bona-fide evidence categories relevant to the
party. Client rungs are warm, professional, and signed by Allison; the
``escalate`` rung is an internal note to Allison with a drafted personal message
she can send herself.
"""
from __future__ import annotations

from datetime import datetime

from intake_workflow.case_templates import get_template
from intake_workflow.schemas import Case, ItemKind, ItemState, Party, PartyRole, Rung

BASE_URL = "http://localhost:8000"
SIGNATURE = "Allison — Yew Legal"


def portal_link(party: Party) -> str:
    return f"{BASE_URL}/c/{party.token}"


def _first_name(full_name: str) -> str:
    parts = full_name.strip().split()
    return parts[0] if parts else full_name


def _open_items(case: Case, role: PartyRole):
    """Returned items (any) and still-pending *required* items for this party."""
    returned = [
        i for i in case.items
        if i.assignee == role and i.state == ItemState.returned
    ]
    pending = [
        i for i in case.items
        if i.assignee == role and i.state == ItemState.pending and i.required
    ]
    return returned, pending


def _thin_categories(case: Case, role: PartyRole) -> list[str]:
    """Bona-fide categories not yet meeting min_items, limited to categories the
    party actually has assigned document items in."""
    template = get_template(case.case_type)
    thin: list[str] = []
    for rule in template.categories:
        accepted = sum(
            1 for i in case.items
            if i.category == rule.category
            and i.kind == ItemKind.document
            and i.state == ItemState.accepted
        )
        party_owns = any(
            i.category == rule.category and i.assignee == role for i in case.items
        )
        if accepted < rule.min_items and party_owns:
            thin.append(rule.label)
    return thin


def _render_outstanding(returned, pending) -> str:
    lines: list[str] = []
    if returned:
        lines.append("Items we sent back for a quick fix:")
        for item in returned:
            reason = item.latest_return_reason or "Please review and resubmit."
            lines.append(f"  • {item.label} — {reason}")
    if pending:
        if lines:
            lines.append("")
        lines.append("Still to send:")
        for item in pending:
            lines.append(f"  • {item.label}")
    return "\n".join(lines)


def _thin_note(thin: list[str]) -> str:
    if not thin:
        return ""
    joined = ", ".join(thin)
    return (
        "A couple of your marriage-evidence categories are still a little thin: "
        f"{joined}. A few more items in these areas will strengthen the case."
    )


def _days_inactive(case: Case, party: Party, now: datetime) -> int:
    base = party.last_activity_at or case.created_at
    return (now - base).days


def build(case: Case, role: PartyRole, rung: Rung, now: datetime) -> tuple[str, str]:
    """Return ``(subject, body)`` for a follow-up at ``rung`` for the party."""
    party = case.party(role)
    if rung == Rung.escalate:
        return _build_escalate(case, party, now)
    return _build_client(case, party, rung, now)


def _build_client(case: Case, party: Party, rung: Rung, now: datetime) -> tuple[str, str]:
    first = _first_name(party.full_name)
    returned, pending = _open_items(case, party.role)
    thin = _thin_categories(case, party.role)
    link = portal_link(party)
    outstanding = _render_outstanding(returned, pending)
    thin_note = _thin_note(thin)

    other = _other_party(case, party.role)
    other_done = other is not None and not any(
        i.assignee == other.role and i.required and i.open for i in case.items
    )

    if rung == Rung.nudge:
        subject = "A quick check-in on your Yew Legal intake"
        opening = (
            f"Hi {first},\n\n"
            "Just a friendly check-in on your immigration case documents — "
            "you're making good progress. Here's what's still outstanding on "
            "your side:"
        )
        offer = "No rush today, but the sooner we have these the sooner we can move your case forward."
    elif rung == Rung.specifics:
        subject = "The specific items we still need — Yew Legal"
        opening = (
            f"Hi {first},\n\n"
            "Following up so you know exactly what's left. These are the specific "
            "items we still need from you to keep your case on track:"
        )
        offer = (
            "If anything here is unclear or hard to get hold of, just reply to this "
            "email and we'll help you work through it."
        )
    else:  # call_offer
        subject = "Would a quick call help? — Yew Legal"
        opening = (
            f"Hi {first},\n\n"
            "I wanted to reach out personally. We still have a few items open on "
            "your case, and I'd be glad to hop on a short call to walk through them "
            "with you if that's easier than email:"
        )
        offer = "Just let me know a couple of times that work and I'll set up a call."
        if other_done:
            offer += (
                " Everything from your spouse is already in — yours are the only "
                "items we're waiting on now."
            )

    body_parts = [opening, "", outstanding]
    if thin_note:
        body_parts += ["", thin_note]
    body_parts += [
        "",
        f"You can pick up right where you left off here:\n{link}",
        "",
        offer,
        "",
        "Warmly,",
        SIGNATURE,
    ]
    return subject, "\n".join(body_parts)


def _build_escalate(case: Case, party: Party, now: datetime) -> tuple[str, str]:
    first = _first_name(party.full_name)
    returned, pending = _open_items(case, party.role)
    days = _days_inactive(case, party, now)
    link = portal_link(party)
    outstanding = _render_outstanding(returned, pending) or "  • (see checklist)"

    subject = f"Internal: {party.full_name} intake has stalled"
    body = (
        f"Hi Allison,\n\n"
        f"{party.full_name} ({party.role.value}) on the \"{case.title}\" case has "
        f"not been active in the client portal for {days} days and still has "
        f"outstanding required items. The automated nudges have run their course, "
        f"so this one is worth a personal touch from you.\n\n"
        f"Outstanding items:\n{outstanding}\n\n"
        f"Suggested note you can send from your own inbox:\n"
        f"---\n"
        f"Hi {first},\n\n"
        f"I know life gets busy — I just wanted to reach out myself to make sure "
        f"nothing is stuck on our end. We're still holding a few items to move your "
        f"case forward, and I'm happy to help however is easiest for you. You can "
        f"upload whenever you have a moment here:\n{link}\n\n"
        f"Warmly,\n{SIGNATURE}\n"
        f"---\n"
    )
    return subject, body


def _other_party(case: Case, role: PartyRole) -> Party | None:
    for party in case.parties:
        if party.role != role:
            return party
    return None
