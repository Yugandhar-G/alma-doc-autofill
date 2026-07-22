# Gmail Agent — cold setup (GCP + OAuth + Pub/Sub)

The always-on email agent: Gmail `watch()` → Pub/Sub topic → streaming-pull
consumer (no public URL) → a real bounded agent tool-loop → a **pending**
`DraftAction` surfaced in Slack for approval → on approve, a real send via the
Gmail API, gated by `LIVE_MODE`.

> **DEMO MAILBOX ONLY.** Never authorize the firm's real account. Create a
> throwaway Google account for the demo and use only that.
>
> **`LIVE_MODE` stays `false`** until the Friday demo decision. With
> `LIVE_MODE=false`, `core.sendgate` renders every approved reply to the
> `outbox` table and NEVER calls the Gmail send — nothing leaves the mailbox.

---

## 0. Prerequisites (the email brain runs on the yunaki kernel)

The email agent is a real bounded tool-loop built on the **yunaki kernel
deep-agent engine** (deepagents + `langchain-google-genai`, model = Gemini). That
engine lives in the sibling `backend/` package and **requires Python ≥ 3.11**.

```bash
# From demo/ — install the backend engine editable (Python >=3.11):
pip install -e ../backend
```

The kernel model is Gemini via `make_agent_model`; set `GEMINI_API_KEY` in `.env`
(https://aistudio.google.com/apikey). This is a locked stack decision — the email
agent never calls Anthropic.

> On a Python 3.10 interpreter the engine cannot be installed (`deepagents` has
> no 3.10 distribution). The rest of the package still imports and its infra
> tests still run via `pip install -e ../backend --no-deps --ignore-requires-python`
> (puts the kernel registry on the path; the loop itself needs 3.11+).

---

## 1. GCP project + APIs

1. Create or select a GCP project. Note its **project id** (`<gcp>` below).
2. Enable **Gmail API** and **Cloud Pub/Sub API**
   (APIs & Services → Library).

## 2. OAuth consent + client (for the mailbox)

3. APIs & Services → **OAuth consent screen** → **External**. Add the demo
   mailbox as a **Test user** (consent screen may stay in "Testing").
4. APIs & Services → **Credentials** → **Create Credentials** → **OAuth client
   ID** → **Desktop app**. Download the JSON to
   `.secrets/gmail_credentials.json` (this path is gitignored).

Scopes requested by the app (least privilege — verified against the Gmail API
reference): `gmail.readonly` (watch, history.list, messages.get with body) +
`gmail.send` (messages.send). `gmail.modify` is intentionally **not** requested —
the agent never mutates messages.

## 3. Pub/Sub topic + subscription

5. Pub/Sub → **Create topic**, e.g. `gmail-inbound`. Full name:
   `projects/<gcp>/topics/gmail-inbound`.
6. On that topic → **Add principal**: grant
   `gmail-api-push@system.gserviceaccount.com` the role **Pub/Sub Publisher**
   (this is what lets Gmail publish notifications to your topic).
7. Create a **PULL subscription** on the topic, e.g. `gmail-inbound-pull`. Full
   name: `projects/<gcp>/subscriptions/gmail-inbound-pull`. (Pull — the consumer
   streams; there is no push endpoint / public URL.)

## 4. Service account for the subscriber (ADC)

8. IAM & Admin → **Service Accounts** → create one, e.g. `gmail-consumer`.
9. Grant it **Pub/Sub Subscriber**.
10. Create a **JSON key** for it and save it locally (e.g.
    `.secrets/pubsub_sa.json`). This is `GOOGLE_APPLICATION_CREDENTIALS` (the
    streaming-pull client authenticates as this service account).

## 5. Fill `.env`

```
GMAIL_ADDRESS=the-demo-mailbox@gmail.com
GMAIL_CREDENTIALS_PATH=.secrets/gmail_credentials.json
GMAIL_TOKEN_PATH=.secrets/gmail_token.json
GMAIL_TOPIC=projects/<gcp>/topics/gmail-inbound
GMAIL_PUBSUB_SUBSCRIPTION=projects/<gcp>/subscriptions/gmail-inbound-pull
GOOGLE_APPLICATION_CREDENTIALS=.secrets/pubsub_sa.json
GEMINI_API_KEY=...
LIVE_MODE=false
```

## 6. Authorize, watch, run

```bash
python -m gmail_agent.auth     # one-time browser consent → writes GMAIL_TOKEN_PATH
python -m gmail_agent.watch    # registers users.watch on INBOX → topic; prints
                               # historyId (stored as the baseline high-water) + expiration
python -m gmail_agent.main     # the always-on streaming-pull consumer
```

The watch expires in ~7 days; the running consumer re-registers automatically
when within 24h of expiry.

---

## How it flows (once running)

1. A new inbound email → Gmail publishes `{emailAddress, historyId}` to the topic.
2. The consumer's streaming pull receives it, calls `users.history.list` from the
   stored high-water mark, and fetches each newly-added INBOX message.
3. Messages sent **by the agent's own address are skipped** (loop prevention);
   bodyless messages are skipped; each Gmail message id is deduped.
4. For each real inbound message, the **email agent** (bounded tool-loop) looks
   up whether the sender is a client, pulls the case snapshot + missing checklist
   items when relevant, and decides: draft a reply, or no action. A deterministic
   post-audit strips any reply that names a checklist item no tool surfaced.
5. `email.received` is emitted (masked payload — a hash of the sender, not the
   address); if a reply was drafted, a **pending** `DraftAction` is created and
   `draft.created` emitted. The Slack process surfaces it for approval.
6. On approve, the Slack process calls `core.sendgate.execute_draft` with the
   callable from `gmail_agent.sender.build_gmail_sender()`. `LIVE_MODE=false` →
   rendered to `outbox`, nothing sent. `LIVE_MODE=true` → real threaded reply.

---

## Troubleshooting

| Symptom | Likely cause / fix |
|---|---|
| No notifications arrive | Watch expired (re-run `python -m gmail_agent.watch`) **or** the topic is missing the `gmail-api-push@system.gserviceaccount.com` **Publisher** grant (step 6). |
| Auth fails with **403 / access_denied** | The demo mailbox is not a **Test user** on the OAuth consent screen (step 3). |
| Sends fail (`insufficient permission`) | The token lacks `gmail.send` — delete `GMAIL_TOKEN_PATH` and re-run `python -m gmail_agent.auth` to re-consent. |
| `TokenMissing` on startup | No OAuth token yet — run `python -m gmail_agent.auth`. |
| Consumer starts then errors on `deepagents` | The kernel engine is not installed / wrong Python — install `../backend` on Python ≥ 3.11 (step 0). |
| Streaming pull auth error | `GOOGLE_APPLICATION_CREDENTIALS` unset or the service account lacks **Pub/Sub Subscriber** (step 4). |
| Reply lands as a new email, not in-thread | The original `Message-ID` header or `threadId` was missing from grounding — check the inbound message had a `Message-ID` header. |
