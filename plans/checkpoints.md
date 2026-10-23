# Svaar phase checkpoints

Last reviewed: 2026-10-23 (Asia/Calcutta).

## How to use this checklist

Read `rules.md`, `PLAN.md`, this file and `anomaly.md` before starting a task.
PLAN.md defines requirements; this file tracks implementation phase by phase.
Inspect current code and local edits before relying on a checkbox. Include this
reading order in agent tasks; these documents are not automatically loaded.

- `[x]` means implemented and verified for the stated scope, not merely scaffolded.
- `[ ]` means incomplete, unverified or blocked. Reference blockers by anomaly ID.
- Tick individual deliverables as they pass. Tick a phase-complete box only after
  every required deliverable and its exit check pass.
- Optional items follow PLAN.md's cut order. If deferred, leave them unticked and
  record the team's decision; an omission is not implemented work.
- Dates below are plan targets, not evidence of completion. Independent tasks may
  proceed in parallel where dependencies and ownership boundaries permit.
- At phase closure record date, owner if known, changed files, executed checks and
  results, integration status and remaining limitations under that phase.

Current position: Phase 0 is complete for local infrastructure. Phase 1 is in
progress: its local identity, action gate, confirmation and decision-policy work is
verified. Phase 2 has a tested shared agent core and a standalone mocked Jev
adapter. A standalone Caspian Telegram transport and durable chat coordinator/
outbox now exist. Gateway polling/cursor/health composition is wired with fake-provider
coverage; live provider activation and voice composition remain pending. Groq probes on Oct 20 and Oct 21 are
user-reported evidence; Caspian authenticated event access was checked Oct 23.
Phase 1 and Phase 2 remain incomplete; A-011 is an accepted MVP limitation.

## Phase 0: Engineering foundation

- [x] Phase complete: local scaffold and shared infrastructure.
- [x] Python package, dependency lock, settings and structured logging.
- [x] FastAPI lifecycle, health/readiness probes and API error conventions.
- [x] SQLAlchemy sessions, explicit transactions and empty Alembic baseline.
- [x] PostgreSQL persistence, one-shot migrations and unprivileged app image.
- [x] Feature ownership packages, including agent, identity and actions.
- [x] Synchronous voice TurnRunner protocol, without a fake implementation.
- [x] Opt-in gateway service and infrastructure diagnostic, without a fake listener.
- [x] Infrastructure tests, CI definition and development documentation.

Exit check: local startup, database connectivity, migrations, tests, lint/format
and container configuration work without any provider dependency.

Evidence recorded on 2026-10-18: 29 tests passed against real PostgreSQL; Ruff
checks passed; default and gateway-profile Compose validated; updated image built;
gateway diagnostic succeeded; live health and readiness returned 200. Relevant
files: src/svaar/, tests/, migrations/, compose.yaml, Dockerfile, README.md and
.github/workflows/ci.yml. This is historical local evidence, not remote CI or
production verification. Owner: not assigned in this document.

Limits: gateway listener/jobs remain absent and outbox is not running (A-001); operator, policy and
LLM settings are active but other provider settings remain planned (A-003).
The upstream test-client warning remains (A-004).

Mac verification on 2026-10-21: installed pinned uv 0.11.29 and locked Python
dependencies with Python 3.12.15; frontend npm ci and production build passed.
Local development PostgreSQL uses port 5434 and revision 0002. API health/readiness
returned 200. A separate svaar_test database now exists; all 195 tests passed with
no skips against it. Migration drift check, Ruff lint and format checks passed.
A local operator token was generated without displaying it; a fresh application
accepted authentication and rejected an empty create body with 422, while missing
authentication returned 401. No organization or invite was created by that check.
The already-running API must restart to pick up the new token. Credentials remain
private and no provider requests were made. See A-010.

## Phase 1: Contract checks, identity and action safety

Target: Oct 18 to 19. Prerequisite: Phase 0.

