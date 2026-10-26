# Svaar anomalies and open integration questions

Last reviewed: 2026-10-24 (Asia/Calcutta).

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

## A-013: Internal voice runner requires transport turn identity and notification wiring

- Status: Open; internal implementation tested, live transport not implemented.
- Evidence (2026-10-23): TurnRunner previously accepted only call_id/text. That
  cannot distinguish a retry from the same utterance spoken again. Added an
  optional keyword turn_index; its absence refuses execution. The transport must
  provide a stable zero-based index after authentication and call-reference
  resolution. No Bolna request field or index algorithm is assumed verified.
- Implemented: Ordinary server-owned active voice_calls bound to a verified phone,
  organization, principal and fixed mission; durable indexed voice_turns and
  bounded private history. Only application composition imports both voice and
  agent. Unknown execution outcomes do not retry. Twenty new tests cover the real
  action gates, fake usability/intent inference, duplicate/conflicting requests,
  identity isolation, unusable speech, unavailable model, concurrent processing,
  crashes and history redaction. Full suite: 276 passed.
- Deliberate scope: Migration 0005 is a minimal ordinary-call schema, not the full
  planned provider/callback/transcript schema. phone_verify is excluded until its
  pending challenge and exact-number binding exist. No production call creation,
  activation or provider route was added. Migration was tested on svaar_test only.
- Remaining: Verify provider call-reference/index delivery before exposing a route.
  Add fallback chat notifications and secret confirmation delivery through a
  durable outbox. Existing fallback wording mentions messaging, but no such
  notification is delivered by this runner yet. Unexpected secret tickets fail
  closed rather than being spoken or silently treated as delivered.
- Owner: Unassigned.

## A-014: Bolna placement adapter verified from docs, live transport still pending

- Status: Open; implemented internal adapter/service, not live call acceptance.
- Evidence (2026-10-23): Official POST /call returns queued plus execution_id;
  GET /executions/{execution_id} exposes agent ID and lifecycle status. Explicit
  retry_config.enabled=false disables provider auto-retries. Sources:
  https://www.bolna.ai/docs/api-reference/calls/make
  https://www.bolna.ai/docs/api-reference/executions/get_execution
  https://www.bolna.ai/docs/outbound/auto-retry
- Implemented: BolnaClient with fixed HTTPS host, Bearer SecretStr, bounded HTTP,
  redirects/proxy inheritance disabled, no retries and sanitized errors.
  Internal CallService claims a scoped pending intent before POST, rechecks
  verified phone ownership, hashes private call references and records receipt
  identity/status. Unknown placement never redials. Read reconciliation rejects
  mismatched IDs and stale progress; final calls cannot reopen.
- Verification: 321 tests passed with synthetic HTTP/fake providers and isolated
  PostgreSQL. Migration 0006 drift and empty-test-database round trip passed.
  Initial migration failed due to a double-prefixed constraint name; op.f fixed
  the unapplied migration and all verification passed afterwards.
- Remaining: Live account readiness was not checked. The public OpenAPI URL
  returned 404, so no user/me response schema was invented. No account smoke,
  provider turn-reference/index delivery or chosen turn mode is verified.
  Phone challenge, per-mission scheduling/limits, provider routes, notification
  delivery and authenticated callbacks remain pending. CallService is not exposed
  to models, API routes or a scheduler; business callers must use the action gate.
- Schema extension: 0006 adds placing/queued/failed/unknown states and nullable
  receipt/reference-hash fields. Downgrade refuses unsupported placement states;
  operators must reconcile those rather than reset to pending and risk redialing.
  Progress statuses are monotonic under disabled retry/rescheduling; rescheduling
  is not supported by the MVP service.
- Outcome: No live authenticated provider requests, calls, messages or purchases.
  Bolna settings activate only explicit client construction; they are not forwarded
  through Compose until a process composes the provider.
