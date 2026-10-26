# Svaar phase checkpoints

Last reviewed: 2026-10-26 (Asia/Calcutta).

## How to use this checklist

Read rules.md, PLAN.md, this file and anomaly.md before starting work.
The incoming main version of PLAN.md is authoritative per the user's Oct 26
instruction. The working file was verified byte-for-byte identical to it; neither
branch had a different PLAN.md in this merge. Checkpoints record progress and
cannot waive plan requirements. Phase numbers, targets and exit criteria
are unchanged. A target date is not evidence of completion.

Every phase separates three kinds of progress:

- **Implementation:** the stated code or artifact exists for the exact scope shown.
- **Offline verification:** the stated checks passed with isolated state and fake
  providers. This does not establish live account access, calls or delivery.
- **Live acceptance:** the required real integration or final user flow was verified.
  Credentials saved locally are configuration, not live acceptance.

[x] applies only to that specific item. Keep partially implemented items split,
rather than hiding missing software inside a live-provider blocker. Phase complete
requires every mandatory implementation, verification and acceptance item plus the
original exit check. Optional cuts stay unticked with a recorded team decision.
Never infer completion from scaffolding, a mock, a date or a configured key.

Record dated evidence, files, results, integration status and limitations. Preserve
earlier evidence in the history below; its old remaining-work notes are historical.
Agents never stage, commit, push or change Git state. Live messages/calls require
explicit authorization covering the action and target.

## Current position

Latest implementation verification: **586 tests passed on 2026-10-26**, plus
Ruff lint/format and alembic check against the isolated PostgreSQL test database.
The database container is healthy. Both local databases are at revision
0015 with clean drift checks; the merge graph was verified (A-020) and the
latest test-only 0015 -> 0014 -> 0015 round trip passed. Compose validation passed. The existing Starlette warning is A-004.

| Phase | Implementation | Offline verification | Live acceptance |
| --- | --- | --- | --- |
| 0: Foundation | Complete | Passed | Required local startup verified |
| 1: Contracts and safety | Safety core done; provider composition partial | Core and adapter mocks passed | Provider checks incomplete |
| 2: Shared runtime | Chat/gateway/internal voice core done; external voice binding pending | Core and persistence checks passed | Complete chat/voice flow pending |
| 3: Voice transport | Call/challenge/follow-up core and status receipts done; turn bridge pending | Implemented scope passed | Real verification call pending |
| 4: CI and timeline | Ingress, incident grouping/timeline/actions and role-based alerts done; App/log fingerprint/owner mapping pending | Ingress checks passed | Real incident/alert/timeline pending |
| 5: Claims and escalation | Not implemented | Pending | Pending |
| 6: Resolution and confirmation | Deterministic constraints, negotiations and validator routes done; risky CI flow pending | Pending for domain flow | Pending |
| 7: Replay | Isolated operator-supplied simulation implemented | Isolation tests passed | Required simulation demonstration pending |
| 8: Rehearsal | Not started | Full scenario rehearsal pending | Calls, timing and recording pending |
| 9: Submission | Not started | Final review pending | Team submission pending |

Configuration note, 2026-10-24: the user reports adding SVAAR_BOLNA_API_KEY.
The latest saved-file check confirms both the API key and agent ID are present.
Settings validation and BolnaClient construction/cleanup passed without any HTTP
request. No value was displayed. Configuration is ready for explicit adapter
use. Authenticated GET account and agent checks subsequently passed on Oct 24:
wallet positive, capacity available, configured agent processed with a conversation
task. No call was placed; turn delivery remains unverified (A-014).

Voice integration handoff: the user assigned remaining Bolna wiring to a teammate.
The configured tunnel/webhook returned HTTP 401 initially, then HTTP 422 after
configuration changes. Payload validation remains unresolved; do not mark
callback processing, the conversation bridge or real-call acceptance complete.

Next independent build: incident grouping -> ordered timeline -> get_timeline ->
deduplicated owner alert. This needs new software, not just credentials.
In parallel, resolve Bolna account/turn-reference/index delivery before exposing
its authenticated routes. No separate stable sender-ID contract is required for
Caspian under the approved MVP address policy (A-011).

## Phase 0: Engineering foundation

Prerequisite: none.

- [x] Phase complete: required local foundation scope.

### Implementation

- [x] Python package/lock, settings, logging and modular ownership boundaries.
- [x] FastAPI lifecycle, health/readiness and sanitized API errors.
- [x] Synchronous SQLAlchemy sessions, PostgreSQL and Alembic baseline.
- [x] Compose migration flow, unprivileged app image and opt-in gateway diagnostic.
- [x] TurnRunner protocol, infrastructure tests, CI definition and run documentation.

### Offline verification

- [x] Infrastructure tests, lint/format, migrations and Compose configuration passed.
- [x] Mac locked dependency installation and frontend production build verified.

### Live acceptance

