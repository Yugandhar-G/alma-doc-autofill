"""SendgateProvider — route the intake app's sends through our gated draft pipeline.

This provider NEVER sends an email. When the intake app "sends" a follow-up
(approve queue or scheduler auto-send), this provider instead:

  1. resolves the /core case behind the recipient email,
  2. creates a PENDING DraftAction in our shared DB (``core.drafts.create_draft``),
  3. emits a ``draft.created`` event on our bus,
  4. returns a synthetic message id ``sendgate-<draft_id>``.

Send semantics change (documented in docs/integration-bridge.md): in the intake
UI, "sent" now means "handed to the firm's gated send pipeline". Actual delivery
only happens later, after a human approves the draft in Slack and it goes out
through the LIVE_MODE send gate from the firm mailbox. The integration does not
deliver mail.
"""
from __future__ import annotations

from intake_workflow.email.outbox import EmailSendError


class SendgateProvider:
    """Implements the intake app's EmailProvider protocol; hands sends to our send gate."""

    name = "sendgate"

    def send(self, *, to_email: str, subject: str, body: str) -> str:
        """Resolve the /core case for ``to_email`` and queue a pending draft.

        Raises EmailSendError (fail loud, never guess) when the recipient cannot
        be resolved to exactly one /core case — the intake flow then leaves the
        follow-up ``drafted`` for a human to sort out.
        """
        from core.drafts import create_draft
        from core.events import emit
        from core.models import DraftAction, DraftGrounding, DraftTo, Event

        from intake_workflow.integration import config

        conn = config.shared_conn()
        try:
            case_id, client_name = self._resolve_case(conn, to_email)

            draft = create_draft(
                conn,
                DraftAction(
                    case_id=case_id,
                    kind="client_email",
                    trigger="manual",
                    to=DraftTo(name=client_name, channel_address=to_email),
                    subject=subject,
                    body=body,
                    grounding=DraftGrounding(case_state={"origin": "yew-bridge"}),
                ),
            )
            emit(
                conn,
                Event(
                    type="draft.created",
                    case_id=case_id,
                    actor="agent:validation",
                    payload={
                        "draft_id": draft.id,
                        "kind": "client_email",
                        "channel": "client_email",
                    },
                ),
            )
            return f"sendgate-{draft.id}"
        finally:
            conn.close()

    @staticmethod
    def _resolve_case(conn, to_email: str) -> tuple[str, str]:
        """Return (core_case_id, client display name) for a recipient email.

        Requires a UNIQUE client row by email and a UNIQUE party->case mapping.
        Anything else raises EmailSendError — never guess which case a send
        belongs to.
        """
        clients = conn.execute(
            "SELECT id, first_name, last_name FROM client WHERE email = ?",
            (to_email,),
        ).fetchall()
        if len(clients) != 1:
            raise EmailSendError(
                f"sendgate: found {len(clients)} /core clients for {to_email!r}; "
                "need exactly one to resolve the case."
            )
        client = clients[0]

        parties = conn.execute(
            "SELECT case_id FROM party WHERE client_id = ?",
            (client["id"],),
        ).fetchall()
        if len(parties) != 1:
            raise EmailSendError(
                f"sendgate: client {client['id']!r} maps to {len(parties)} /core "
                "cases; need exactly one to resolve the case."
            )

        name = f"{client['first_name']} {client['last_name']}".strip()
        return parties[0]["case_id"], name