- Live evidence 2026-10-24 (user-authorized, recipient owned by the user and kept
  out of logs, files and this document):
  - GET /user/me: key accepted; trial account, max concurrency 2.
  - Agent "Svaar" exists, status processed, still on Bolna's own model (Azure
    gpt-4.1-mini) with no custom LLM endpoint, tools or status webhook.
  - First attempts returned 400 "Trial accounts can only make calls to verified
    phone numbers"; BolnaClient correctly raised CallRejectedError. After the
    user verified the number in the Bolna dashboard, placement was accepted.
  - Call 1 (execution e7bbd55c-...): initiated, ringing, busy; hangup by carrier;
    cost 0. Call 2 (execution c220761a-...): ringing, in-progress,
    call-disconnected, completed; hangup by callee; 41 s; cost 6.0 wallet units
    (wallet 500.0 to 494.0); transcript present but not read or stored.
  - latency_data.time_to_first_audio was 102.248 on a 41 s call, so its unit is
    not seconds (likely milliseconds); still unconfirmed by Bolna documentation.
  - Not verified: custom LLM turn mode, per-call reference delivery, status
    webhook and Svaar answering on a call. Those need the turn/status routes,
    a public tunnel and agent reconfiguration.
- Owner: Unassigned.

## A-015: Phone verification core exists; private delivery and live transport remain

- Status: Open; internal challenge/mission implementation verified offline only.
- Evidence (2026-10-23): Added identity-owned phone_challenges, salted scrypt code
  hashes, ten-minute expiry, three failed-attempt limit, principal/number cooldown
  and supersession. Pending numbers do not reserve phone bindings. A correct
  exact ASCII-digit comparison creates the intended phone binding atomically.
  Spaces/hyphens may separate digits; words, guessed substrings and Unicode digit
  substitutions do not verify.
- Mission exception: phone_verify call intents reference exactly one pending
  challenge, intended organization/principal and number. They have no ordinary
  verified-phone binding. Ordinary call contexts cannot carry a pending challenge.
  Only verify_phone_code is offered and all tool execution passes actions.
  Caller transcript overrides model-proposed code; model-selected challenge IDs
  and target numbers are not accepted as tool arguments.
- Verification: 344 tests passed (23 new) with real PostgreSQL/fake providers,
  including exact/leading-zero codes, expiry/attempts, cooldown/supersession,
  ownership, concurrent verification, pending-number placement, unusable speech,
  invented-code rejection, mission boundaries, saved replies and code-free history.
  Ruff and test-only migration 0007 round trip/drift checks passed.
- Remaining: IssuedPhoneChallenge returns the secret code once to an internal
  coordinator, but no live chat issuance command or durable private code delivery
  is wired yet. No provider turn/status route is exposed; Bolna reference/index
  delivery, auth, callback dedupe and account readiness remain unverified.
  Unconfigured Jev still requests clarification; this is not a working live
  verification demo. No pending phone is ever marked verified on call failure.
- Scope: The schema/runner exception supersedes A-013/A-014 notes that excluded
  phone_verify. The complete phase deliverable remains unticked until private
  delivery and the authorized real call work. Development migrations are pending.
- Owner: Unassigned.

### A-015 update: private issuance and delivery wired, 2026-10-23

Private chat code issuance/delivery is no longer an unimplemented coordinator.
ChatRuntime handles /verify_phone only after authenticated enrollment and
atomically persists a challenge, pending call intent, private code outbox and
inbound dedupe. The command and reply never enter inference/history. Application
and gateway inject a voice callback without agent/voice implementation imports.
No automatic call placement or call-scheduling policy was enabled.

OutboxMessage.phone_challenge_id (migration 0008) lets the sender recheck challenge
validity and recipient scope before sending. Stale or superseded codes fail
closed. Codes are plaintext only in the private delivery outbox; identity keeps a
salted scrypt hash. Uncertain sends remain non-retryable. Downgrade refuses to
discard guards while linked deliveries are pending/sending/queued/unknown.