- [x] Required local database/container startup and health/readiness verified.
- No external provider acceptance is required for Phase 0. This does not establish
  a running chat listener, deployed production app or remote CI success.

Exit check: local startup, database connectivity, migrations, tests, lint/format
and container configuration work without any provider dependency.

Evidence: historical Oct 18 and Oct 21 checks retained below; later migrations
and runtime work supersede their old scaffold-only limitations.

## Phase 1: Contract checks, identity and action safety

Target: Oct 18 to 19. Prerequisite: Phase 0.

- [ ] Phase complete.

### Implementation

- [x] Scoped organizations/principals, expiring single-use invites and trusted bindings.
- [x] Registry/dispatcher, validated arguments, org/role/channel checks and execution audit.
- [x] Owner-bound atomic confirmations, expiry and durable uncertain execution states.
- [x] Typed standalone Jev adapter, confidence policy, per-question fallback and audit.
- [x] P0 usability/intent schemas and deterministic mission allowlists.
- [x] Implemented feature settings: operator, LLM, Caspian, Bolna adapter and GitHub HMAC.
- [ ] Jev runtime settings/provider composition and remaining voice route credentials.
- [ ] Operator reconciliation path for uncertain external execution (A-006).
- [ ] Close outstanding implementation-design decisions recorded in A-007.

### Offline verification

- [x] Unconfirmed tier-2 actions do not execute; concurrent confirmations run once locally.
- [x] Owner/channel/expiry/role rechecks and invalid-argument cases pass.
- [x] Missing/invalid/unavailable Jev answers fall back independently and are audited.
- [x] Mission limits cannot be expanded by model/intent output.
- [x] Implemented standalone provider contracts have mocked HTTP tests.
- [ ] Full provider composition and real-adapter uncertain-outcome recovery checks.

### Live acceptance

- [x] Caspian Telegram selected; authenticated connection/poll reads passed on Oct 23.
- [x] Caspian sender-address policy explicitly accepted by the user (A-011);
  this is an MVP decision, not proof of immutable usernames.
- [ ] Caspian outbound delivery and full enrollment/read-tool exchange.
- [x] Verify Bolna account access, positive wallet, available concurrency and processed agent.
- [ ] Choose and verify Bolna turn mode and bridge configuration.
- [ ] Verify Bolna call-reference delivery and one explicitly authorized outbound call.
- [ ] Verify the selected Jev model/gateway with a real response; Vercel is selected,
  mock-only work is approved, and no purchase is authorized or implied (A-002).

Exit check: unconfirmed tier-2 tools never execute; concurrent confirmations cannot
create duplicate local execution attempts; authorization is rechecked; invalid or
unavailable Jev responses fall back safely; mission limits are enforced. Required
quality checks pass. Contract blockers: A-002; execution ambiguity: A-006.

## Phase 2: Shared chat and voice agent runtime

Target: Oct 20 to 21. Prerequisites: identity/action gate and selected transport.

- [ ] Phase complete.

### Implementation

- [x] ChannelTransport and Caspian private Telegram adapter under approved MVP policy.
- [x] Durable inbound dedupe, resumable received work and conservative uncertain states.
- [x] Scoped chat/call history and exclusion of invites/codes from later model history.
- [x] Bounded OpenAI-compatible adapter, chat/voice profiles and pre-execution limits.
- [x] Registry-generated tool policy; business tools dispatch through actions.
- [x] Durable outbox with receipts, safe rejection backoff and no blind uncertain retries.
- [x] Internal TurnRunner injection sharing AgentLoop without agent/voice cross-imports.
- [x] Usability/intent gates and deterministic mission checks in the shared voice path.
- [x] Gateway polling, persistent cursor, stream ownership, shutdown and heartbeat health.
- [ ] External authenticated voice call-reference and retry-index mapping (A-013).
- [ ] Voice confirmation ticket delivery and operator recovery tooling (A-006/A-013).
- [ ] Bound/verify remaining synchronous provider handlers for the full voice budget (A-009).

### Offline verification

- [x] Real PostgreSQL enrollment -> whoami -> outbox -> duplicate handling passes.
- [x] Isolation, concurrent workers, durable cursor restart and crash boundaries pass.
- [x] Private-code chat delivery -> fake call -> exact voice verification passes.
- [x] Unusable/ambiguous speech cannot run tools; limits and late inference checks pass.
- [x] Gateway composition, resource cleanup and stale heartbeat checks pass.
- [ ] Full provider-handler and end-to-end voice latency validation.

### Live acceptance

- [x] User-reported Groq native-tool probes passed on Oct 20 and Oct 21.
  Mac median was 0.5919 seconds for the full non-streaming response, not first token.
- [ ] Real private enrollment, whoami and an additional read tool work through chat.
- [ ] A real redelivery produces one effect and verified outbound delivery.
- [ ] A trusted real voice turn reaches the same agent and action gate.
- [ ] Live voice usability/intent routing and complete turn latency pass.

