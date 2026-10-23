# Svaar anomalies and open integration questions

Last reviewed: 2026-10-23 (Asia/Calcutta).

## How to use this log

Read alongside `rules.md`, `PLAN.md` and `checkpoints.md`. Record observed defects, intentional
limitations, unresolved contracts and design ambiguities separately. A planned
feature is not a bug, and a successful infrastructure probe is not proof of a
working integration.

For a new entry, use a stable ID and record status, category, evidence, impact,
next action and owner if assigned. Resolve entries with verification evidence;
do not silently delete them. Do not paste secrets or sensitive payloads.

## A-001: Gateway runtime is not implemented

- Status: Open; intentional scaffold limitation.
- Evidence: `src/svaar/gateway.py` exits with code 2 without `--check`.
  `compose.yaml` puts the service behind the `gateway` profile.
- Impact: No live listener, outbox sender or polling jobs run. The successful diagnostic
  proves configuration/database access only, not chat availability.
- Next action: Implement the agent/jobs composition, transport shutdown and runtime
  health reporting before enabling the long-running service.
- Owner: Unassigned.

- Update 2026-10-23: A durable ChatRuntime and OutboxSender now exist independently
  of providers; API composition creates the coordinator when LLM is configured.
  Nothing starts a live listener or sends automatically.
- Subsequent update 2026-10-23: Gateway composition now wires polling, persistent
  stream cursor, chat processing, outbox/receipt workers and SIGTERM/SIGINT cleanup.
  --status checks heartbeat freshness independently of API readiness; Compose uses
  it for health. Fake-provider tests and real PostgreSQL cover these paths.
  Missing configuration prevents normal startup. The subsequent approved MVP
  policy below removes the separate sender-ID contract gate (A-011).
  Live channel acceptance remains open; no keys are fabricated.

## A-002: External provider contracts remain unverified

- Status: Open; integration blockers, not implemented adapter defects.
- Evidence: PLAN.md sections 6, 9, 10 and 19 identify required smoke checks.
  No provider integration code or live-provider verification was added by scaffolding.
- Impact: Do not assume Caspian message IDs, sender trust, transport mode, delivery
  receipts or available channels. Do not assume Bolna's custom LLM endpoint,
  per-call reference delivery or latency units. Do not assume a common Jev payload,
  batching contract or partial-failure schema. The historical chat native-tool
  probe is user-reported in A-008; wider model and live voice behavior remain unverified.
- Next action: Record separately dated, redacted results for each provider and its
  selected mode/version before implementing its adapter. Use Telegram only through
  the same planned transport boundary if the Caspian decision gate selects it.
- Owner: Unassigned.

- Update 2026-10-21: Vercel was selected for Jev. decisions/jev.py is implemented
  against documented TypeSafe-compatible System One/Choice shapes and tested with
  synthetic HTTP responses only. User approved mock-only work; live Jev remains
  pending and its environment/settings composition is disabled. References:
  https://vercel.com/docs/ai-gateway/sdks-and-apis/typesafe and
  https://docs.typesafe.ai/primitives/choice.
- User decision 2026-10-21: Keep chat transport selection pending. Telegram remains
  the plan fallback, not an approved runtime selection in this session. Caspian
  sender-trust, delivery and account access remain unverified. Bolna account,
  turn mode and call-reference delivery remain unverified. Do not place a test
  call without explicit authorization and a specified recipient.

- Update 2026-10-23: User selected Caspian hosted Telegram, superseding the
  pending choice. Public deployed OpenAPI is version 0.1.0; current SDK main
  advertises a 1.0 rewrite. The adapter uses documented REST via existing httpx,
  not assumed SDK constructors. Authenticated GET /v1/events returned 200; field
  names confirmed data.message nesting, ordered seq and stable message IDs in
  the schema. No message content, sender values or credentials were printed.
  Source references: https://api.trycaspianai.com/openapi.json and
  https://github.com/TryCaspian/caspian-sdk/blob/718a96d6d04cb76c7ccce942d2532fd4adbfd545/server/src/comm_gateway/providers/telegram.py.
- Remaining: The saved .env contains the key/base URL, but Telegram connection
  ID/address are absent. A read-only connection probe awaits those saved fields.
  Delivery POST/receipt behavior has synthetic tests only; no outbound message
  was authorized or sent. Stable sender identity is a separate blocker (A-011).
  Supported polling needs no Svaar public webhook route; webhook secret is unused.

- Subsequent acceptance 2026-10-23: After the user saved the connection fields,
  the read-only Caspian probe returned connection_verified=true, poll_verified=true,
  private_text_messages_in_sample=0, sender_identity_verified=false,
  outbound_delivery_verified=false, messages_sent=0. Connection credentials are
  no longer a blocker. This supersedes the missing-field observation above.