Evidence: 359 tests passed, including 15 new integrated chat/private delivery/fake
call/shared-agent verification tests and migration downgrade refusal. Ruff and
test-only migration round trip/drift passed. Development DB upgraded to 0008 and
drift check passed. No live provider requests, messages or calls. Status remains
open for authenticated provider routes, reference/index delivery, account
readiness/scheduling, voice decision-provider composition and authorized real
acceptance. Earlier notes that code delivery was absent are historical.

## A-016: Voice fallback follow-ups wired; live delivery and route ambiguity remain

- Status: Partially resolved, 2026-10-23. Application composition injects an
  agent-owned outbox callback into VoiceRuntime without cross-imports between
  agent and voice implementations.
- Implemented: Unavailable/tool-limited turns and unexpected execution errors queue
  a generic private follow-up atomically with turn state. Crash-marker retries can
  queue it without repeating tools. One key per call/turn and locked inbound
  anchors prevent duplicate notifications/ordinal collisions. Existing outbox
  receipt handling and uncertain-send policy are reused.
- Routing: Exactly one existing organization/principal-scoped conversation with
  a verified sender binding is required. No latest-organization or arbitrary-route
  guess is made. Missing/ambiguous routes or notification failures use a spoken
  request to continue in chat; only successfully queued notifications get the
  queued-follow-up line. Sender rechecks current recipient ownership.
- Scope: Generic follow-up text never contains caller speech, phone numbers,
  nonces or claim evidence. Confirmation ticket delivery remains separate/pending.
  Full eight-second end-to-end latency remains A-009; added DB work is not a
  proven live timing result. No notification polling service was added.
- Evidence: Part of 396 passing tests with real PostgreSQL/fake transports,
  including failure/timeout results, unknown execution, interrupted processing,
  concurrent ordinals, dedupe, ambiguous routing, revocation and no notification
  on ordinary clarification/refusal. No live messages were sent.

## A-017: GitHub ingestion exists; incident aggregate and App client remain pending

- Status: Partial Phase 4 implementation verified with synthetic signed payloads.
- Verified public contracts (2026-10-23):
  https://docs.github.com/en/webhooks/using-webhooks/validating-webhook-deliveries
  https://docs.github.com/en/webhooks/webhook-events-and-payloads#workflow_run
  https://docs.github.com/en/webhooks/using-webhooks/best-practices-for-using-webhooks
- Implemented: POST /api/v1/webhooks/github validates raw-body HMAC with a separate
  optional 32+ character secret; absent secret returns 503. Body is capped at
  1 MiB; duplicate JSON keys and non-JSON numeric constants are rejected.
  Workflow action/status/conclusion, IDs, SHA and timezone-aware occurrence time
  are validated. Only explicit repo/installation/org mappings can create facts.
  POST /api/v1/repo-mappings requires the operator token and refuses overwrites.
- HTTP behavior follows PLAN.md: malformed JSON 400, unsupported events
  200/handled=false, unmapped repositories rejected with 404 and sanitized logs.
  Typed payload/header errors use 422; duplicate-ID/content conflicts use 409.
  Unsupported/unmapped receipts retain their outcome on redelivery. Previously
  ignored/unmapped IDs are not automatically replayed after adding a mapping.
- Persistence: Delivery IDs and normalized run-transition keys are separate
  dedupe boundaries; observations and delivery receipts commit together.
  events stores source provenance and normalized fields only. PostgreSQL blocks
  updates/deletes. Arrival order never rewrites source occurrence timestamps.
- Plan/schema extensions needing awareness: Current events are org/repository
  observations before an incident aggregate exists. external_key implements the
  planned stable external_id concept; data is the normalized payload. An incident
  association is not present yet and must be added without rewriting observed
  facts. Repo mappings use numeric repository plus installation IDs instead of
  guessing organization from names. Delivery receipts include outcome/hash/event
  linkage beyond the plan's minimal columns.