Exit check: invite enrollment, whoami and a read tool work in chat; a resent message
has one effect; unusable/ambiguous speech cannot invoke tools; deadlines and limits
hold. Required quality checks pass. Track A-001 and A-002.

## Phase 3: Mission-bound voice transport

Target: Oct 22 to 23. Prerequisite: shared runner and identity/action boundaries.

- [ ] Phase complete.

### Implementation

- [x] Bolna placement/execution adapter with sanitized errors and provider retries disabled.
- [x] Durable ordinary-call intents, receipt scope checks and uncertain-placement policy.
- [x] Internal mission-bound runner, per-call history and idempotent indexed replies.
- [x] Pending phone challenge, exact-code action, expiry/attempt/cooldown safeguards.
- [x] Private /verify_phone issuance, atomic code outbox and pending verification intent.
- [x] Narrow pending-number exception only for phone_verify; ordinary calls require
  verified phones and verification offers only verify_phone_code.
- [x] Durable private fallback follow-ups, dedupe and honest unroutable fallback (A-016).
- [x] Failed/unanswered status receipts queue one verified private outbox follow-up
  per call, atomically with the receipt; absent/ambiguous routes queue nothing.
- [x] Internal hashed call-reference resolver delegates to the guarded indexed runner.
- [ ] Verify provider delivery of reference/retry identity and implement its authenticated turn route.
- [x] Implement status receipt authentication, direct peer-IP checks and durable dedupe.
- [x] Restricted Cloudflare loopback status listener with scoped edge-header checks.
- [ ] Verify real Cloudflare ingress and implement operator balance alerts.
- [ ] Match failed/no-answer/busy terminal call state to PLAN.md section 10 (A-021).
- [ ] Classify completed transcripts, persist evidence and apply retention policy.
- [ ] Wire account readiness, authorized call scheduling/limits and production placement.
- [ ] Implement transcript retention and voice confirmation-ticket notification delivery.
- [x] Implement a status-only tunnel entry point with operator/docs routes absent.
- [x] User launched the restricted tunnel and configured the hosted status webhook.
- [ ] Teammate handoff: resolve the dashboard sample HTTP 422 and verify accepted
  callback processing against a stored Svaar execution (A-014).

### Offline verification

- [x] Placement acceptance/rejection/unknown outcomes and no duplicate redial pass.
- [x] Receipt IDs, state progression, final closure and stale-progress rejection pass.
- [x] Exact/leading-zero codes, ownership, expiry, attempts, cooldown and concurrency pass.
- [x] Duplicate/conflicting turns, interrupted execution and no secret-history replay pass.
- [x] Private code delivery withholding, transaction rollback and safe downgrade checks pass.
- [x] Failure follow-up routing, dedupe, recipient revocation and missing-route cases pass.
- [x] Status route authentication, peer-IP rejection, concurrent dedupe, replay/reordering
  and transaction rollback tests.
- [ ] Provider turn-route authentication and transcript retention tests.
- [ ] Production call scheduler/readiness and notification timing tests.

### Live acceptance

- [x] Verify Bolna account access/capacity and configured agent processing through GETs.
- [ ] Verify hosted bridge configuration and telephony delivery in an authorized call.
- [ ] Confirm chosen turn mode, call-reference delivery and stable retry identifiers.
- [ ] Explicitly authorized call reaches the intended number and verifies it by code.
- [ ] Spoken request is answered through Svaar; duplicate completed callback applies once.
- [ ] Real timeout/failure produces the intended spoken reply/private follow-up.
- [ ] Verify actual turn latency and restricted ingress.

Exit check: an authorized real call verifies the intended phone; a spoken question
reaches the shared agent; retries do not repeat effects; completed is processed
once. Failed calls cannot create contradictory evidence. Required checks pass.

## Phase 4: CI ingestion and incident timeline

Target: Oct 24 to 25. Prerequisites: scoped identity, chat delivery and incident storage.

- [ ] Phase complete.

### Implementation

- [x] Explicit repository/installation-to-org mapping and operator-only creation route.
- [x] Raw-body HMAC ingress with bounded input, payload validation and delivery-ID dedupe.
- [x] Atomic normalized workflow observations/receipts with stable run-transition keys.
- [x] Append-only observations with source provenance and occurrence timestamps.
- [x] Standalone GitHub App RS256/token adapter and scoped repository/run reads.
- [ ] Compose the App client into runtime with bounded lifecycle/deadlines.
- [x] Standalone failed-workflow log download with credential-isolated storage request
  and bounded in-memory ZIP processing.
- [x] Incident aggregate/linkage and repository/workflow/branch grouping.
- [x] Versioned normalized log-tail signatures and org/repo/workflow/branch fingerprint helper.
- [x] Explicit attempt-bound enrichment with append-only digest/provenance storage
  and provider I/O outside database transactions.
- [ ] Compose enrichment into guarded runtime work and wire log-based grouping
  without rewriting observed history.