- [ ] Phase complete.
- [ ] Verify Caspian auth, inbound mode, stable IDs, sender trust, outbound delivery
  and channels; record the Caspian/Telegram transport decision.
- [ ] Verify Bolna account readiness, turn mode, call-reference delivery and one
  explicitly authorized outbound test call.
- [ ] Select Jev gateway/model and verify its actual request/response contract.
  Vercel selected; versioned-model live acceptance is pending. User approved
  mock-only development after observing that Jev is excluded from free credits.
  No purchase was made by the agent.
- [x] Implement scoped identities, expiring single-use invites and trusted bindings.
- [x] Implement the actions registry/dispatcher, argument validation, role/org/channel
  checks, configured risk tiers and execution audit.
- [x] Implement owner-bound atomic confirmations, expiry, execution authorization
  and an explicit uncertain-provider-outcome policy.
- [ ] Implement typed Jev adapter, confidence policy, fallback and decision audit.
  Policy, per-question fallback, audit and the standalone Vercel adapter have
  offline coverage. Live verification and runtime settings/composition remain
  pending (A-002); mocked success does not complete this deliverable.
- [x] Define P0 intent/usability schemas and deterministic mission-guard interface.
- [ ] Introduce validated feature settings with process-specific credential wiring.
  Operator, invite, confirmation and policy settings are active; provider settings
  arrive with their adapters (A-003).

Exit check: unconfirmed tier-2 tools never execute; concurrent confirmations cannot
create duplicate local execution attempts; authorization is rechecked; invalid or
unavailable Jev responses fall back safely; mission limits are enforced. Required
quality checks pass. Contract blockers: A-002; execution ambiguity: A-006.

Evidence recorded on 2026-10-20 (partial; phase not complete). Owner: not assigned
in this document. Local checks only, not remote CI or provider verification:

- `ruff format --check` and `ruff check` passed; `alembic upgrade head`,
  `alembic check`, downgrade to 0001 and re-upgrade passed against PostgreSQL 16.
- `pytest`: 112 passed against real PostgreSQL (29 existing, 83 new), with the
  A-004 warning still present.
- Exit-check items covered by tests: tier-2 tools create a confirmation and never
  run unconfirmed; four concurrent confirmations execute once; role is rechecked at
  execution; wrong, expired, same-channel, other-owner and "yes" confirmations are
  refused; wrong codes lock at the limit; invalid, missing, duplicate and
  unavailable decision answers fall back per question and are audited; voice
  mission allowlists are enforced.
- Container smoke: `docker compose up --build app` migrated to 0002; operator
  routes created an org and invite with the token and returned 401 without it.
- Changed files: src/svaar/config.py, src/svaar/api/{auth,router}.py,
  src/svaar/identity/, src/svaar/actions/, src/svaar/approvals/,
  src/svaar/decisions/, migrations/env.py, migrations/versions/0002_phase1_foundation.py,
  tests/, compose.yaml, .env.example, README.md.

Remaining: provider contract checks and live Jev acceptance (A-002), provider settings,
phone binding challenge (Phase 3), reconciliation for unknown outcomes (A-006), and
team review of the design choices in A-007.

## Phase 2: Shared chat and voice agent runtime

Target: Oct 20 to 21. Prerequisites: identity/action gate and selected transport.

- [ ] Phase complete.
- [ ] Implement transport protocol and the chosen authenticated chat adapter.
  On 2026-10-21 selection was pending. Superseded on 2026-10-23: user selected
  Caspian hosted Telegram. ChannelTransport and a standalone HTTP adapter are
  implemented with 31 offline tests. The approved MVP policy trusts private sender
  addresses for invite enrollment (A-011); no separate stable-ID contract is
  required. Durable processing and gateway composition exist. Live end-to-end
  channel acceptance remains pending.