- Remaining: GitHub App auth/REST client, incident grouping/fingerprints,
  incident-scoped timeline/get_timeline, owner alerts and live repository
  acceptance. No CI mutation, rerun, model call or claim inference is performed.
  No tunnel was configured. The 1 MiB bound may need revisiting for large real
  workflow payloads; it is an MVP application limit, not GitHub's advertised cap.
- Evidence: 396 tests passed (37 new across this task); schema drift, test-only
  0010 -> 0008 -> 0010 round trip, Ruff and Compose passed. Development DB is 0010.
  No live provider calls or messages and no new dependency/infrastructure.
- Update 2026-10-24: incidents and incident_events (migration 0011) group
  observations without rewriting facts. A failure, timed_out or startup_failure
  run opens one active incident per org and fingerprint (repository, workflow_id,
  head_branch); later runs on that fingerprint join it. A success is linked as
  evidence only and never resolves an incident. An advisory lock plus a partial
  unique index serialize concurrent deliveries. Normalization now keeps optional
  workflow_id, workflow name and head_branch. Tools get_timeline, list_incidents
  and acknowledge_incident dispatch through actions; GET
  /api/v1/incidents/{id}/timeline is operator-only. Remaining: log-tail
  fingerprint (needs the App client), owner mapping and outbox alerts.
  Evidence: 411 tests passed (15 new), drift check clean, dev DB at 0011.
  Synthetic deliveries only; no live GitHub requests.

## A-018: Incident alert recipients stand in for a missing repository owner

- Status: Open; design decision needing team review, not an observed defect.
- Evidence: src/svaar/incidents/alerts.py, src/svaar/integrations/github.py
  (2026-10-24). PLAN.md says the owner is alerted, but no owner field exists on
  repositories, mappings or incidents.
- Current handling: opening an incident queues one private-chat alert to every
  principal with role ops, lead or admin in the incident's organization. Each
  alert is keyed incident-opened:<incident>:<principal>, so redelivery never
  repeats it. Principals without exactly one verified private route are skipped.
  Alerts are queued in the ingest transaction; if queueing fails, the observation
  and incident roll back together. The body names only workflow and branch.
- Impact: a team with many leads receives several alerts; nobody is singled out
  as owner, so escalation calls (Phase 5) still need an owner rule.
- Next action: decide an owner rule (per repository mapping, on-call rotation or
  first acknowledger) before Phase 5 escalation.
- Owner: Unassigned.

## A-019: Negotiation constraints are supplied per request, not stored per agent

- Status: Open; design decision needing team awareness, not an observed defect.
- Evidence: src/svaar/resolution/ and migration 0012 (2026-10-24).
- Plan difference: PLAN.md lists a constraints table (owner_agent, rule). The
  implementation takes typed constraints with each negotiation and stores a JSON
  snapshot on the negotiation row, so a stored verdict stays reproducible after
  rules change. There is no standing per-organization rule store yet.
- Behavior: the release agent only moves the start past freezes and never adds
  approvals; capacity moves past busy slots and maintenance; staffing reassigns
  to the first engineer, alphabetically, with no staffing violation. At most five
  rounds; a proposal that cannot progress ends rejected. Only the validator can
  accept. The demo conflict (freeze, off-shift engineer, deploy slot) is rejected
  and its revision accepted in round two.
- Remaining: a standing constraint store, a start_negotiation chat tool (it needs
  trusted constraints rather than model-supplied ones), optional Jev ranking,
  and the approve_exception tier-2 flow.
- Evidence: 436 tests passed (22 new); drift clean; dev DB at 0012.
- Owner: Unassigned.


### A-014 configuration update, 2026-10-24

The user reports adding SVAAR_BOLNA_API_KEY. A presence-only saved-.env check
found API key present and agent ID absent.
No value was displayed, .env was not edited, and no provider request was made.
The API key was detected on the final saved-file check; the earlier presence
check did not find it. No secret values were inspected or published.
Account readiness, chosen turn mode, reference/index delivery and an explicitly
authorized real test call remain unverified. This is configuration evidence only,
not resolution of the live transport requirements.