- [x] Organization-scoped ordered timeline and get_timeline/list_incidents actions.
- [x] Idempotent opening alerts queued to same-org ops/lead/admin private routes.
- [ ] Explicit repository owner mapping (A-018); live alert delivery remains unverified.
- [ ] Implement the planned operator POST /incidents manual-creation route.
- [ ] Complete the incident pipeline without automatic workflow reruns.

### Offline verification

- [x] Synthetic HMAC, malformed/oversized/ambiguous input and mapped-scope checks pass.
- [x] Duplicate/conflicting/concurrent deliveries and atomic rollback checks pass.
- [x] Unmapped repos/installations are rejected; operator mappings cannot be overwritten.
- [x] PostgreSQL rejects observation updates/deletes; source time survives arrival reordering.
- [x] Mocked App JWT/token/REST contracts, cache refresh/concurrency and org isolation.
- [x] Synthetic workflow-log download, archive limits, credential isolation and
  normalized/scoped signature tests.
- [ ] Live App/log retrieval acceptance.
- [x] Implemented grouping/linkage, occurrence-order and scoped timeline/action tests.
- [ ] Log-tail fingerprint and explicit owner-routing tests.
- [ ] Workflow failure -> one incident -> one owner alert -> chat/voice timeline slice.

### Live acceptance

- [ ] Configure a real GitHub App/webhook secret, installation and explicit repo mapping.
- [ ] One real failed demo workflow creates the intended scoped incident and chat alert.
- [ ] Real redelivery does not repeat the incident/alert.
- [ ] Its ordered timeline is available in chat and on an authorized voice call.

Exit check: a failing demo workflow produces one scoped incident/chat alert and
its ordered timeline is available through chat and voice. Signature, unmapped-repo
and duplicate-delivery tests pass alongside required quality checks.

## Phase 5: Evidence-backed claims and guarded escalation

Target: Oct 26 to 27. Prerequisites: events, outbox and verified voice calls.

- [ ] Phase complete.

Existing mission definitions, decision audit and call/outbox safeguards are reusable
foundations, not implemented claims or escalation.

### Implementation

- [ ] Detect claims and perform deterministic evidence lookup with provenance.
- [x] Incident acknowledgement action is registered through the dispatcher.
- [ ] Implement claim_check/escalation handlers and guarded scheduling.
- [ ] Classify usable final answers and derive status from persisted evidence.
- [ ] Preserve unverified for missing evidence, unusable speech and failed calls.
- [ ] Guarded jobs, row claiming, durable escalation intents and deterministic call limits.
- [ ] Independently validated CI category/adaptive escalation decisions and labelled audit.
- [ ] Use batching only if the actual gateway contract verifies support.

### Offline verification

- [ ] Evidence/claim state transitions and missing-evidence cases pass.
- [ ] Wrong-person, unusable-answer and failed/unanswered-call cases remain unverified.
- [ ] Concurrent escalation produces one intent; one failed job does not stop others.
- [ ] Timing, recipient authorization, call limits and per-question decision audit pass.

### Live acceptance

- [ ] An overdue unacknowledged incident triggers one explicitly authorized call.
- [ ] A real usable answer produces evidence with provenance.
- [ ] Missing/failed calls do not contradict claims; acknowledgement suppresses escalation.

Exit check: an overdue unacknowledged incident triggers one authorized call under
concurrent workers; one job failure does not stop others; missing/failed calls never
contradict claims; deterministic code enforces timing, recipients and call limits.
Required quality checks pass.

## Phase 6: Validated resolution and cross-channel confirmation

Target: Oct 28. Prerequisites: action gate, confirmations, claims and scoped adapters.

- [ ] Phase complete.

The confirmation/action gate remains reusable. Main adds deterministic negotiation
and validation routes; this does not establish the real confirmed CI action flow.

### Implementation

- [x] Request-supplied release-freeze, staffing and deploy/CI constraints (A-019).
- [x] Bounded deterministic revisions, persisted rounds and operator validation routes.
- [ ] Implement the planned standing constraints store or obtain an explicit plan
  change approving request-scoped snapshots (A-019).
- [ ] Wire start_negotiation through the agent with trusted constraints.
- [ ] Confirmation-call domain flow with exact owner/channel/nonce/expiry checks.
- [ ] Gated CI action with durable outcomes and no blind risky retry.
- [ ] Optional: Jira read/create adapter, creation gated as tier 2.
- [ ] Optional: Jev proposal pre-screening outside the critical voice path.

### Offline verification

- [x] Reject invalid proposals and accept a valid revision in offline tests.
- [ ] Domain CI action waits for valid owner confirmation and runs once concurrently.
- [ ] Provider rejection/unknown outcomes require safe reconciliation (A-006).
- [ ] Optional implemented integrations have scoped adapter/action tests.

### Live acceptance

