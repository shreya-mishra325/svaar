# Caspian channels

The user's Oct 31 instruction expands the current build beyond PLAN.md's Discord/
email cuts and optional Slack. PLAN.md itself is unchanged. All channels share
ChatRuntime, the action dispatcher, durable inbound dedupe and outbox. No extra
SDK, schema, paid service or public route was added.

## Implementation and acceptance

| Channel | Implemented path | Remaining live requirement |
| --- | --- | --- |
| Telegram | Existing private chat adapter, backward compatible | Completed enrollment, read-tool and delivery acceptance |
| Slack | Private one-to-one DMs with chat_type=im | User message and authorized reply delivery |
| Discord | DMs with chat_type=dm | A DM-capable connection and authorized reply delivery |
| Email | Connection/poll/receipt diagnostics; sends and gateway startup refused | Provider-authenticated sender evidence or a separately reviewed email identity design |

GET-only account checks on Oct 31 confirmed all three additional configured
connections active with receive/reply/send capabilities. New adapters' connection
and event-poll probes passed. No new-channel sends were performed; no private
messages appeared in the sampled ten earliest project events. A sample without
messages does not establish inbound delivery. Credentials remain local/ignored.

## Privacy and identity

The deployed normalized schema is at https://api.trycaspianai.com/openapi.json.
Channel privacy labels were checked in official provider source at commit
718a96d6d04cb76c7ccce942d2532fd4adbfd545:
- server/src/comm_gateway/providers/slack.py uses channel_type (im for a DM).
- server/src/comm_gateway/providers/discord.py uses dm or guild. The shared guild
  install skips DMs because it cannot route them to a guild connection. An invite
  to that shared server bot alone therefore does not establish a usable private
  Svaar chat. Do not enable guild messages to bypass this limitation.

Slack channels, multiparty DMs, Discord guilds and unknown privacy labels are
skipped; they cannot redeem invites or receive phone/confirmation codes. Edits,
automated messages, other connections and malformed events retain existing guards.
Private Slack/Discord messages use the existing Caspian sender-address MVP policy;
this does not prove immutable sender IDs. Each channel requires its own operator
invite. Identities are not merged by matching display names or usernames.

Email MessageOut exposes sender.address, not an authentication verdict. An asserted
From address cannot establish a verified binding. Email poll results are marked
unauthenticated; the gateway refuses startup and the adapter refuses sends before
network I/O. Do not claim email enrollment or business actions are implemented.

## Configuration and read-only checks

Set SVAAR_CASPIAN_BASE_URL and SVAAR_CASPIAN_API_KEY, then the selected channel's
SVAAR_CASPIAN_<CHANNEL>_CONNECTION_ID and SVAAR_CASPIAN_<CHANNEL>_ADDRESS.
SVAAR_CASPIAN_CHANNEL defaults to telegram. Selection never reuses another
channel's connection/address. The existing Discord guild ID is not a substitute
for the provider's actual connection address.

These probes only GET; they do not start a gateway or send messages:

```bash
uv run --locked python -m svaar.agent.caspian_smoke --channel slack
uv run --locked python -m svaar.agent.caspian_smoke --channel discord
uv run --locked python -m svaar.agent.caspian_smoke --channel email
```

## Explicit local demo companions

Only run each listener after authorization to process messages and send replies
on that exact connection. These commands use the same Render database via the
ignored .env.render-control (external psycopg URL with sslmode=require), with
provider settings from .env. They do not deploy a service. Keep PostgreSQL external
access limited to the laptop IP and remove it when finished. Check workspace rules
as well; their effective scope has not been independently verified.

```bash
uv run --locked --env-file .env --env-file .env.render-control python -m svaar.gateway --channel slack
uv run --locked --env-file .env --env-file .env.render-control python -m svaar.gateway --channel discord
```

One channel per process, one terminal per active companion. Each stream has its own
cursor, database lock and outbox scope. Do not start duplicate Telegram listeners
while the approved companion is already running. These listeners do not dial calls;
placement remains an explicit, separately authorized dispatch. Local listeners stop
with their process/laptop; Render's Free service still runs no polling worker.
Only the user publishes or deploys changes. No Render redeployment was performed.

85 focused channel/configuration/gateway tests passed without skips against a new
disposable PostgreSQL database, including Slack/Discord enrollment, gated whoami,
reply delivery and restart dedupe with fake providers. Alembic drift check passed.
Existing Starlette/httpx deprecation warning remains. No full-suite rerun.
