# yunaki Slack Gateway Setup

Provision the `yunaki` Slack bot. It runs in **Socket Mode** (outbound WebSocket only, no
public HTTP endpoint), so it works from a laptop or the desktop app with no ingress or tunnel.

> **⚠️ Demo workspace only.** Install this app **exclusively** into a dedicated demo
> workspace named **`yunaki-demo`** (create one now if it does not exist). **Never** install it
> into the law firm's real workspace this week. **Zero real client data** goes into the demo
> workspace — synthetic cases only.

## 1. Create the app from the manifest

1. Go to https://api.slack.com/apps → **Create New App** → **From a manifest**.
2. Pick the **`yunaki-demo`** workspace (not the firm's real workspace).
3. Paste the contents of [`slack-app-manifest.yaml`](./slack-app-manifest.yaml), review the
   scopes/events/slash command, and **Create**.

## 2. Generate the app-level token (Socket Mode)

1. **Settings → Basic Information → App-Level Tokens → Generate Token and Scopes**.
2. Name it `yunaki-socket`, add the **`connections:write`** scope, **Generate**.
3. Copy the `xapp-…` value. This is `SLACK_APP_TOKEN`. It is shown once — grab it now.

Confirm **Settings → Socket Mode** is toggled **On** (the manifest sets this; verify it stuck).

## 3. Install to the workspace and get the bot token

1. **Settings → Install App → Install to Workspace**, approve the scopes.
2. Copy the **Bot User OAuth Token** (`xoxb-…`). This is `SLACK_BOT_TOKEN`.

## 4. Collect member IDs for the allowlist

Only allowlisted users can assign tasks; an empty allowlist means the bot refuses everyone.

- In Slack, click a person → **View full profile → ⋮ (More) → Copy member ID**.
- Member IDs look like `U012ABCDEF`. Collect one per teammate who may assign work.

## 5. Find the demo #cases channel ID

The bot watches one channel for case handoffs. In `yunaki-demo`, create a channel named
`#cases`, then copy its ID: open the channel → click its name in the header →
**View channel details** → scroll to the bottom of the **About** tab → **Channel ID** (looks
like `C012ABCDEF`). This is `SLACK_CHANNEL_CASES`.

## 6. Configure `backend/.env`

Add the four variables. **Never commit `.env`** (it is gitignored; keep it that way).

```dotenv
SLACK_BOT_TOKEN=xoxb-your-bot-token
SLACK_APP_TOKEN=xapp-your-app-token
SLACK_ALLOWED_USER_IDS=U012ABCDEF,U034GHIJKL
SLACK_CHANNEL_CASES=C012ABCDEF
```

`SLACK_ALLOWED_USER_IDS` is comma-separated, no spaces required. Leave it empty only if you
intend the bot to ignore everyone.

## 7. Invite the bot and smoke-test

1. In `#cases` (and any test channel), run `/invite @yunaki`. The bot only sees channels it
   has been invited to.
2. Start the backend so the Socket Mode client connects.
3. Post `@yunaki draft a summary of the Q3 filing`. Expected: a reaction on your message and a
   threaded reply carrying the proposed action with **[Approve] [Edit] [Reject]** buttons.
   Clicking **Edit** opens a modal to adjust the task before it runs.
4. Try `/yunaki status <case>` to confirm the slash command responds.

## Privacy note

Message text you send to `@yunaki` transits Slack, a third-party product channel — treat it as
you would any Slack message. The backend keeps **server logs PII-masked** (documents referenced
by content hash, member IDs and counts only), so nothing sensitive is written to local logs.

## Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| Bot never responds to a mention | Not invited to the channel | `/invite @yunaki` in that channel |
| Bot process starts but no events arrive | `SLACK_APP_TOKEN` missing/wrong or lacks `connections:write` | Regenerate the app-level token with `connections:write`, update `.env` |
| Auth error on startup | `SLACK_BOT_TOKEN` missing/wrong, or app not installed | Reinstall to workspace, copy the fresh `xoxb-…` token |
| Bot replies in-thread that it can't accept the task | Your member ID not in `SLACK_ALLOWED_USER_IDS` (bot refuses openly, does not stay silent) | Add your `U…` id to the allowlist, restart |
| `/yunaki` command not found | App not reinstalled after adding the command/`commands` scope | Reinstall to workspace (step 3) |
| No WebSocket connection at all | Socket Mode disabled | Enable **Settings → Socket Mode**, restart |
