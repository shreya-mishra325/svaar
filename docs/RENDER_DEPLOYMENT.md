# Render Free demo deployment

Primary target as of 2026-10-31. The private Compose stack remains an unchanged
running fallback. Do not set up a Cloudflare tunnel for this Render deployment.

## Exactly two Free resources

1. Existing Free PostgreSQL named svaar-demo-db in Singapore, created/identified
   by the user. Disable all external database access; keep only private access.
2. One Free Docker web service created from render.yaml, also in Singapore.

The Blueprint deliberately defines only the web service and references the
existing database. It must not create a second DB, paid worker, disk, cron job,
preview environment or paid plan. If the existing database has another name,
change fromDatabase.name before syncing. Auto deploys are off.

Render reports 15-minute idle spin-down and approximately one-minute wakeup.
Free Postgres expires 30 days after creation and is limited to 1 GB. Free services
have no shell access or paid pre-deploy command. Check the actual expiry date.
Sources: https://render.com/docs/free and https://render.com/docs/deploys

Use a personal/Hobby workspace without a payment method for the zero-spend demo.
Stop if Free is unavailable or billing/payment is requested. Existing model/voice
credits are separate from infrastructure; no real call is authorized by deployment.

## Startup

Docker Command: python -m svaar.render_start

The startup module:
- accepts the injected internal PostgreSQL connection string, preserving its
  password and connection options; normalizes the psycopg driver;
- validates Render public-web metadata and production voice configuration;
- serializes overlapping startup migrations using a PostgreSQL session lock;
- runs alembic upgrade head, failing closed before HTTP starts if it fails;
- execs one Uvicorn worker on 0.0.0.0:$PORT with access/proxy-header logging disabled.

Migrations run at startup because a paid pre-deploy job is excluded. There is no
persistent disk, background worker, CI worker or Caspian loop in the Render image
startup. Data lives in PostgreSQL. /ready checks actual SQL connectivity after
migrations; the container probe also follows PORT and the service's Host header.

## Restricted Render ingress

Public paths:
- GET /health and /ready
- POST /api/v1/webhooks/github (disabled until HMAC credentials configured)
- GET /api/v1/voice/llm/models (voice Bearer token)
- POST /api/v1/voice/llm/chat/completions (voice Bearer token and call-reference checks)
- POST /api/v1/voice/status (independent status secret and Bolna source IP allowlist)

Operator/admin endpoints, docs, OpenAPI and function-mode transport are absent.
The factory requires RENDER=true, RENDER_SERVICE_TYPE=web and the exact provided
RENDER_EXTERNAL_HOSTNAME ending in .onrender.com. TrustedHostMiddleware restricts
Host to it. It does not reuse the private deployment's loopback check.

Render documents that its Cloudflare edge replaces CF-Connecting-IP on public
requests. Only this Render factory enables trusting that assertion; status still
requires both its original secret and one exact allowlisted address. Duplicate,
missing or malformed assertions and arbitrary X-Forwarded-For are refused.
The generic application and private Cloudflare listener retain their old policies.
Source: https://render.com/articles/host-pocketbase-on-render

Before a real call, test the actual public edge with an otherwise authenticated
status request containing a forged allowlisted CF-Connecting-IP. From a
non-Bolna machine it must still return 403. If it reaches payload validation
instead, stop: proxy provenance has not been established. Do not weaken the check.

## Human deployment steps

Repository rules require the team, not an agent, to commit/push. Publish the
reviewed Render files and dependent private deployment files without any .env
file. Then on https://dashboard.render.com/:

1. New > Blueprint, connect this GitHub repository and the published branch.
   Grant repository access only as needed. Use render.yaml at the root.
2. Confirm exactly one web service, Free, Singapore, referencing the existing
   Free DB. If anything is priced or a second DB is proposed, stop.
3. Enter the three secrets from the ignored local .env.render:
   SVAAR_LLM_API_KEY, SVAAR_VOICE_TURN_TOKEN, SVAAR_VOICE_STATUS_SECRET.
   Values are generated/copied privately by python -m svaar.render_env; no values
   were printed. Paste just the value, not surrounding dotenv quotes.
4. Confirm the database reference resolves to the internal connection string.
   Do not paste a development URL or database password into chat.
5. Review and approve deployment. Wait for render_migrations_complete and /ready
   health success. Give the engineer the actual HTTPS URL shown by Render; never
   guess the hostname from the service's display name.

Manual web-service form alternative: New > Web Service, same repo/branch,
language Docker, instance Free, Singapore, health path /ready, Docker Command
python -m svaar.render_start. Set the same non-secret variables from render.yaml
and the internal SVAAR_DATABASE_URL privately. Do not create both variants.

The engineer validates HTTP, authentication, SSE framing and proxy spoof rejection
once the real URL is available. Public deployment and external PostgreSQL access
are not claimed from local container checks.

## Caspian decision

Deferred on Render for speed and predictable behavior: background polling is not
continuous on a sleeping Free web service. No paid worker is provisioned and no
gateway is started implicitly. The local Compose gateway is an optional later
demo companion only after message-send approval; it currently uses a different
database and cannot be presented as the Render service's chat state.

## Bolna live acceptance

After public validation, obtain separate authorization for hosted-agent changes:
- Custom model svaar; base URL https://ACTUAL-HOST/api/v1/voice/llm.
- Key: SVAAR_VOICE_TURN_TOKEN from .env.render, not the local fallback token.
- Prompt marker: svaar_call_ref: {{call_ref}}.
- Status URL https://ACTUAL-HOST/api/v1/voice/status, with
  X-Svaar-Voice-Status-Secret matching .env.render.

Warm /ready until it returns 200 before recording or dialing. Do not use an
automated keepalive loop to pretend Free hosting provides continuous operation.

A real call additionally requires an enrolled principal, approved recipient and
a matching prepared call in this Render database. Free has no shell, and operator
HTTP routes remain private/absent. Private provisioning/dispatch access must be
reviewed explicitly before that phase; a queued call in the laptop's different DB
cannot resolve here. Do not invent a reference, expose admin routes, open the DB
to everyone, seed a verified phone or place a call merely to bypass this boundary.
Each exact real phone test still requires approval.

## Recording, after verification

1. Show actual Render URL /ready=200 and both resources marked Free.
2. Show a valid prepared/approved call and its authenticated response path.
3. Demonstrate the live voice exchange, then persisted indexed turn and final
   status in the same database. Queued/model registration alone is not success.
4. Use docs/DEMO_RUNBOOK.md for domain steps only when their prerequisites pass.
   Telegram/GitHub stages are not live until separately configured and tested.
5. If a provider is unavailable, label the local rehearsal OFFLINE/SIMULATED,
   with the private Compose stack as fallback.

## Current verification

- 70 focused startup, proxy/auth, route isolation and call-reference tests passed,
  including their PostgreSQL cases; no full-suite rerun.
- Separate svaar:render-demo image built. Local Render-style startup, migrations,
  dynamic port, readiness, isolation and restart checked with disposable PostgreSQL.
- This is a platform simulation, not actual Render acceptance.
- Private fallback preserved. No public URL, hosted-agent change, real message,
  real call or paid resource has been created by the agent.