## A-003: Feature configuration names are not active settings

- Status: Open; intentional scaffold limitation.
- Evidence: `.env.example` comments and README's feature configuration section;
  `src/svaar/config.py` currently validates infrastructure settings only.
- Impact: Adding provider tokens to `.env` does not enable or validate integrations.
  Compose currently forwards infrastructure variables only. No operator, voice or
  webhook authentication is implemented.
- Next action: Introduce validation and process-specific credential wiring with
  each owning feature. Keep credentials server-side and without usable defaults.
- Update 2026-10-20: `SVAAR_OPERATOR_TOKEN` (validated, passed to `app` only),
  invite, confirmation and policy settings are now active. Provider credentials
  remain comments, so this entry stays open.
- Update 2026-10-21: LLM base URL/key/model are active all-or-none settings and are
  passed only to app/gateway, not migrations. Jev/Bolna/channel settings still
  await their feature composition. Local credential absence is tracked in A-010.
- Owner: Unassigned.

- Update 2026-10-23: Caspian base URL, key, Telegram connection ID and bot address
  are now optional validated settings. Explicit adapter construction/probe requires
  all four; partial values do not start a listener. Compose passes them to gateway
  only. Existing direct Telegram token, email/Slack/Discord IDs remain unused.

## A-004: Upstream test-client deprecation warning

- Status: Open; non-blocking warning.
- Evidence: Last local run on 2026-10-18 passed 29 tests and emitted a
  `StarletteDeprecationWarning` about using httpx with Starlette's test client.
- Impact: Tests currently pass; future dependency updates may require test-client
  changes. This is not an observed production request failure.
- Next action: Review the supported upstream migration when updating dependencies;
  change the lockfile deliberately and rerun tests. Do not suppress the warning
  simply to claim a clean run.
- Owner: Unassigned.

## A-005: Planning document handling instructions conflict

- Status: Open; documentation/workflow conflict.
- Evidence: PLAN.md's introductory note and working rules discourage keeping or
  pushing planning documents. The user's explicit team instructions retain
  `plans/` for collaboration and now authorize these two context files.
- Impact: An agent following the plan alone might delete, move, ignore or commit
  documents against the team's current instructions.
- Current handling: Preserve `plans/` and existing plan contents. Do not change
  `.gitignore`, `.git/info/exclude` or Git configuration to hide these documents.
  Git operations and final submission cleanup belong to the team.
- Next action: Have the team reconcile the wording when it next edits PLAN.md.
- Owner: Team decision; no individual assigned.

## A-006: Confirmation atomicity does not guarantee external exactly-once effects

- Status: Open; design question for implementation, not an observed code defect.
- Evidence: PLAN.md section 7 describes a conditional confirmation update and a
  unique execution key. README also notes external side effects are not atomic
  with database commits. No confirmation executor exists yet.
- Impact: A crash after a provider accepts an action but before its receipt is
  persisted can leave the outcome unknown. Row locks or a unique local record alone
  cannot prove the provider executed exactly once.
- Next action: Define execution/unknown-outcome states, provider idempotency where
  supported, and reconciliation or human review. Never retry a risky action blindly.
  Test concurrency and crash boundaries with the executor implementation.
- Update 2026-10-20: The dispatcher commits a `started` execution row keyed by the
  confirmation ID before running a tier-2 handler. Handlers raise
  `ProviderOutcomeUnknownError` to record `outcome_unknown`; a row left in `started`
  after a crash has the same meaning. Neither is retried. Concurrent local execution
  is tested. Still open: provider idempotency keys, reconciliation and a human
  review path for unknown outcomes; crash-boundary tests need a real provider adapter.
- Owner: Unassigned.

## A-007: Phase 1 implementation choices needing team review

- Status: Open; design decisions made during implementation, not observed defects.
- Evidence: Phase 1 local work on 2026-10-20; see checkpoints.md Phase 1.
- Choices:
  1. Added operator route `POST /api/v1/orgs`. PLAN.md lists only `POST /invites`,
     but an invite needs an existing organization and orgs must not be created from chat.
  2. The unique execution key lives on `tool_executions.execution_key` (set to the
     confirmation ID) rather than on `confirmations`, so approvals does not depend on
     actions. `confirmations` also stores validated `arguments` (JSONB), which the
     plan's column list omits but deferred execution requires.
  3. Same-channel confirmation is refused unless
     `SVAAR_ALLOW_SAME_CHANNEL_CONFIRMATION` is set, even when the owner has only one
     verified channel. PLAN.md says "when they have two"; the stricter reading was
     chosen because nothing else would block a single-channel self-confirmation.
  4. Nonces are six digits, compared after keeping digits only, so spoken digits
     transcribed as numerals match. Number words ("four eight") do not; whether STT
     output needs word-to-digit conversion depends on Bolna's transcripts (A-002).
  5. Policy thresholds default to 0.85 and 0.55 as placeholders until tuned.
