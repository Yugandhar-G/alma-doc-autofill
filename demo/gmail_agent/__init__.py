"""Workstream A extension — the always-on Gmail agent.

Gmail watch() → Pub/Sub topic → streaming-pull consumer (no public URL, no
webhook, no polling of Gmail) → a REAL bounded agent tool-loop (the yunaki
kernel deep-agent engine on Gemini) that investigates then decides → DraftAction
(pending) + email.received / draft.created via core.events. A separate Slack picks
up draft.created for approval and, on approve, executes the send through
core.sendgate using the callable exported by `gmail_agent.sender`.

Builds only on the frozen /core contracts; never edits them. Real sends happen
only when LIVE_MODE=true (core.sendgate owns that decision — this package never
checks it). See CLAUDE_WORKPLAN.md §1.4 / §2 / §6 (Jul 22 scope change).
"""