The checkpoint layout now separates implementation, offline verification and
live acceptance under each original phase. Historical evidence and original exit
checks are retained. The last implementation suite remains 396 passed on Oct 23;
no implementation checks were rerun for the Oct 24 documentation restructure.


### A-014 subsequent configuration update, 2026-10-24

The user added the agent ID. Both Bolna API key and agent ID are now present in
the saved .env. Settings validation and BolnaClient.from_settings construction/
cleanup passed with no HTTP request. This supersedes the earlier missing-agent-ID
observation. No values were displayed and .env was not edited. Account/agent
readiness, turn mode/reference/index delivery and authorized live acceptance
remain pending; configuration validation does not establish provider access.


### A-014 authenticated readiness update, 2026-10-24

GET /user/me and GET /v2/agent/{configured_id} succeeded. The wallet is positive,
concurrency is available, the configured ID matches, and the agent is processed
with a conversation task. The reusable read-only smoke command also passed.
No secret, exact balance, personal data or provider prompt was printed.
The hosted agent currently lacks an ask_svaar bridge and call_ref template.
No agent update, outbound call or message was performed. Account-read access is
verified; per-turn delivery, stable retry identifiers, callback delivery and
telephony acceptance remain unresolved. Readiness does not close A-014.


### A-014 status receipt implementation update, 2026-10-24

The documented status webhook now has an implemented endpoint, independent
header credential, direct peer allowlist, bounded parsing and atomic receipt
dedupe. Synthetic HTTP and PostgreSQL tests pass; no real callback was received.
Uvicorn must disable proxy headers. A generic tunnel will expose its own peer,
so trusted ingress remains an explicit integration task, not an accepted
forwarded-IP assumption. The hosted agent has not been changed.

Status processing currently records transport lifecycle only. Claim evidence,
transcript retention/classification and failure notifications are still pending,
as are the turn bridge and stable retry binding. No live calls are authorized
by account readiness alone. Full suite: 417 passed; migration 0011 verified on
isolated test and local development databases.


### A-014 failure notification wiring update, 2026-10-24

Failed/unanswered callbacks now enqueue one generic private outbox follow-up per
call via root application composition. Receipt and notification are atomic;
enqueue exceptions allow redelivery, while absent/ambiguous verified routes
deliberately queue nothing. Claim status and phone verification are unaffected.
Full suite 430 passed; final status/notification scope 35 passed after the HTTP
composition test was added. No live delivery is established. Operator balance
alerts, turn reference/retry binding and trusted public ingress remain pending.


### A-013 reference resolution update, 2026-10-24

The internal ReferencedTurnRunner now resolves hashed private placement references
to stored calls with execution/agent receipts and delegates to VoiceRuntime.
It refuses malformed/missing indices and ineligible or unknown references.
Full suite 451 passed, including durable runner retry and closed-call tests.
No public route was added. Bolna parameter/auth documentation does not establish
stable retry identity; that provider contract and trusted ingress remain open.
Do not generate an index in the model or deduplicate by transcript text.


### A-014 restricted ingress update, 2026-10-24

Implemented a dedicated status-only Cloudflare origin listener. It requires
loopback peer, a single allowed CF-Connecting-IP value and the independent
callback secret. The normal app does not trust that header. This explicitly
trusts the local host and its cloudflared process; it is not a general proxy
trust policy. The listener must bind 127.0.0.1 with Uvicorn proxy headers disabled.
Only the exact status route is exposed. No tunnel launch or live delivery has
occurred. Real edge-header behavior and provider acceptance remain open.


## A-020: duplicate Alembic revision during branch merge

- Observed 2026-10-26: main's incident schema and the voice branch both used
  revision 0011 after 0010. This collision was not marked as a textual Git
  conflict but would make migration history ambiguous.
- Resolution: main's 0011 -> 0012 -> 0013 remains unchanged. Voice receipts now
  identify as 0011_voice; revision 0014 joins 0013 and 0011_voice.