- Next action: Team confirms or adjusts each choice.
- Owner: Unassigned.

## A-008: Chat LLM selection and provider key setup

- Status: Resolved for primary model selection and the user-reported 2026-10-20
  native-tool probe, plus the user-reported Oct 21 Mac probe below. Voice
  latency, backup models and transport connectivity are not verified.
- Decision (2026-10-20): Chat and voice use one OpenAI-compatible adapter.
  - Primary: Groq, `SVAAR_LLM_BASE_URL=https://api.groq.com/openai/v1`,
    `SVAAR_LLM_MODEL=openai/gpt-oss-20b`, explicitly chosen by the user after
    reporting the earlier llama candidate unavailable. No current quota or
    first-token/voice-latency guarantee is inferred.
  - Backup: Google Gemini through its OpenAI-compatible endpoint
    `https://generativelanguage.googleapis.com/v1beta/openai/`, a Flash model.
  - Optional for comparison: OpenRouter free models, Cerebras.
  - Jev is not a chat model and stays separate (A-002); decisions fall back safely
    while it is unconfigured.
- Free-tier limits are from secondary 2026 comparison articles, not provider pages:
  Groq roughly 30 requests per minute on 70B models; Gemini roughly 1,500 requests
  per day on Flash. Free tiers may use submitted data for training, so send only
  demo data. These numerical free-tier notes are historical and unverified,
  not current provider guarantees or configuration. Only the primary probe below
  has user-reported native-tool evidence.
- How to generate keys (each developer uses a personal account; never share or
  commit keys, and never paste them into chat or documents):
  1. Groq: sign in at <https://console.groq.com>, open API Keys, create a key, and set
     `SVAAR_LLM_API_KEY` in the local `.env`.
  2. Gemini: create a key at <https://aistudio.google.com/apikey> and keep it in the
     local `.env` for backup testing.
  3. Telegram bot (needed for either chat route): message @BotFather, send `/newbot`,
     choose a name and a username ending in `bot`, and set `SVAAR_TELEGRAM_BOT_TOKEN`.
  4. Caspian (optional until A-002 is answered): create a key at
     <https://dashboard.trycaspianai.com>, or run `caspian init project` outside the
     repository and copy `CASPIAN_API_KEY` to `SVAAR_CASPIAN_API_KEY`. Billing is
     prepaid credit; no free tier is documented.
- User-reported probe on 2026-10-20:
  {"requests":3,"native_tool_calls":true,"median_response_seconds":0.516,
  "measurement":"non_streaming_full_response_not_first_token"}.
  Source: terminal output supplied by the user from the old laptop, not a new
  provider request by the agent. The probe executes no business tools.
- On 2026-10-21 the migrated Mac .env has no active Groq credentials. Restore
  them locally before any explicitly authorized fresh probe; do not paste keys
  into chat. The adapter and all 195 tests pass with mocked inference.
- Caspian documentation notes (read 2026-10-20, not a live check): hosted mode polls
  `GET /v1/events`, so no public route is needed; messages carry a stable `id`,
  `conversation_id`, `channel` and `sender {address, name}`. The documents do not say
  whether `sender.address` is verified by the platform, so Caspian senders are treated
  as unauthenticated until Caspian confirms it (A-002). Telegram remains the fallback.
- Subsequent user-reported Mac result, 2026-10-21: three requests,
  native_tool_calls=true, median_response_seconds=0.5919, measurement
  non_streaming_full_response_not_first_token. This supersedes the credential
  absence above; no first-token/full voice metric is inferred.
- Next action: Use the configured Groq adapter in future runtime composition.
  Chat transport selected as Caspian Telegram on Oct 23; acceptance remains A-002.
- Owner: Unassigned.

## A-009: Full turn deadlines need bounded synchronous handlers

- Status: Open; runtime acceptance requirement.
- Evidence: agent/inference.py bounds read-only inference waits. ToolContext
  carries a monotonic deadline and the dispatcher checks it before a handler.
- Impact: A late model result cannot execute tools, but a synchronous operation
  already running cannot safely be killed. Full eight-second voice latency is
  not established by mocked core tests.
- Next action: Bound database/provider operations to their remaining budgets and
  test actual handler latency and uncertain external outcomes (A-006). Preserve
  durable replies/fallback delivery through the outbox; worker composition is pending.
- Owner: Unassigned.

## A-010: Mac migration readiness and missing provider configuration

- Status: Partially resolved on 2026-10-21; provider credentials remain blocking
  for live integration only, not provider-independent development.