- [ ] Demonstrate rejected proposal -> valid revision -> validator approval.
- [ ] Authorized real CI action waits for cross-channel confirmation.
- [ ] Duplicate confirmation does not repeat the action; provider receipt is checked.

Exit check: validator rejects a proposal and accepts a valid revision; a risky CI
action waits for owner confirmation across verified channels; duplicate confirmation
attempts do not repeat it. Required checks pass. Address A-006.

## Phase 7: Isolated replay and exception draft

Target: Oct 29. Prerequisite: timeline and validator-approved proposal.

- [ ] Phase complete.

### Implementation

- [x] Operator-supplied corrected pipeline scenario replayed in isolated state.
- [x] Pure in-memory replay with persisted explicitly simulated results.
- [x] Replay isolation and simulated-only database constraint implemented.
- [ ] Optional: exception draft export with tier-2 approval.

### Offline verification

- [x] Corrected operator-supplied sequence produces labelled simulation in tests.
- [ ] Connect replay to the validator-approved proposal in the end-to-end flow.
- [x] Replay isolation tests reject observed writes/live provider access for current scope.
- [ ] Optional draft export honors owner confirmation and scope.

### Live acceptance

- [ ] Demonstrate the required isolated replay in the integrated demo.
- No live provider action is required or permitted by replay. Simulation never
  establishes production recovery.

Exit check: corrected sequence produces labelled simulation with no live effects.
Replay cannot establish production recovery. Required quality checks pass.

## Phase 8: Integration rehearsal and demo recording

Target: Oct 30. Prerequisite: required incident, claims, decision and voice loop.

- [ ] Phase complete.

### Implementation

- [ ] Complete the alert/call/timeline/claim/negotiation/replay/confirmed-action demo path.
- [ ] Prepare reproducible demo data, run instructions and recording script.
- [ ] Instrument timing and audit display; record units and optional cuts honestly.

### Offline verification

- [ ] Full scenario rehearsal passes with isolated fixtures/adapters.
- [ ] Integrated duplicate/reordering/provider-failure/deadline checks pass.
- [ ] Required quality checks and observed/simulated separation pass.

### Live acceptance

- [ ] At least five real end-to-end calls with authorized participants.
- [ ] Measure turn latency and time to first audio; verify units and report medians.
- [ ] Rehearse and record a clean complete demonstration under three minutes.
- [ ] Show decision/tool audit and clearly label mocked/simulated behavior.
- [ ] Record team-approved optional cuts and remaining limitations.

Exit check: reproducible recording and evidence-backed metrics exist; required
quality checks pass; no unresolved critical trust-rule failure remains.

## Phase 9: Submission

Target: Oct 31, morning; exact cutoff must be confirmed by the team.

- [ ] Phase complete.

### Implementation

- [ ] Confirm exact cutoff and prepare write-up, recording and run instructions.
- [ ] Reconcile checklist/anomalies with the actual final code.
- [ ] Prepare the team's final repository/secrets/submission review.

### Offline verification

- [ ] Final required checks pass; instructions reproduce the demonstrated build.
- [ ] Team reviews secrets, repository contents and submission-time documents.
- [ ] Recording/write-up accurately distinguish live, mocked and simulated behavior.

### Live acceptance

- [ ] Team submits before the confirmed cutoff.
- [ ] Team records successful submission confirmation.
- Agents do not publish, commit or push on the team's behalf.

Exit check: team has evidence of successful submission before the cutoff.

## Historical evidence through 2026-10-23

The records below preserve earlier results and decisions. They are not the current
checklist: old statements about missing code, ports, migrations or credentials may
have been superseded by later entries and the current phase sections above.

<details>
<summary>Expand dated implementation and verification history</summary>

#### Phase 0: retained dated evidence

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

#### Phase 1: retained dated evidence

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

#### Phase 2: retained dated evidence

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

#### Phase 3: retained dated evidence

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

#### Phase 4: retained dated evidence

Evidence on 2026-10-23 (partial): migrations 0009 and 0010 add outbox notification
dedupe plus repo_mappings, webhook_deliveries and events. HMAC is checked over exact
bounded bytes before JSON parsing; database work is offloaded from the async
handler. Only mapped repository/installation pairs create normalized observations.
Delivery IDs and stable run-transition keys prevent repeated effects. Conflicts
return 409, malformed JSON 400, unsupported events 200/handled=false; unmapped
repositories are rejected/logged without payload data. PostgreSQL blocks updates
and deletes of observed events. Raw sender payloads/transcripts are not stored.

Verification: 396 tests passed (37 new), Ruff lint/format and Compose config passed.
Isolated test DB round trip 0010 -> 0008 -> 0010 and drift checks passed.
Development DB upgraded to 0010 with clean drift check. Existing Starlette warning
remains. No live provider calls, messages, GitHub requests or tunnel were started.

