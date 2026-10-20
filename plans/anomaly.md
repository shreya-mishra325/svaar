# Svaar anomalies and open integration questions

Last reviewed: 2026-10-18 (Asia/Calcutta).

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
- Impact: No listener, outbox sender or polling jobs run. The successful diagnostic
  proves configuration/database access only, not chat availability.
- Next action: Implement the agent/jobs composition, transport shutdown and runtime
  health reporting before enabling the long-running service.
- Owner: Unassigned.

## A-002: External provider contracts remain unverified

- Status: Open; integration blockers, not implemented adapter defects.
- Evidence: PLAN.md sections 6, 9, 10 and 19 identify required smoke checks.
  No provider integration code or live-provider verification was added by scaffolding.
- Impact: Do not assume Caspian message IDs, sender trust, transport mode, delivery
  receipts or available channels. Do not assume Bolna's custom LLM endpoint,
  per-call reference delivery or latency units. Do not assume a common Jev payload,
  batching contract or partial-failure schema. The chat model's native tool behavior
  is also unverified.
- Next action: Record separately dated, redacted results for each provider and its
  selected mode/version before implementing its adapter. Use Telegram only through
  the same planned transport boundary if the Caspian decision gate selects it.
- Owner: Unassigned.

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
- Owner: Unassigned.

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

- Status: Open; provider selected, smoke check not yet run (no keys configured as of
  2026-10-20).
- Decision (2026-10-20): Chat and voice use one OpenAI-compatible adapter.
  - Primary: Groq, `SVAAR_LLM_BASE_URL=https://api.groq.com/openai/v1`,
    `SVAAR_LLM_MODEL=llama-3.3-70b-versatile`. Chosen for low latency on the
    8 second voice turn budget and a free tier without a card.
  - Backup: Google Gemini through its OpenAI-compatible endpoint
    `https://generativelanguage.googleapis.com/v1beta/openai/`, a Flash model.
  - Optional for comparison: OpenRouter free models, Cerebras.
  - Jev is not a chat model and stays separate (A-002); decisions fall back safely
    while it is unconfigured.
- Free-tier limits are from secondary 2026 comparison articles, not provider pages:
  Groq roughly 30 requests per minute on 70B models; Gemini roughly 1,500 requests
  per day on Flash. Free tiers may use submitted data for training, so send only
  demo data. Native tool calling on these models is unverified until the smoke check.
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
- Smoke check to run once keys exist: key accepted, configured model listed, three
  native tool-call requests return the expected tool and arguments, median latency
  recorded in seconds (non-streaming). Record dated, redacted results here.
- Caspian documentation notes (read 2026-10-20, not a live check): hosted mode polls
  `GET /v1/events`, so no public route is needed; messages carry a stable `id`,
  `conversation_id`, `channel` and `sender {address, name}`. The documents do not say
  whether `sender.address` is verified by the platform, so Caspian senders are treated
  as unauthenticated until Caspian confirms it (A-002). Telegram remains the fallback.
- Next action: Configure keys, run the smoke check, record results, then lock the
  chat transport decision for Phase 2.
- Owner: Unassigned.

## Resolved entries

None recorded yet. When resolving an entry, retain its ID, add the resolution date,
relevant files and the specific check or external evidence establishing resolution.