- [ ] Implement durable inbound dedupe, retryable failures and thread/call memory.
  ChatRuntime now implements scoped private chat history and durable dedupe with
  received/processing/processed/unknown states. Received work can resume; uncertain
  execution never retries automatically. Call memory and reconciliation tooling
  remain pending. See A-012 for the state/column additions to PLAN.md.
- [x] Verify chat LLM native tool calling; implement the bounded adapter.
  User-reported Groq openai/gpt-oss-20b probe on 2026-10-20: three requests,
  native_tool_calls=true, median full non-streaming response 0.516 seconds.
  On Oct 21 the user supplied a fresh Mac smoke result: three requests, native
  tools true, median full response 0.5919 seconds. Mac Groq setup is restored.
  No first-token or full voice-latency claim is made.
- [ ] Implement chat/voice profiles, pre-execution round/call limits and deadlines.
  Core profiles, limits and absolute inference deadlines are implemented/tested.
  Full synchronous provider-handler latency remains an acceptance item (A-009).
- [x] Generate registry-based tool policy; dispatch every tool through actions.
- [x] Implement durable outbox sending with receipt/failure state.
  Standalone worker tested with fake transports: safe rejection retries/backoff,
  recipient recheck, concurrent claiming, queued receipts and unknown outcomes.
  Live outbound acceptance and gateway worker startup remain pending.
- [ ] Implement and inject TurnRunner without agent/voice implementation imports.
  Internal VoiceRuntime is injected as app.state.voice_turn_runner through
  VoiceAgentExecutor, sharing the existing AgentLoop. Server-owned call context,
  verified-phone rechecks, per-call memory and durable indexed replies are tested.
  Bolna call-reference mapping and live acceptance remain pending (A-013).
- [ ] Integrate transcript usability, intent routing and deterministic mission limits.
  Core gates and mission checks have mocked coverage. Live Jev, call binding and
  transport wiring remain pending; unconfigured voice gates request clarification.
- [ ] Replace gateway refusal with real runtime composition, shutdown and runtime
  health reporting; API readiness is not listener health.
  Composition, durable page cursors, outbox/receipt coordination, SIGTERM/SIGINT
  shutdown and --status heartbeat checks are implemented with fake-provider tests.
  Startup now uses the approved private sender-address policy.
  Live acceptance remains unticked; missing future keys do not block offline work.

Exit check: invite enrollment, whoami and a read tool work in chat; a resent message
has one effect; unusable/ambiguous speech cannot invoke tools; deadlines and limits
hold. Required quality checks pass. Track A-001 and A-002.

Evidence on 2026-10-21: all 195 existing tests passed on Mac with isolated
PostgreSQL, including agent-loop and Jev HTTP/policy/audit scenarios. Shared
implementation: agent/{llm,loop,profiles,prompts,inference,smoke}.py and
decisions/jev.py. Jev uses synthetic HTTP responses only. No provider was called.
Only whoami is registered as a business tool; confirm_action is dispatcher-owned.
At that checkpoint no chat listener, durable inbound/memory/outbox storage or job runtime existed.

Evidence on 2026-10-23: Caspian public OpenAPI fetched successfully (deployed
version 0.1.0); authenticated GET /v1/events returned 200 with an array and the
documented event/data/message envelope. Only field names/counts were printed.
Configured Telegram connection ID/address were missing from the saved .env, so
no connection-specific acceptance is claimed. Public source at commit
718a96d6d04cb76c7ccce942d2532fd4adbfd545 prefers a mutable username for sender
address, so sender_authenticated remains false. No messages were sent.
Implemented: agent/{transport,caspian,caspian_smoke}.py, optional Caspian settings,
gateway-only Compose credentials, offline tests and operator documentation.
Final validation: 226 tests passed against isolated PostgreSQL, Ruff lint/format,
migration drift and gateway-profile Compose checks passed; A-004 remains. Initial
database tests failed while Docker was stopped, then passed after Docker started.
At that adapter checkpoint no schema change or durable runtime was introduced.

