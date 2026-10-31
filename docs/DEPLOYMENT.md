# Svaar deployment

Current primary target: [Render Free](RENDER_DEPLOYMENT.md). The local Compose
configuration below is retained as a fallback. Cloudflare setup is superseded
for the public deployment; do not start its tunnel.

Status on 2026-10-31: private local deployment verified. Public HTTPS and live
Telegram/GitHub/voice end-to-end acceptance are pending. Never treat a healthy
container or mocked rehearsal as live provider acceptance.

## Architecture

Use compose.demo.yaml, a separate project and volume from development:

- PostgreSQL: persistent demo_postgres volume, no published port.
- migrate: one-shot Alembic upgrade before application processes.
- app: private operator/API listener at http://127.0.0.1:18000.
- ingress: provider routes and minimal probes only, bound to 127.0.0.1:8001 inside
  its container namespace. No published host port, docs or operator routes.
- gateway: opt-in chat profile, with persisted cursor/heartbeat.
- ci-worker: opt-in ci profile, with a process-local atomic heartbeat.
- tunnel: opt-in public profile, a named Cloudflare Tunnel sharing the ingress
  network namespace. Its origin is http://127.0.0.1:8001.

All application processes use one image and database, not microservices or a queue
broker. Log reads stay outside chat polling. Containers restart unless stopped;
migrations do not restart repeatedly. Application containers run non-root with
read-only filesystems and writable temporary storage. Logs rotate at 10 MiB,
three files per application container. Database and operator routes never need
public access.

This local deployment depends on Docker Desktop, the laptop staying awake,
electricity and internet. A named tunnel gives a stable hostname, not laptop
uptime. For durable hosting, move this isolated stack and encrypted backup to an
approved VPS and named tunnel. Do not buy/provision it without approval.

## Why a named tunnel