- Resolved: uv 0.11.29, Python 3.12.15 virtual environment and locked backend/
  frontend dependencies installed. Latest main recovered at 41a800a.
  Docker PostgreSQL is healthy on localhost:5434; .env corrected from 5433.
  Development schema is 0002, migration check is clean, health/readiness are 200.
  A separate svaar_test database was created and all 195 tests passed with no
  skips. Existing Starlette warning remains (A-004).
- Local operator token generated privately and checked with a fresh application:
  no token returns 401; valid token with invalid empty body returns 422 without
  creating records. Restart the existing API process to load this new token.
  Local .env also holds the separate test URL. Neither value is published.
- Remaining: Groq key/model configuration, chat-provider credentials, Bolna key/
  agent and live Jev access are absent in this Mac environment. Adding commented
  planned names alone cannot activate unimplemented adapters.
- Update 2026-10-23: Groq is restored with the user-reported Mac probe above.
  Caspian key read access is verified; connection ID/address still need saving.
  Transport selection is now Caspian Telegram. All 226 tests pass locally.
- Next action: User saves connection fields locally, never through chat; resolve
  A-011 before live enrollment. Jev stays mock-only. No provider
  requests, calls, purchases or messages were made during these checks.
- Owner: Local credentials supplied by the user; no provider/team owner assigned.

## A-011: Caspian Telegram sender identity is not stable enough for verified binding

- Status: Accepted MVP limitation by explicit user decision on 2026-10-23;
  no longer a startup/enrollment blocker. See the approved policy below.
- Evidence: Public TelegramProvider parse_update at source commit
  718a96d6d04cb76c7ccce942d2532fd4adbfd545 uses username when present, otherwise
  the numeric Telegram user ID. Public Participant schema exposes only address/
  name; it does not expose a separate immutable user ID or identity assurance.
  Deployment equivalence to that source commit has not been established.
- Impact: A mutable username is not a safe long-lived principal key. A signed
  Telegram webhook authenticates delivery, but does not make usernames immutable.
  Display names, bot addresses and project API keys do not identify the human.
- Historical behavior before the approved policy: Adapter marked sender_authenticated=false; only fresh private
  Telegram text is normalized. No enrollment, binding creation or business tools
  are wired through the live adapter. Poll and delivery contracts use mock tests.
- Follow-up: A stable numeric sender ID remains a future improvement, not an MVP
  prerequisite. The approved private-address binding policy is documented below.
  Provider provisioning and webhook changes were not performed.
- Owner: Provider contract clarification required; no individual assigned.

## A-012: Durable chat state extensions and conservative recovery

- Status: Open; implemented design extensions recorded for review, not an observed
  duplicate-execution failure. All 246 tests pass locally with fake providers.
- Evidence: PLAN.md lists received/processed/failed inbound states. Migration 0003
  adds processing/unknown so a crash after tool execution cannot silently replay.
  It also adds connection IDs for route isolation, payload hashes for conflicting
  duplicates, ordered message positions, outbox ordinals and pending/sending/
  queued/sent/failed/unknown states for receipts and uncertain delivery.
- Policy: Received records are resumable. Processing/unknown requires review.
  A model timeout returning a fixed fallback completes the inbound reply normally.
  Outbound sending/unknown never resends automatically; only explicit known-safe
  rejections can retry, with bounded backoff. Queued acceptance is not delivery.
- Evidence: Tests cover real PostgreSQL enrollment, duplicate/concurrent inbound
  messages, cross-org/thread isolation, locks surviving commits, post-tool crashes,
  outbox concurrency and uncertain sends. Invite commands and confirmation values
  are excluded from later history; secret tickets are persisted only in the outbox.
- Remaining: Operator reconciliation workflow, trusted live sender identity,
  live voice composition are not present.
  Crash safety does not establish exactly-once external effects (A-006).
- Owner: Team review; no individual assigned.

## Resolved entries

- A-008: Primary model and user-reported native-tool probe resolved for the scope
  above. Mac credentials and broader integration remain separate open items.
- A-010: Local dependencies, database port/migration and isolated test coverage
  resolved on 2026-10-21. Provider setup remains open in that entry.

When resolving an entry, retain its ID, add the resolution date, relevant files
and the specific check or external evidence establishing resolution.

### Approved MVP sender policy, 2026-10-23

The user explicitly removed the separate verified stable sender-ID contract
requirement. This supersedes earlier A-011 startup/enrollment blocker statements
in this document. Caspian's authenticated API supplies the private sender address;
the adapter now marks eligible private messages sender_authenticated=true.
Invite enrollment, organization/role checks, confirmation gates, private-message
filtering and generic rejection of unauthenticated transport input remain enforced.
Mutable username changes or reassignment can affect bindings; this is an accepted
MVP limitation, not a verified immutable-ID guarantee. No live gateway, messages
or calls were started for this change. Live channel acceptance remains pending.