Subsequent evidence on 2026-10-23: user authorized continuing available,
provider-independent work. Added agent/{models,runtime,outbox}.py and migration
0003; API composition exposes an optional ChatRuntime without starting a listener.
Fake authenticated enrollment -> whoami -> durable delivery and duplicate handling
are covered through the real dispatcher. Tests cover conversation/org isolation,
locks surviving dispatcher commits, ordered history, invite/nonce exclusion,
post-execution crashes, concurrent sends, recipient revocation, safe rejection
retries/backoff and receipt reconciliation. All 246 tests passed with real isolated
PostgreSQL and fake provider adapters. Ruff lint/format passed. Test DB downgrade
0003 -> 0002 -> 0003 and migration drift check passed; development DB upgraded to
0003 with clean drift check. Database verification used port 5434 explicitly while
the local editor configuration was being updated. No .env values were changed.
The saved connection fields later passed Caspian's read-only smoke: connection
and polling true, identity/outbound false, messages_sent=0. A-011 is now an accepted MVP limitation.
Jev remains mocked; Bolna and incident/claim/negotiation/replay work remain pending.
Phase 2 is not complete: durable polling cursor/worker startup, trusted live sender
identity and voice binding remain required.

Further evidence on 2026-10-23: wired GatewayWorker polling, cursor persistence,
stream ownership, ChatRuntime/outbox/receipt processing and bounded failure backoff.
Added gateway_cursors via migration 0004 for stream position and heartbeat. CLI
--check remains infrastructure-only; --status reports fresh ready/processing vs
not-started/stale/blocked/error/stopped. Opt-in Compose health now uses --status.
Originally normal startup required a separate verified sender-ID contract.
The subsequent user decision below removes that gate; complete channel and
provider configuration is still required. API/voice behavior is unchanged.
All 256 tests passed against isolated PostgreSQL (10 new gateway checks); lint,
format and Compose validation passed. Test migration 0004 -> 0003 -> 0004 and
drift checks passed; development DB is 0004. The A-004 warning remains. No live
gateway process, outbound messages, model requests or calls were started.
Remaining Phase 2 acceptance: live channel flow under the approved address policy,
Bolna call-reference/turn-index mapping, real handler latency and operator recovery.

## Phase 3: Mission-bound voice transport

Target: Oct 22 to 23. Prerequisite: shared runner and identity/action boundaries.

- [ ] Phase complete.
- [ ] Implement outbound call intent/state and authenticated Bolna adapter.
  BolnaClient and an internal CallService now have mocked HTTP/PostgreSQL coverage.
  Placement markers, acceptance receipts and final-status reconciliation exist.
  Live account readiness, authorized call and production caller wiring remain
  pending; this is not an enabled dialer (A-014).
- [ ] Implement only the selected turn route with per-call reference binding.
- [ ] Persist/idempotently reuse replies and deduplicate status callbacks.
- [ ] Implement the narrow phone_verify challenge before ordinary call missions.
  Internal challenge issuance, exact-code tool, pending-number call exception
  and shared-runner verification now have PostgreSQL/fake-provider coverage.
  Private /verify_phone command issuance, durable code delivery and pending call
  preparation are now wired and tested with fake providers. An authorized real
  verification call and authenticated Bolna routes remain pending (A-015).
- [ ] Enforce separate voice credentials, status secret and trustworthy IP checks.
- [ ] Implement fixed timeout/error replies, outbox fallback and transcript retention.
- [ ] Restrict tunnel ingress to implemented external routes; keep operator/docs local.

Exit check: an authorized real call verifies the intended phone; a spoken question
reaches the shared agent; retries do not repeat effects; completed is processed
once. Failed calls cannot create contradictory evidence. Required checks pass.