Remaining Phase 4 work: GitHub App client, failure fingerprinting, incident
aggregation/linkage, scoped timeline and get_timeline, owner alerts and live
repository acceptance. See A-017 for schema extensions and the minimal ingress
scope. No automatic workflow reruns exist.

#### Additional dated updates

##### Approved MVP sender policy, 2026-10-23

The user explicitly removed the separate verified stable sender-ID contract
requirement. This supersedes earlier A-011 startup/enrollment blocker statements
in this document. Caspian's authenticated API supplies the private sender address;
the adapter now marks eligible private messages sender_authenticated=true.
Invite enrollment, organization/role checks, confirmation gates, private-message
filtering and generic rejection of unauthenticated transport input remain enforced.
Mutable username changes or reassignment can affect bindings; this is an accepted
MVP limitation, not a verified immutable-ID guarantee. No live gateway, messages
or calls were started for this change. Live channel acceptance remains pending.

##### Phase 2 internal voice runner evidence, 2026-10-23

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

##### Phase 3 internal phone verification evidence, 2026-10-23

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

##### Phase 3 private challenge delivery evidence, 2026-10-23

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

</details>


### Oct 24: GET-only Bolna readiness

Added BolnaClient.readiness and python -m svaar.voice.smoke. The command makes
only GET /user/me and GET /v2/agent/{id}, verifies the configured agent identity,
and prints readiness flags without balances, identities, prompts or credentials.
Live checks passed: wallet positive, concurrency available, agent processed and a
conversation task present. calls_placed=0 and turn_delivery_verified=false.
The current hosted configuration has no ask_svaar bridge or call_ref template.
No hosted configuration was changed. Authenticated turn/status endpoints,
stable retry binding and end-to-end call acceptance remain pending.

Verification: 35 Bolna adapter tests and the full 406-test PostgreSQL suite passed;
Ruff lint/format and alembic check passed. The initial full-suite attempt failed
because PostgreSQL was stopped; starting the existing db service resolved it.
No schema migration or Git mutation was performed.


### Oct 24: authenticated status receipts

Implemented POST /api/v1/voice/status using a separate 32-character minimum
header secret and the three documented Bolna peer IPs. Unknown executions or
mismatched agents are rejected. Payloads are bounded; duplicate JSON keys are
rejected. Migration 0011 stores only receipt metadata, unique execution/status,
and a payload hash. Call locking makes concurrent duplicates atomic with status
updates. Shared lifecycle handling rejects stale progress and cannot reopen a
terminal call. No transcript/extraction is retained and no claim is inferred.

The image disables proxy headers. An arbitrary tunnel cannot satisfy peer-IP
checks; reviewed trusted ingress and real callback delivery remain pending.
No hosted agent mutation, real callback, message or call was performed.
Failure notifications, transcript retention/classification and the authenticated
conversation bridge remain incomplete. This is transport receipt handling only.

Verification: full PostgreSQL suite 417 passed with the existing A-004 warning;
Ruff lint/format, Compose config, migration downgrade/upgrade/check on svaar_test,
and upgrade/check on local svaar passed. Both databases are at 0011.


### Oct 24: failed-call outbox wiring

Application composition injects agent.enqueue_call_failure into voice status
processing without cross-importing agent/voice implementations. A newly applied
no-answer/busy/failed/canceled/stopped/error receipt queues one generic private
follow-up using the existing verified-route and outbox ordinal locks. Duplicate
or stale terminal statuses cannot enqueue another. Completed and balance-low
receipts do not invoke this notifier. No claim, identity or evidence is changed.
An enqueue exception rolls back receipt, call status and outbox together; a false
result means no safe route, so the receipt commits without a notification.
No new schema, dependencies, provider mutations or live sends were needed.

Verification: full suite 430 passed; after adding the final HTTP composition
test, all 35 status/notification tests passed. Ruff lint/format and alembic check
passed. Existing A-004 warning remains. Live callback/outbox delivery, operator
balance alerts, conversation bridge and trusted ingress remain pending.


### Oct 24: internal call-reference boundary

Added ReferencedTurnRunner, which accepts a private placement reference, validates
bounded text and an explicit stable index, resolves only a stored reference hash
with execution/agent receipts, and delegates to the existing guarded TurnRunner.
No asserted phone, organization or principal is accepted. No provider HTTP route,
model-derived index, automatic activation or new schema was added.

Real PostgreSQL integration confirms duplicate reuse, conflicting retry rejection,
identical utterances at new indices and closed-call replay/new-turn restrictions.
Full suite: 451 passed; Ruff lint/format and alembic check passed. A-004 remains.

Bolna function/schema documentation establishes parameters and auth headers, but
does not establish a stable transport retry identifier. Provider delivery of the
private reference and index remains unverified (A-013/A-014). Public HTTPS ingress
and its trusted source-IP handling are still required. This internal boundary is
not a working Bolna bridge and does not complete Phase 3.


### Oct 24: restricted Cloudflare origin implementation