- Local recovery: both svaar and svaar_test were verified at old voice-only
  0011, with voice_webhook_events present, its expected columns and unique key,
  and incident/negotiation/replay tables absent. Their migration label alone
  was transactionally corrected to 0011_voice; no domain data was changed.
- Verification: 526 tests passed without skips; lint/format passed. On the test
  database, downgrade to 0010, main-only upgrade to 0013, upgrade through the
  voice branch to 0014 and drift check passed. Development upgraded to 0014
  with clean drift check. The earlier full suite also migrated voice-only
  0011_voice through the incoming main branch successfully.
- Other developers: a main database already at 0011/0012/0013 follows the normal
  upgrade path. An old voice-only 0011 database needs the same schema-verified
  label correction first. Do not blindly stamp, drop tables or run downgrade
  on development databases to bypass the collision.
- Four textual conflicts are resolved in the working files. The user must
  stage the resolutions and commit the paused merge manually.


## A-021: partial voice status lifecycle differs from the authoritative plan

- Observed 2026-10-26 while reconciling the merge to main's PLAN.md section 10.
- Current apply_provider_status closes every terminal outcome, including
  no-answer/busy/failed/canceled/stopped/error. The plan requires failed state
  for these outcomes. Tests currently assert transport closure, not the full
  planned failure state semantics.
- Completed callbacks do not yet classify/retain transcripts or persist evidence;
  balance-low does not yet enqueue an operator alert. Failed-call private
  follow-ups are implemented, but do not complete those missing requirements.
- Treat these as incomplete plan work; passing tests are scoped to the implemented
  transport layer. Do not count them as full status lifecycle/live acceptance.
- Remaining voice wiring belongs to the user's teammate. Align state transitions
  and tests with the plan alongside existing pending domain work; do not weaken
  claims, authentication, dedupe or retention requirements.
- No code or plan change was made during this documentation reconciliation.

### Main-plan precedence clarification, 2026-10-26

The user designated the incoming main plan authoritative. Read-only comparison
confirmed plans/PLAN.md is identical in both merge parents and the working tree.
Main's revised progress records are retained in the combined checklist with
scoped evidence; they do not override product requirements. A-018 owner selection
and A-019 request-scoped constraints remain open plan differences, not approved
plan amendments. Earlier session instructions retaining plans/ and prohibiting
agent Git mutations continue to govern the team's manual workflow.


### A-017 App adapter update, 2026-10-26

The standalone GitHub App adapter now supports RS256 installation authentication
and verified repository/workflow-run reads scoped through an explicit same-org
repo mapping. Synthetic signing/HTTP/cache/concurrency/isolation tests pass.
Full suite: 545 passed. This is mocked contract verification, not live App access.
No logs/archive download, runtime composition, log-tail fingerprint, explicit
repository owner or confirmed risky CI action is established. The client only
requests Actions/metadata read permissions. No live provider calls were made.


### A-017 log retrieval/signature update, 2026-10-26

Standalone failed-workflow archive download and normalized log-tail-v1 signatures
are implemented and mocked/tested. API credentials never reach storage downloads;
host/redirect and archive expansion bounds apply. Only hashes return; raw logs
are neither persisted nor logged. Full PostgreSQL suite 570 passed.
Runtime retrieval, attempt-bound persisted provenance and log-based grouping are
still absent; the existing repository/workflow/branch grouping remains in use.
Unavailable or invalid logs raise a sanitized error, never a shared empty hash.
No live GitHub log contract/account acceptance or production recovery is claimed.


### A-017 attempt provenance update, 2026-10-26

Explicit enrichment now checks signed observation/delivery scope, verifies
attempt-specific GitHub metadata and stores immutable hash provenance in
workflow_log_signatures (0015). Reads occur outside DB transactions; mappings are
rechecked before writes. Duplicate/conflicting signatures do not overwrite the
first record. Existing events/incident links are not changed. Guarded runtime
orchestration and log-driven grouping remain incomplete; no live provider
acceptance or production recovery is established.