Evidence on 2026-10-23 (partial, Phase 3 remains incomplete):
Verified public Bolna call, execution and auto-retry documentation. Implemented
voice/{provider,bolna,calls}.py and migration 0006; active optional
SVAAR_BOLNA_API_KEY / SVAAR_BOLNA_AGENT_ID settings are blank in .env.example.
Client construction makes no request. Existing local credentials were not read.

A pending ordinary call must already have server-owned organization, principal,
mission and verified phone binding. Placement rechecks those before committing
placing; concurrent/repeated invocations cannot send another POST for that intent.
High-entropy references are passed in user_data; only their hashes are stored.
Explicit rejection becomes failed; timeout, invalid acceptance, server failure or
unexpected placement error becomes unknown. Interrupted placing requires review.
Provider auto-retries are disabled. No automatic local placement retries exist.

Read-only execution reconciliation validates execution and agent IDs. Stale
progress cannot reopen an answered/final call. call-disconnected blocks turns
while awaiting completion; terminal status closes the call. No claim/evidence
state is derived here. Transcript and extraction payloads are not persisted by
this minimal receipt adapter.

Verification: 321 tests passed (45 new), Ruff lint/format passed, migration drift
check and test-only 0006 -> 0005 -> 0006 round trip passed. The initial migration
test caught an Alembic naming-convention double prefix; corrected with op.f and
the complete suite then passed. Existing A-004 warning remains. Development
migration was not applied. No live authenticated Bolna request, message or call
was made. No new dependency or service was added.

Remaining: account readiness, phone_verify challenge, authenticated turn/status
routes, verified call-reference/turn-index delivery, callback dedupe, notification
outbox and real authorized call. CallService is internal only; no action handler,
API, application lifespan or job starts it. Contract blockers: A-002 and A-014.

## Phase 4: CI ingestion and incident timeline

Target: Oct 24 to 25. Prerequisites: scoped identity, chat delivery and incident storage.

- [ ] Phase complete.
- [ ] Implement GitHub App client and explicit repository-to-organization mapping.
- [ ] Verify raw-body HMAC, validate payloads and deduplicate delivery IDs.
- [ ] Persist append-only observed events with provenance and stable external IDs.
- [ ] Implement failure fingerprints and an ordered incident timeline.
- [ ] Deliver owner alerts through the outbox; do not automatically rerun workflows.

Exit check: a failing demo workflow produces one scoped incident/chat alert and
its ordered timeline is available through chat and voice. Signature, unmapped-repo
and duplicate-delivery tests pass alongside required quality checks.

Evidence: Pending.

## Phase 5: Evidence-backed claims and guarded escalation

Target: Oct 26 to 27. Prerequisites: events, outbox and verified voice calls.

- [ ] Phase complete.
- [ ] Detect claims and perform deterministic evidence lookup with provenance.
- [ ] Implement claim_check/escalation missions and incident acknowledgement.
- [ ] Classify usable final answers; derive status from persisted evidence.
- [ ] Preserve unverified for missing evidence, unusable speech and failed calls.
- [ ] Implement guarded polling, row claiming and durable escalation intent/state.
- [ ] Add independently validated CI category and adaptive escalation decisions.
- [ ] Record per-question audit and evaluate labelled examples; batch only if the
  verified gateway contract supports it.

Exit check: an overdue unacknowledged incident triggers one authorized call under
concurrent workers; one job failure does not stop others; missing/failed calls never
contradict claims; deterministic code enforces timing, recipients and call limits.
Required quality checks pass.

Evidence: Pending.

## Phase 6: Validated resolution and cross-channel confirmation

Target: Oct 28. Prerequisites: action gate, confirmations, claims and scoped adapters.

- [ ] Phase complete.
- [ ] Implement release-freeze, on-call staffing and deploy/CI capacity constraints.
- [ ] Implement bounded proposal/revision rounds and deterministic validation.
- [ ] Implement confirmation calls with exact nonce and owner/channel/expiry checks.
- [ ] Implement a gated CI action with durable outcomes and no blind risky retries.
- [ ] Optional: Jira read/create adapter, with creation gated as tier 2.
- [ ] Optional: Jev proposal pre-screening, outside the critical voice path.