create_status_ingress exposes only POST /api/v1/voice/status, without docs,
health, operator, GitHub or turn routes. It reuses application lifecycle and
outbox composition but skips model initialization. Missing status secret fails
startup. The standard application remains on direct peer-IP checks.

The dedicated listener trusts the local Mac and cloudflared connector, requires
a 127.0.0.1 peer and one CF-Connecting-IP header from the documented Bolna allowlist,
plus the callback secret. Uvicorn must bind 127.0.0.1 with --no-proxy-headers.
Local processes holding the secret are trusted; arbitrary proxies/Workers are
outside this deployment. README contains explicit port 8001 startup instructions.
cloudflared is installed locally. No tunnel was started or hosted agent changed.

Twenty-five synthetic ingress tests passed, covering route isolation, missing
secret, nonlocal peers, malformed/duplicate/spoofed headers and normal-app
separation. Real Cloudflare header delivery and Bolna callbacks remain unverified.

Final verification: 476 tests passed against isolated PostgreSQL; Ruff lint/format
and alembic check passed. Existing A-004 warning remains. No schema change,
live provider request, public tunnel, message, call or Git mutation was made.


### Oct 24: live tunnel attempt and teammate handoff

User-provided evidence: a temporary Cloudflare URL was generated, the hosted
Bolna status webhook and custom secret header were configured, and Send test
returned HTTP 401 initially, then HTTP 422 after configuration changes.
The screenshot showed Svaar's unauthorized envelope for the initial response.
The subsequent 422 is consistent with passing authentication/source checks and
failing payload validation in the implemented handler; its response body and
payload were not inspected, so the exact cause is unverified.

This establishes a user-reported live ingress attempt, not accepted receipt
processing. No successful callback transaction, real call, phone verification,
conversation turn or live outbox delivery was established. No new tests were run
for this documentation-only update; the latest implementation check remains
476 tests passed.

The user asked to stop troubleshooting this wiring and handed it to a teammate
(name unspecified). Remaining handoff:
- Inspect a sanitized dashboard test payload/error to identify the 422 cause.
- Confirm callback execution/agent identity matches a stored Svaar call receipt;
  unknown sample executions deliberately return 404.
- Verify accepted receipt persistence and duplicate delivery behavior live.
- Finish the authenticated conversation bridge with verified private reference
  and stable retry identity, then perform an explicitly authorized end-to-end call.
- Maintain restricted ingress, separate secrets and all existing action gates.

The tunnel URL is temporary; verify it is current before further provider tests.
Secret values are intentionally omitted. Prior implementation-only statements
that no tunnel/hosted configuration had been changed describe agent actions at
that earlier point; this later user configuration supersedes current setup status.
Phase 3 and all unverified live acceptance items remain incomplete.


### Oct 26: main-branch integration and migration collision

Retained the phase-wise tracking layout and both branches' voice, incidents,
negotiation and replay implementations. Main's prior evidence reports 411 tests
for incidents and 436 for negotiation, plus one authorized outbound Bolna call
on Oct 24; these are teammate-recorded historical claims, not reverified live
here. The reported call used Bolna's model and does not establish the Svaar
conversation bridge. The later dashboard 422 and voice handoff remain unresolved.

Main adds repository/workflow/branch incident grouping, scoped timeline/actions,
acknowledgement, same-org ops/lead/admin outbox alerts (A-018), request-scoped
negotiation constraints (A-019), bounded validator-driven rounds and isolated
operator-supplied simulated replay. No log-tail fingerprint, owner rule, GitHub
App client, risky CI adapter or real voice bridge is established by this merge.
Original phase exit checks and incomplete live acceptance remain unchanged.

Migration collision: both branches called a different revision 0011. Main's
0011 -> 0012 -> 0013 chain is preserved; voice receipts now use 0011_voice from
0010. A merge revision 0014 joins 0013 and 0011_voice. A database whose existing
0011 is the old voice-only schema needs a schema-verified version correction
to 0011_voice before upgrade. Never blindly stamp or apply main's 0011 over it.


Merge verification, 2026-10-26: 526 PostgreSQL tests passed with no skips and the
existing A-004 warning. Ruff lint/format and the conflict-marker scan passed.
Test-only migration 0014 -> 0010 -> main-only 0013 -> combined 0014 passed;
both development and test databases have clean drift checks at 0014.
Voice-only database labels were corrected after schema verification (A-020).
No Git staging, commit, push or further pull was performed. The working files
are resolved; the index remains unmerged until the user stages the four files.
No live providers, calls, messages or public tunnel were used during resolution.


### Oct 26: authoritative main-plan reconciliation

User explicitly designated main's plan authoritative. Read-only comparison showed
plans/PLAN.md is identical in HEAD, MERGE_HEAD and the working tree. The divergent
documents were progress/checkpoint records, not a revised product plan. No
requirements file was changed or replaced.