[Quick Tunnels do not support SSE](https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/#limitations).
[Bolna custom LLMs require streamed OpenAI deltas](https://www.bolna.ai/docs/custom-llm-inference).
Do not reuse the old trycloudflare.com URL for this voice path.

The tunnel image is pinned by digest (verified cloudflared 2026.10.7). It connects
to loopback in the ingress network namespace using Compose network_mode:
service:ingress. The ingress rejects other peers and ignores forwarded peer claims.
Status processing additionally checks the existing CF-Connecting-IP allowlist and
independent status secret. Turn requests require their separate Bearer token;
GitHub requests retain raw-body HMAC verification.

This explicitly trusts the dedicated cloudflared process and local Docker admin.
It is not a reusable trust rule for an arbitrary reverse proxy. Do not publish
the origin, change its bind address, enable Uvicorn proxy headers or point the
tunnel at the private operator app.

## Prepare and start privately

Run from the repository root. Dependencies: Docker Compose, Python 3.11+ and the
locked uv environment.

```sh
uv sync --locked
uv run --locked python -m svaar.deployment --source .env --output .env.demo
docker compose --env-file .env.demo -f compose.demo.yaml build app
docker compose --env-file .env.demo -f compose.demo.yaml up -d --wait app ingress
```

Preparation creates a mode-0600 ignored file exclusively; it refuses to overwrite
an existing file. It copies selected existing provider credentials, generates
fresh independent database/operator/status/turn secrets, sets production mode
and leaves CI writes, CI deferral and background business jobs disabled.
It never copies the development password or database URL. Do not print the file
or resolved docker compose config. Use config --quiet for validation.

An existing .env.demo is preserved. Edit only required values locally; changing
POSTGRES_PASSWORD after database initialization does not rotate an existing
database user. Do not delete the persistent volume to resolve credentials.

Required names for the complete demo, without values:

- POSTGRES_USER, POSTGRES_DB, POSTGRES_PASSWORD.
- SVAAR_DATABASE_URL is synthesized for containers from POSTGRES_*.
- SVAAR_OPERATOR_TOKEN: private app only.
- SVAAR_LLM_BASE_URL, SVAAR_LLM_API_KEY, SVAAR_LLM_MODEL; Groq inference.
- SVAAR_CLASSIFIER_ENABLED: required for meaningful typed voice interpretation.
- SVAAR_CASPIAN_BASE_URL, SVAAR_CASPIAN_API_KEY,
  SVAAR_CASPIAN_TELEGRAM_CONNECTION_ID, SVAAR_CASPIAN_TELEGRAM_ADDRESS.
- SVAAR_BOLNA_API_KEY, SVAAR_BOLNA_AGENT_ID: explicit operator dispatch only.
- SVAAR_VOICE_TURN_MODE=llm_endpoint, SVAAR_VOICE_TURN_TOKEN,
  SVAAR_VOICE_STATUS_SECRET: restricted origin.
- SVAAR_GITHUB_WEBHOOK_SECRET and paired SVAAR_GITHUB_APP_ID,
  SVAAR_GITHUB_PRIVATE_KEY_B64 for live CI/log reads.
- CLOUDFLARE_TUNNEL_TOKEN: tunnel container only.

Optional controls: SVAAR_GITHUB_ENRICHMENT_ENABLED, SVAAR_CI_BATCH_SIZE,
SVAAR_CI_POLL_SECONDS, SVAAR_ESCALATION_JOBS_ENABLED,
SVAAR_CLAIM_CHECK_JOBS_ENABLED. None places calls automatically.
SVAAR_GITHUB_ACTIONS_ENABLED remains false until a specific CI write demo is
approved. Keep SVAAR_ALLOW_SAME_CHANNEL_CONFIRMATION=false.

## Human boundaries, in order

1. Named tunnel: in the [Cloudflare dashboard](https://dash.cloudflare.com/), open
   Networking > Tunnels > Create Tunnel. Use an existing Cloudflare-managed domain;
   [a domain is required to publish](https://developers.cloudflare.com/tunnel/get-started/).
   Save the connector token locally as CLOUDFLARE_TUNNEL_TOKEN in .env.demo.
   Under Routes > Add route > Published application choose a hostname and origin
   http://127.0.0.1:8001. Do not point it at app:8000 or port 18000.
   Do not buy a domain or paid plan without approval.
2. After the user approves publication to that hostname, the deployment engineer
   starts the public profile and verifies HTTPS route isolation and SSE remotely.
3. After separate authorization to send through the configured bot, start the chat
   profile. It may process existing incoming messages and send outbox replies.
   Provision an explicit demo org/invite and let the owner enroll privately.
4. Configure GitHub App/subscriptions only with approval for the controlled
   repository. Required webhook events: workflow_run and pull_request.
   Set the webhook to https://HOST/api/v1/webhooks/github, JSON, with the demo HMAC
   secret. Set the explicit installation/repository/org/owner mapping locally.
   Enable CI deferral and start the ci profile only when App credentials are ready.
5. The user configures the Bolna agent: custom model svaar, base URL
   https://HOST/api/v1/voice/llm, key from SVAAR_VOICE_TURN_TOKEN; prompt line
   svaar_call_ref: {{call_ref}}. Status URL is
   https://HOST/api/v1/voice/status, with header X-Svaar-Voice-Status-Secret from
   the matching .env.demo value. Do not reuse the old .env callback secret.
6. Each live call requires explicit approval for the exact call ID and intended
   recipient. Use phone_verify for initial proof of phone ownership. The operator
   dispatch CLI enforces readiness, mission/recipient checks and daily limits.

The engineer handles terminal steps; the user supplies dashboard access/grants
and explicit approvals. Never paste tokens, private keys or phone numbers in chat.

## Commands after the corresponding authorization

```sh
docker compose --env-file .env.demo -f compose.demo.yaml --profile public up -d tunnel
docker compose --env-file .env.demo -f compose.demo.yaml --profile chat up -d --wait gateway
docker compose --env-file .env.demo -f compose.demo.yaml --profile ci up -d --wait ci-worker
```

When credentials/flags change, recreate affected services. Do not expect restart
alone to load new container environment. After recreating ingress, recreate the
tunnel too: it must join the new ingress namespace.

## Health and diagnostics

```sh
docker compose --env-file .env.demo -f compose.demo.yaml ps
docker compose --env-file .env.demo -f compose.demo.yaml exec -T app alembic current
docker compose --env-file .env.demo -f compose.demo.yaml exec -T app alembic check
docker compose --env-file .env.demo -f compose.demo.yaml exec -T gateway python -m svaar.gateway --status
docker compose --env-file .env.demo -f compose.demo.yaml exec -T ci-worker python -m svaar.jobs --status
docker compose --env-file .env.demo -f compose.demo.yaml logs --tail 80 app ingress gateway ci-worker
```

GET http://127.0.0.1:18000/health and /ready are private probes. /ready verifies SQL
connectivity; migration completion/schema check is separate. The restricted
origin also has /health and /ready but is reachable only from its own namespace.
Production disables docs. /api/v1/orgs and operator mutation routes return 404
on ingress, not just 401.

Restart policy restarts an exited process, not an unhealthy-but-running process.
Investigate unhealthy status rather than treating it as automatic recovery.

CI heartbeat reports a fresh running/ready process, not successful GitHub
authentication or log retrieval. Empty-queue lifecycle was tested with synthetic
App credentials; real App acceptance remains pending.

401: check credential scope and matching demo environment, never print headers.
403 on status: verify the real Bolna source IP and Cloudflare header path against
provider documentation; do not expand the allowlist by guessing.
422: inspect only safe schema field/error types, never log raw call payloads.
404 on a synthetically valid callback: its execution/agent is not a placed call;
it is not evidence of callback success.
Gateway stale: inspect persisted state and sanitized logs; uncertain inbound or
outbox states require review, never forced replay.
Unhealthy CI worker: inspect the heartbeat and App configuration; pending CI jobs
are durable and do not disappear on restart.

## Backup, update and recovery

Use an ignored local directory and protect backup files, which may contain private
messages and identity information.

```sh
mkdir -p .cache/deployment
docker compose --env-file .env.demo -f compose.demo.yaml exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' > .cache/deployment/demo.dump
docker image tag svaar:demo svaar:demo-before-update
docker compose --env-file .env.demo -f compose.demo.yaml build app
docker compose --env-file .env.demo -f compose.demo.yaml run --rm migrate
docker compose --env-file .env.demo -f compose.demo.yaml up -d --wait app ingress
```

Stop the tunnel/chat/CI profiles before a risky update, after reviewing any
in-flight calls. Preserve the named volume. Do not use down -v, prune volumes or
downgrade a database with unresolved calls/confirmations to force a rollback.

For a code-only rollback compatible with the current schema, retag the previous
image to svaar:demo and recreate application services. If schema changes are
incompatible, stop writers and restore a reviewed backup into a new recovery
database/volume, validate there, then switch deliberately. Never restore over
current data blindly. After ingress recreation, recreate tunnel.

The restart test inserted a temporary probe into this new isolated demo database,
restarted db/app/ingress, verified the probe survived, then removed only that probe.
The existing development database/volume was not modified.

## Verification record

- 784 tests passed, none skipped, on a new disposable PostgreSQL instance.
- Ruff lint/format, Compose profiles and Docker build passed.
- Demo schema 0026, migrations and alembic check passed before/after restart.
- app/db/ingress healthy; app is non-root; private env files absent from image.
- Local authenticated synthetic SSE refusal completed with [DONE]; not a real call.
- Groq native tools: three requests on host, median full response 0.3857 seconds;
  three in the image, median 0.602 seconds. These are not first-token measurements.
- Caspian connection/poll verified read-only, zero messages sent.
- Bolna account/agent ready read-only, zero calls.
- Real CI worker startup/restart heartbeat verified with synthetic credentials and
  an empty disposable queue, then the test worker stopped.
- Live gateway: not started; only its database check and fake-runtime tests passed.
- Public tunnel, GitHub delivery, actual outbound chat and real voice: not verified.

No external provider configuration, DNS, billing, messages, workflow mutations or
calls were changed. Current branch was locally clean before deployment edits;
no fetch/pull/commit/push was performed. Secrets live only in ignored private files.