Exit check: validator rejects a proposal and accepts a valid revision; a risky CI
action waits for owner confirmation across verified channels; duplicate confirmation
attempts do not repeat it. Required checks pass. Address A-006.

Evidence: Pending.

## Phase 7: Isolated replay and exception draft

Target: Oct 29. Prerequisite: timeline and validator-approved proposal.

- [ ] Phase complete.
- [ ] Replay one corrected failed-pipeline sequence in isolated state.
- [ ] Use fake/recorded adapters only; results are explicitly simulated.
- [ ] Prove replay cannot write observed events or call GitHub, Jira or Bolna.
- [ ] Optional: export an exception draft with tier-2 approval.

Exit check: corrected sequence produces labelled simulation with no live effects.
Replay cannot establish production recovery. Required quality checks pass.

Evidence: Pending.

## Phase 8: Integration rehearsal and demo recording

Target: Oct 30. Prerequisite: required incident, claims, decision and voice loop.

- [ ] Phase complete.
- [ ] Run the full alert, call, timeline, claim, negotiation, simulated replay and
  confirmed-action demonstration.
- [ ] Complete at least five real end-to-end calls with authorized participants.
- [ ] Verify duplicate/reordered delivery, provider failures and deadlines.
- [ ] Measure turn latency and time to first audio; confirm units and report medians.
- [ ] Rehearse and record a clean demonstration under three minutes.
- [ ] Show decision/tool audit; label all mocked or simulated behavior.
- [ ] Record team-approved optional cuts and remaining limitations honestly.

Exit check: reproducible recording and evidence-backed metrics exist; required
quality checks pass; no unresolved critical trust-rule failure remains.

Evidence: Pending.

## Phase 9: Submission

Target: Oct 31, morning; exact cutoff must be confirmed by the team.

- [ ] Phase complete.
- [ ] Confirm cutoff and prepare write-up, recording and run instructions.
- [ ] Reconcile checklist/anomaly status against actual code and final checks.
- [ ] Team manually reviews secrets, repository contents and submission-time docs.
- [ ] Team submits and records confirmation; agents do not publish or push.

Exit check: team has evidence of successful submission before the cutoff.

Evidence: Pending.

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

### Phase 2 internal voice runner evidence, 2026-10-23

Implemented voice/{models,runtime}.py, agent/voice_runner.py, migration 0005,
TurnRunner contract extension and application lifecycle injection. Agent and voice
implementations do not import each other; application composition joins them.
Ordinary active calls resolve their organization, principal, mission and verified
phone binding from server-owned rows. No call creation/activation endpoint exists.
The pending phone_verify challenge is deliberately not accepted by this runtime.

Stable zero-based turn_index is required for execution. Retries reuse the saved
reply; changed payloads, missing/gapped indices and unknown/closed/unverified calls
are refused. Session advisory locks survive dispatcher commits. Processing/unknown
turns never replay after a crash; unknown turns block later work pending review.
History is scoped to the call and bounded to six completed turns, with codes and
unusable speech excluded from later input history.

Verification: 276 tests passed against isolated PostgreSQL (20 new voice tests);
Ruff lint and formatting passed. Migration drift and test-only 0005 -> 0004 ->
0005 round trip passed. Existing Starlette warning remains. Docker Desktop and
the project database were started for verification. Current Compose published
port is 5433; process-local test configuration used that actual port. No .env
values were edited. Development database migration 0005 was not applied.

Still pending: Bolna authentication/reference/index delivery, phone challenge,
provider callbacks, chat notification delivery for fallback/confirmation, real
handler latency and live chat/voice acceptance. The inherited fixed fallback
mentions messaging, but this internal runner does not yet enqueue such a message.
No provider requests, messages or calls were made. Phase 2 remains incomplete.