Preserved main's incident aggregation, timeline/actions, private role-based
alerts, deterministic negotiation/validator and isolated replay. Offline items
now reflect the merged 526-test verification without claiming live acceptance.
The checklist retains individual implementation/offline/live sections so an
implemented subset is visible without weakening the original phase exit check.

Outstanding plan gaps remain explicit: GitHub App/log-tail fingerprinting, an
actual repository owner rule (A-018), standing constraints and agent wiring
(A-019), planned manual incident creation, validator-linked replay, claim/evidence
flow, Jev runtime acceptance and the real confirmed CI action. Voice wiring stays
with the teammate. The current transport-only status handler closes failed call
receipts instead of setting failed; full completed-transcript/evidence processing
and balance alerts are missing (A-021). These are incomplete requirements, not
implicit approvals to change the plan.

This reconciliation edited only checkpoints/anomaly documentation. The prior
526-test result remains the latest code verification; no further tests, migration,
provider action or Git mutation were performed for these documentation changes.


### Oct 26: standalone read-only GitHub App adapter

Implemented integrations/github_app.py and optional paired App settings.
for_repository resolves only a same-org repo mapping and that mapping's
installation. JWT lifetime is nine minutes including a 60-second backdated iat;
token caching stops five minutes before expiry. Token exchange scopes to one
repository and Actions/metadata read permissions. Repository and workflow-run
GETs verify returned identities. HTTP is bounded, redirects/proxy inheritance
and retries are disabled, and failures reveal no keys/tokens/provider payloads.
PyJWT[crypto] is the added dependency for RS256; uv.lock was updated.

No startup/gateway/tool composition or new Compose credential forwarding exists.
No real GitHub request, authentication, workflow mutation, call or message was
made. Logs/archive retrieval, normalized log-tail fingerprinting, explicit owner
mapping and end-to-end runtime integration remain pending. Webhook observations
are not rewritten or synthesized from these reads.

Verification: 545 tests passed without skips, including 19 adapter/settings tests;
Ruff lint/format passed. The existing A-004 warning remains. No schema change or
Git mutation was performed. The earlier paused merge still needs user staging
and its manual commit; this task did not finish that Git operation.


### Oct 26: bounded workflow logs and normalized signatures

GithubAppClient.workflow_log_signature verifies a completed failed run before
requesting its documented log archive redirect. Only HTTPS documented Actions
storage hosts are permitted. A separate client sends no App JWT, installation
token, API cookie or API headers to storage. There is one explicit hop, no
automatic redirects/retries, and an 8 MiB streamed download limit.

incidents/fingerprints.py reads only in memory, caps archive entries at 100 and
expanded bytes at 16 MiB, and rejects unsafe paths, links, encrypted/non-text
members, excessive compression and invalid/empty archives. It hashes the final
40 nonempty normalized lines per file (bounded to 64 KiB), removes timestamps,
ANSI formatting, paths and PIDs, and preserves ordinary numbers/error codes.
Only log-tail-v1 digest/file-count metadata returns. A pure helper scopes the
digest by organization, repository, workflow and branch.

Existing incident grouping and observed events are unchanged. These signatures
are not yet persisted or fetched by webhook/gateway jobs. Attempt-specific
provenance and runtime orchestration must be designed before regrouping existing
incidents. No failure category, claim verdict or production recovery is inferred.

Verification: 570 tests passed without skips, including 25 new synthetic archive/
download cases. Ruff lint/format and alembic check passed. No schema change, new
dependency, real GitHub request, call, message or Git mutation occurred. A-004
remains. The paused merge still requires manual staging and commit.


### Oct 26: attempt-bound durable log-signature enrichment

Added explicit integrations.log_enrichment.enrich_event and migration 0015 for
workflow_log_signatures. Signed observed failed runs and their accepted delivery
receipts must match org scope; incomplete/missing workflow scope is refused.
The App adapter verifies the attempt-specific run response against run, attempt,
commit, workflow and branch before requesting that attempt's log archive.
No latest-attempt shortcut is used for persisted provenance.

The network read is outside DB transactions. Mapping scope is rechecked under
lock before storing only digest/fingerprint/version/file-count and source IDs.
A unique attempt/algorithm key plus advisory lock serializes duplicates; changed
hashes return conflict rather than overwrite. PostgreSQL forbids record updates
and deletes. Failed/unavailable logs never fabricate provenance or modify events.

This is an explicit internal operation with fake adapters in tests. No automatic
job, public route, tool registration, live GitHub call or incident regrouping was
added. Runtime work claiming/retries, missing-log policy and log-based grouping
remain pending. Existing observed history and incident membership are unchanged.

Verification: 586 PostgreSQL tests passed without skips; Ruff lint/format and
whitespace checks passed. Migration 0015 round trip and drift checks passed
on svaar_test; local svaar upgrade/check passed. Both databases are at 0015.
No new dependency, live provider request, call, message or Git mutation was made.
The existing A-004 warning remains; the user still needs to complete the paused
Git merge manually.