### Phase 3 internal phone verification evidence, 2026-10-23

Implemented identity/{phones,phone_tools}.py and PhoneChallenge storage, registered
verify_phone_code through actions, added a server-resolved challenge identifier
to ToolContext, and extended internal call placement/runtime for phone_verify.
Migration 0007 enforces mutually exclusive contexts: ordinary calls require a
verified-binding reference; verification calls require a challenge and no binding.

Issuance is internal and requires an existing verified non-phone identity.
Codes are six ASCII digits, stored only as salted scrypt hashes, with ten-minute
expiry, three mismatch attempts and one-minute resend cooldown per principal and
target. New challenges cancel prior pending challenges for that principal.
Pending numbers do not create or reserve a globally owned phone binding.
Exact matching creates/verifies only the intended principal's phone binding.
Model proposals cannot replace the raw caller transcript or select the challenge.

Only phone_verify can dial the pending number; its sole offered tool is
verify_phone_code. Ordinary missions still require verified phones. Usability and
intent gates remain enforced. The internal call closes on verification/lockout;
saved indexed replies remain reusable without repeating tools. Verification
utterances and replies are not replayed as later model history.

Verification: 344 tests passed (23 new), with real isolated PostgreSQL and fake
models/providers; Ruff lint/format and test-only 0007 -> 0006 -> 0007 migration
round trip/drift checks passed. Existing Starlette warning remains. Development
migrations were not applied. No new dependencies, .env edits, live provider
requests, messages or calls. Prior ordinary-call-only notes are historical and
superseded for this narrow verification exception.

Remaining: private chat code delivery and issuance wiring, authenticated provider
turn/status routes, verified call-reference/turn-index delivery, callback dedupe,
fallback notifications and authorized live acceptance. No Bolna route or tunnel
was added based on assumed payload fields. Phase 3 remains incomplete.

### Phase 3 private challenge delivery evidence, 2026-10-23

Added the private identity-enrollment command /verify_phone <E.164 number> to
ChatRuntime, alongside /join. It requires transport-authenticated enrollment,
bypasses inference/history and creates the challenge, pending verification call,
secret outbox message and processed inbound marker in one transaction.
Duplicate messages do not reissue codes. Invalid input/cooldown failures produce
safe durable replies without creating extra challenges or call intents.

Agent receives an injected preparation callback; it never imports voice.
Application and gateway composition supply the callback. It creates only a pending
call intent, never a provider request or automatic dial. Replies explicitly say
the call must be started separately and the phone remains unverified.

Migration 0008 links code outbox entries to their challenges. Sender rechecks
recipient ownership and active challenge immediately before POST. Expired,
canceled, locked, verified or superseded code deliveries are withheld. The salted
hash remains in identity storage; the delivery code exists in the private outbox
only, never conversation history or model requests. Unknown sends never retry.
Downgrade refuses unresolved code deliveries rather than dropping their guards.

Verification: 359 tests passed (15 new chat/phone integration tests), Ruff
lint/format passed, test-only 0008 -> 0007 -> 0008 round trip and drift checks
passed. Tests cover enrollment -> code outbox -> fake call placement/receipt ->
shared-loop exact voice verification, duplicates, rollback, invalid/untrusted
input, cooldown, stale-code withholding and downgrade refusal. The existing
Starlette warning remains. Development database was upgraded through 0008 with
a clean migration drift check, superseding earlier unapplied-migration notes.
Actual Compose host port remains 5433; no .env values were edited.

No live messages, calls, provider requests, gateway process or tunnel were started.
Remaining: authenticated Bolna turn/status routes and call-reference/index contract,
callback dedupe, call scheduling/readiness, live Jev or approved voice-gate design,
fallback/confirmation notifications and explicitly authorized real acceptance.
Phase 3 remains incomplete.
