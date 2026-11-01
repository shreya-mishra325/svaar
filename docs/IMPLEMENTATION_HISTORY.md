# Svaar implementation history

Earlier notes below describe the scope when each feature was introduced. Their
pending-work statements are historical; use the deployment guide and latest
checkpoints for current implementation and live acceptance.

### Internal shared voice runner

Application composition exposes app.state.voice_turn_runner when the LLM is
configured. VoiceRuntime owns persistence and calls the injected VoiceAgentExecutor;
agent and voice implementations never import each other. Both chat and voice use
the same AgentLoop, registry and action gates. No Bolna route or real call is enabled.

Migration 0005 adds ordinary voice_calls and voice_turns. Internal calls must be
active and tied to the intended organization, principal and still-verified phone
binding. The internal phone_verify challenge exception is described below; live code delivery remains pending.
The runtime accepts a server-resolved internal call ID, text and stable zero-based
turn_index. Missing/gapped indices or changed duplicate payloads refuse execution;
completed retries reuse their saved reply. Text alone is never a retry key.
A per-call advisory lock survives action commits. Processing/unknown outcomes
require review and never repeat tools automatically.

History is isolated per call and limited to six previous turns; confirmation
inputs and unusable speech are excluded from later user history. Existing voice
usability, intent, mission and timeout behavior runs through the shared agent.
The runner is tested with real PostgreSQL and fake providers. Before live use,
verify Bolna authentication, call-reference mapping and stable turn indices, add
the phone challenge and wire fallback/confirmation notifications. The inherited
fallback mentions messaging, but notification delivery is not implemented here.
See plans/anomaly.md A-013. Run alembic upgrade head before using the new schema.

### Bolna outbound adapter and internal call lifecycle

BolnaClient implements documented call placement and execution lookup using
existing synchronous httpx. Optional SVAAR_BOLNA_API_KEY and
SVAAR_BOLNA_AGENT_ID settings are required by explicit from_settings construction.
No client, call service, call job or network request starts automatically; these
credentials are not yet forwarded by Compose. No provider SDK is required.

CallService works on an existing server-owned pending ordinary call. Before
placement it checks organization, principal and verified phone ownership. It
commits placing before the single POST, stores only a hash of the generated
private call reference, and records queued acceptance with the execution ID.
Queued is not proof of an answered call. Explicit rejection is failed; ambiguous
placement is unknown. Neither state is automatically redialed. A crash leaving
placing requires review. Provider auto-retries are explicitly disabled.

Execution reads validate the receipt's execution and agent IDs. Progress cannot
regress or reopen a final call. call-disconnected blocks further turns while
waiting for the final result; completed and hard-failure terminal statuses close
the call. These statuses do not establish or contradict an incident claim.
This adapter does not persist transcripts or provider extraction payloads.

Migration 0006 adds placement/receipt state. Apply migrations before internal use;
development migrations were not applied by these checks. Downgrade requires new
placement states to be reconciled rather than resetting them to pending.
Phone verification, account readiness, authenticated turn/status routes,
call-reference/turn-index delivery and fallback notification delivery remain
pending. No production entrypoint invokes CallService; future business callers
must retain action authorization and mission-specific scheduling/limits.

Contracts checked on 2026-10-23:
[call placement](https://www.bolna.ai/docs/api-reference/calls/make),
[execution lookup](https://www.bolna.ai/docs/api-reference/executions/get_execution)
and [provider retry configuration](https://www.bolna.ai/docs/outbound/auto-retry).
Tests use synthetic HTTP and fake providers; no live Bolna call is claimed.

### Internal phone verification challenge

Phone challenges are owned by identity. Internal issuance requires an enrolled
principal with a verified non-phone channel and returns a six-digit code once
for private chat delivery. Only a salted scrypt hash is stored. Challenges expire
after ten minutes, lock after three failed comparisons and enforce a one-minute
resend cooldown per principal and target. Reissue cancels prior pending challenges.
Pending numbers do not create or reserve phone bindings.

Migration 0007 adds phone_challenges and an explicit pending-challenge call
context. create_phone_verification_call creates only an internal intent, without
dialing. CallService may dial that exact pending number only for phone_verify.
Ordinary missions still require a verified phone binding. Verification calls offer
only verify_phone_code through the shared actions dispatcher and usability/intent
gates. The challenge comes from trusted context; the code comparison uses the
caller transcript, never a model-reconstructed code. Six ASCII digits must match
exactly after removing spaces/hyphens; number words are not guessed.

A successful comparison creates/verifies only that principal's number. The runner
closes finished verification calls and returns saved replies on indexed retries.
Verification text and replies never enter later model history. Core behavior is
tested with fake inference/providers and real PostgreSQL.

The live flow is still incomplete: no chat issuance command/private code delivery,
provider turn/status endpoint or real verification call is enabled. Bolna reference
and retry-index delivery must be verified before exposing a route. No code is sent
or call placed automatically. Without a configured classifier, voice gates continue to request clarification.
See plans/anomaly.md A-015; development migrations still need applying.

### Request phone verification in private chat

After invite enrollment, the private command is:

```text
/verify_phone +<your E.164 number>
```

The configured gateway handles this identity-enrollment command without calling
the model. Challenge creation, pending call intent, private code outbox and inbound
dedupe commit together. The six-digit code is delivered through the existing
outbox, with expiry/supersession and recipient checks before sending. Codes and
phone-registration commands never enter conversation history or model prompts.
Identity stores a salted code hash; the private delivery outbox holds the code
needed for delivery. Unknown sends are not blindly retried.

The reply explicitly states that the verification call must be started separately.
This prepares a pending intent; it does not enable a dialer, verify the phone,
place a real call or claim a code was delivered before its receipt. Application
and gateway composition inject call preparation without imports between agent
and voice implementations.

An offline integration test covers enrollment, private code delivery, fake Bolna
placement/status and exact spoken-code verification through the shared action
gate. No live messaging or calling was performed. Authenticated Bolna routes,
verified reference/index delivery and authorized real acceptance remain pending.

Development database is migrated through 0008; the isolated test DB passed its
migration round trip/drift checks. This supersedes earlier unapplied-migration
notes. Restart running application/gateway processes to load the new code.
Migration downgrade refuses unresolved private-code deliveries.

### Voice failure follow-ups

Application composition injects enqueue_voice_fallback into the voice runner.
Unavailable/tool-limited turns and unexpected failures queue one generic private
chat follow-up per call/turn through the existing outbox. Processing/unknown
retries can queue the notification without repeating tools. Notifications contain
no caller transcript, phone or secret code.

Routing requires exactly one existing scoped conversation with a verified binding.
Missing/ambiguous routes or notification failure produce a spoken request to
continue in chat. A queued follow-up is described as queued, never delivered.
Recipient verification, bounded safe rejection retries and uncertain-send handling
remain enforced by OutboxSender. Confirmation-ticket delivery and real voice
latency/acceptance remain pending.

### GitHub workflow ingress

Implemented endpoints:

| Endpoint | Authentication | Behavior |
| --- | --- | --- |
| POST /api/v1/repo-mappings | Operator token | Bind numeric repository and installation IDs to an existing org; overwrites refused |
| POST /api/v1/webhooks/github | Raw-body HMAC | Persist validated, explicitly mapped workflow_run observations |

Set SVAAR_GITHUB_WEBHOOK_SECRET locally to a high-entropy value of at least
32 characters. It is optional and forwarded only to the app container; absent
configuration returns 503. GitHub App credentials are separate and its outbound
REST client is not implemented. No token or new provider account is needed to
run the synthetic tests.

The handler verifies the exact request bytes before JSON parsing and caps bodies
at 1 MiB. It rejects invalid signatures, ambiguous JSON and inconsistent typed
workflow states. Mapped repository and installation IDs are required; sender names
never establish scope. Synchronous database work runs off the async request loop.

Malformed JSON returns 400, unsupported events return 200 with handled=false,
unmapped repositories return 404, and conflicting delivery reuse returns 409.
Delivery IDs and stable run-transition keys dedupe separately. Normalized
observations and receipt metadata commit atomically. Events retain source delivery
provenance and occurrence time; raw webhook bodies and sender personal fields are
not persisted. PostgreSQL rejects updates/deletes to events.

Migrations 0009/0010 add notification dedupe and GitHub observations/receipts.
Development DB is at 0010 with clean drift checks. Tests use an isolated database
and synthetic HMAC requests, with no live GitHub, Bolna or Caspian calls/messages.

Incident grouping, fingerprints, incident-scoped timeline/get_timeline and owner
alerts remain pending. Current facts are org/repository scoped, before incident
association. No CI action or automatic rerun exists. No tunnel is configured; any
future tunnel must expose only the implemented webhook path, keeping operator
routes and docs private.

Contracts:
[signature validation](https://docs.github.com/en/webhooks/using-webhooks/validating-webhook-deliveries),
[workflow_run payloads](https://docs.github.com/en/webhooks/webhook-events-and-payloads#workflow_run)
and [delivery handling](https://docs.github.com/en/webhooks/using-webhooks/best-practices-for-using-webhooks).


### Read-only Bolna account readiness

After saving SVAAR_BOLNA_API_KEY and SVAAR_BOLNA_AGENT_ID locally, run:

```sh
uv run --locked python -m svaar.voice.smoke
```

This makes two authenticated GET requests to Bolna's account and configured-agent
endpoints. It prints only readiness flags, never balances, prompts or credentials.
A successful exit requires positive credit, available concurrency, a processed
agent and a conversation task. It places no calls and changes no configuration.
The account/agent checks passed on October 24, 2026. Turn delivery remains
unverified: this command cannot establish a working Svaar bridge, webhook,
telephone connection or end-to-end voice flow.


### Bolna status receipt endpoint

POST /api/v1/voice/status is implemented for minimal execution lifecycle receipts.
Set a separate random SVAAR_VOICE_STATUS_SECRET of at least 32 characters locally.
Blank disables ingress with 503. In Bolna's webhook configuration, the custom
X-Svaar-Voice-Status-Secret header must match this value. No hosted configuration
has been changed automatically.

The endpoint also requires the actual peer to be one of Bolna's documented IPs:
13.203.39.153, 13.126.9.249 or 13.202.133.53. Run Uvicorn with
--no-proxy-headers, as the image does. Forwarded headers are ignored by the handler.
The normal app rejects tunneled peers. For local Cloudflare delivery, use only
the dedicated restricted listener described below.

Only an execution already recorded on a Svaar call, with a matching provider
agent, is accepted. Migration 0011 adds atomic execution/status dedupe metadata.
Stale progress and later callbacks cannot reopen a terminal call. Unknown status
labels are recorded and ignored. Request bodies are bounded to 1 MiB; transcripts
and extractions are discarded, not logged or retained.

This endpoint records transport closure only. Completed-call classification,
claim/evidence updates, operator balance alerts, transcript retention and the
authenticated conversation-turn bridge remain pending. No real callback
delivery or telephone call has been verified.

Contract: https://www.bolna.ai/docs/post-call/polling-call-status-webhooks


### Failed-call private follow-ups

Authenticated no-answer, busy, failed, canceled, stopped and error receipts now
queue one generic private chat notification per call through the existing outbox.
The callback and notification commit together; enqueue exceptions roll back both
for safe provider redelivery. A missing or ambiguous verified private conversation
queues nothing. Outbox delivery still rechecks the recipient binding.

This does not send directly, verify a phone, infer claim status or redial.
Completed calls and balance-low do not use this failure notifier. Operator
balance alerts remain pending. Real callback and notification delivery are still
unverified; offline tests use synthetic provider data and isolated PostgreSQL.


### Internal voice reference resolution

ReferencedTurnRunner resolves a private placement reference by its stored hash,
requires provider execution/agent receipts and delegates to the existing guarded
runner. The authenticated transport must supply a stable zero-based turn index.
The resolver accepts no asserted caller, organization or mission.

This is an internal boundary, not an exposed Bolna endpoint. The provider's
delivery of the reference and retry identity remains unverified. Do not substitute
model-generated counters or utterance hashes for transport retry identifiers.
A public HTTPS ingress and verified proxy/IP handling are also still pending.


### Local Cloudflare status tunnel

The dedicated create_status_ingress factory exposes only the exact POST
/api/v1/voice/status route. It has no docs, health, operator, GitHub or turn routes
and starts no model runtime. It reuses the same database, callback processing and
outbox composition; this is a restricted entry point for the modular monolith,
not a new independently deployed business service.

Prerequisites: cloudflared installed, local database migrated, and a separate
SVAAR_VOICE_STATUS_SECRET saved locally. The factory refuses startup without it.
From the project directory, run in terminal 1:

```sh
uv run --locked uvicorn svaar.app:create_status_ingress --factory --host 127.0.0.1 --port 8001 --no-access-log --no-proxy-headers
```

In terminal 2, when ready to expose that restricted listener:

```sh
cloudflared tunnel --url http://127.0.0.1:8001
```

Keep both terminals running. The printed HTTPS URL is temporary. Do not point
this tunnel at the main app on port 8000. Do not enable proxy headers or bind the
restricted listener to 0.0.0.0. Stop either process with Ctrl+C when finished.
No automatic tunnel launch or provider configuration is part of application startup.

This listener trusts the local Mac and its cloudflared process. It accepts only
a direct 127.0.0.1 peer, exactly one CF-Connecting-IP header matching a documented
Bolna IP, and the independent callback secret. It ignores X-Forwarded-For.
A local process that knows the secret can impersonate the connector: local host
trust is explicit. Do not insert other proxies or Workers into this setup.
The standard application continues to ignore Cloudflare client-IP headers.

Cloudflare documents CF-Connecting-IP as the client address delivered to the
origin. This trust applies only to traffic delivered by your local cloudflared
connector, not arbitrary headers on public/direct requests:
https://developers.cloudflare.com/fundamentals/reference/http-headers/

Once the tunnel runs, the intended Bolna webhook URL is:
https://YOUR-TUNNEL-HOST/api/v1/voice/status
Its custom X-Svaar-Voice-Status-Secret header must match the saved local secret.
Configure the hosted agent manually only when ready. A browser request cannot
test acceptance because its source is not a Bolna IP. Unknown executions, including
dashboard samples without a stored Svaar call receipt, deliberately return 404.
Public delivery and real source-header behavior remain unverified until tested.
The conversation-turn bridge remains separate and incomplete.


### Standalone read-only GitHub App adapter

Phase 4 now has GithubAppClient.for_repository(session, settings, org_id,
repository_id). It requires an explicit same-org repo_mappings entry and uses
that entry's installation ID, with no deployment-wide installation fallback.

Optional SVAAR_GITHUB_APP_ID and SVAAR_GITHUB_PRIVATE_KEY_B64 must be configured
together. The key is base64-encoded unencrypted PEM RSA, at least 2048 bits.
It is separate from the existing GitHub webhook HMAC secret. Leave both blank
until the team provisions an App; no credentials are needed for mocked tests.

PyJWT with cryptography support signs a nine-minute RS256 JWT, including the
documented clock-skew allowance. Token exchange requests only the selected
repository and Actions/metadata read permissions. The client caches the token
until five minutes before expiry, serializes concurrent refreshes and bounds HTTP
timeouts and response size. It follows no redirects, inherits no HTTP proxies,
performs no automatic retries and exposes sanitized errors.

repository_name and workflow_run perform reads and verify response IDs. They do
not create observed events, infer recovery or execute business tools. No workflow
rerun, dispatch or cancel is exposed. Client construction makes no requests.
Callers must close the client. The adapter remains standalone: it is not wired
into startup, the gateway or model tools; App secrets are not newly forwarded
through Compose. Runtime lifecycle/deadline composition remains future work.

Verified scope: official contracts and mocked HTTP with synthetic RSA keys.
No live authentication or installation provisioning was attempted. Workflow
logs/archive retrieval and normalized log-tail fingerprinting remain pending.

References:
https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/generating-a-json-web-token-jwt-for-a-github-app
https://docs.github.com/en/rest/apps/apps#create-an-installation-access-token-for-an-app
https://docs.github.com/en/rest/actions/workflow-runs#get-a-workflow-run


### Workflow-log signatures (standalone)

GithubAppClient.workflow_log_signature(run_id) now verifies a completed failed
run, requests GitHub's short-lived log redirect, and downloads the ZIP using a
separate credential-free client. Accepted storage locations are HTTPS on
results-receiver.actions.githubusercontent.com or an Azure blob storage account
host matching the documented blob.core.windows.net family. Arbitrary hosts,
userinfo, nonstandard ports and further redirects are rejected. API credentials,
headers and cookies are not forwarded.

The 8 MiB archive is processed in memory with 100-member/16 MiB expanded limits.
Unsafe paths, links, encrypted or non-text files, excessive compression and empty
or invalid logs are rejected. No archive is extracted to disk. The signature
hashes versioned normalized file tails, not raw log text or filenames.
Ordinary numeric error codes remain meaningful; timestamps, paths, PIDs and ANSI
formatting are normalized. Only digest and file-count metadata return.

The scoped failure_fingerprint helper includes org, repository, workflow and
branch. It does not change current incident grouping, create observed evidence
or infer recovery. Runtime composition, run-attempt provenance, durable signature
storage and grouping integration are pending. Missing logs produce an explicit
failure rather than a fabricated empty fingerprint. No live download was tested.

Contracts:
https://docs.github.com/en/rest/actions/workflow-runs#download-workflow-run-logs
https://docs.github.com/en/actions/reference/runners/github-hosted-runners


### Attempt-bound log provenance

The explicit internal integrations.log_enrichment.enrich_event operation reads
one same-org signed failed-workflow observation, verifies an App response against
its run ID, attempt, commit SHA, workflow ID and branch, and downloads that
attempt's logs. Provider I/O occurs after the read transaction has closed.
There is no automatic startup, webhook, gateway, job or model-tool invocation.

Migration 0015 adds workflow_log_signatures: only digests, scoped fingerprint,
algorithm, file count, observation reference and run/installation metadata are
stored. A unique per-org/repository/run/attempt/algorithm key and advisory lock
serialize writes. Matching reprocessing returns duplicate. A changed digest
returns conflict and preserves the original; raw logs and signed URLs are not
stored. PostgreSQL blocks updates and deletes of signature records.

The repository mapping is rechecked before commit; changed or missing mappings
cannot receive a record. Unavailable or invalid logs create no signature.
Unsupported/successful/incomplete observations are refused before provider I/O.
This is enrichment metadata, not a claim verdict or production recovery signal.
Existing incident membership and broad workflow grouping remain unchanged until
runtime enrichment and log-based grouping are wired together.


### Explicit repository and incident ownership

POST /api/v1/repo-mappings accepts an optional owner_principal_id. It must name
an existing principal in the mapping's organization. Roles are not used to guess
an owner; a developer can own a repository.

An operator can configure an existing mapping through:
PUT /api/v1/repo-mappings/{repository_id}/owner

```json
{
  "org_id": "<organization UUID>",
  "owner_principal_id": "<principal UUID>",
  "assign_unowned_incidents": false
}
```

This operator-only route changes the default for future incidents. Each newly
opened incident snapshots the configured same-org owner. Mapping changes do not
transfer already-owned incidents. To assign the selected owner to existing open
unowned incidents explicitly, set assign_unowned_incidents=true. Assigned,
acknowledged and resolved incidents are untouched. Owner assignment and its
idempotent outbox alert commit together; repeats cannot queue another alert.

Alerts target only the incident owner through the existing verified private route.
Missing owners or missing/ambiguous private routes queue nothing; there is no
role-based broadcast fallback. Acknowledgement records the acknowledging caller
and does not transfer ownership. Timeline/tool summaries expose the owner ID.
No call or escalation is started by this configuration.

Migration 0016 adds nullable owner references without guessing existing owners.
Its downgrade refuses to discard configured ownership. Explicit reassignment of
an already-owned incident and general transfer/audit tooling are not implemented.
Claims and guarded escalation remain subsequent work. Live owner configuration,
chat delivery and calls have not been verified by these synthetic tests.


### Claims and deterministic workflow evidence

The initial claims core registers record_claim and check_claim as tier-1 chat
tools, and list_claims as a chat/voice read tool subject to mission gates.
All calls pass through actions. Author and organization come from trusted caller
context; source correlation deduplicates one claim per author/message. AgentLoop
replaces model-proposed statement text with the original caller message.
Source/content conflicts do not overwrite the original assertion.

Supported structured claim kinds are workflow_succeeded (exact run/attempt,
optional commit SHA) and fix_merged. A positive workflow assertion such as
"The build passed." can become confirmed only from matching completed-success
observations linked to that incident and accepted signed-delivery receipts.
Any run number present in the supported statement must match the target.
The matcher deliberately accepts only a narrow positive assertion grammar;
questions, negatives, compound/unrecognized wording and model-kind mismatches
stay unverified. A model's selected label alone never establishes truth.

Evidence is stored separately with event provenance, stance and rule version,
deduplicated per claim/event and protected by a PostgreSQL append-only trigger.
Missing facts and observed failed workflows produce no contradictory evidence.
Successful CI never proves a fix was merged: merge claims remain unverified
until merge-event or verified call-answer evidence is implemented. Current rules
do not generate contradicting evidence. Mixed future evidence defers to unverified.

GET /api/v1/incidents/{incident_id}/claims is an operator-authenticated read-only
view. It returns assertions, statuses and evidence references; GET does not refresh
statuses or call a provider. check_claim explicitly refreshes after new evidence.
Migration 0017 adds claims/evidence and refuses downgrade while claims exist.

This is a scoped core, not the complete claim workflow. Dedicated automatic
claim detection, merge-event ingestion, record_claim_answer, completed-call
classification/retention, verification authorization and guarded escalation jobs
remain pending. No claim operation places a call, mutates CI or infers recovery.

### Guarded escalation preparation

Migration 0018 adds durable escalation jobs and an incident binding on call intents.
The optional gateway worker prepares at most one pending escalation intent per
open incident with an explicit owner, a confirmed delivered owner alert and exactly
one verified phone. The acknowledgement grace begins at the outbox's confirmed
delivery time. Queued or unknown delivery cannot start it. Acknowledgement before
preparation cancels the job; missing phones defer it. Recipient cooldown and row
claiming prevent concurrent duplicate preparation. Individual preparation failures
roll back independently and retry after 60 seconds.

Set SVAAR_ESCALATION_JOBS_ENABLED=true locally and restart the gateway to enable
preparation after applying migrations. Defaults remain disabled. This worker has
no provider client and never dials. Prepared incident-bound escalation intents are
refused by the default CallService unless a composition-supplied authorization
guard exists. Live placement, readiness, final incident/recipient checks at dispatch,
delivery acceptance and reconciliation still need the voice integration milestone.
Bound voice tools cannot select another incident. Preparation does not classify
call answers, refresh claims or establish any observed evidence.

### Non-voice implementation update, 2026-10-28

Standing release/staffing/capacity constraints now have an operator-only,
revision-checked store. The agent can negotiate against trusted rules, export
tracked JSON drafts, request isolated replay of a proposed scenario, and request
tier-2 draft approval. Policy changes require a new negotiation. Draft approval
does not waive constraints or execute a deployment.

Optional leased CI work composes the existing read-only App/log adapter with
log-based incident grouping and atomic owner-outbox alerts. A separate process
in the same application/image keeps slow log reads out of chat polling.
list_ci_runs/explain_ci_failure expose scoped accepted observations and hash
provenance, with root cause/category explicitly unknown.

Confirmed rerun/cancel use a separate default-disabled writer. Its durable,
attempt-level intent prevents duplicate effects across confirmations and retains
accepted/rejected/uncertain outcomes. Ordinary log/read tokens stay read-only.
No workflow dispatch tool or automatic workflow rerun is implemented.

| Setting | Default |
| --- | --- |
| SVAAR_GITHUB_ENRICHMENT_ENABLED | false; enabled API defers grouping to CI jobs |
| SVAAR_CI_BATCH_SIZE | 5; between 1 and 20 |
| SVAAR_CI_POLL_SECONDS | 5; between 1 and 60 |
| SVAAR_GITHUB_ACTIONS_ENABLED | false; explicit opt-in for confirmed rerun/cancel |

Apply migrations through 0021 before using these features. Configuration alone
does not establish live access. See [the non-voice rehearsal guide](NONVOICE_REHEARSAL.md)
for the offline test command, operator routes, opt-in setup and remaining work.
This update supersedes earlier standalone-only log/policy notes; their dated test
counts remain historical. PLAN.md/CEREBRO_CONTEXT.md and the private .env are unchanged.


### Claim verification calls

A lead or admin can ask Svaar in chat to verify an unverified claim. verify_claim
rechecks recorded evidence and prepares one pending claim_check call to the claim's
author; it needs owner confirmation when the author is not the incident owner. Nothing
is dialed automatically. During that call the only tool is record_claim_answer, which
stores the caller's exact words.

Set SVAAR_CLAIM_CHECK_JOBS_ENABLED=true and restart the gateway to finalize answers.
After the provider reports the call completed, one audited claim_answer decision labels
the answer. Only a confident model label of confirmed or denied becomes evidence;
unsure, wrong person, callback, fallback and low-confidence answers stay unverified, and
failed or unanswered calls discard the answer. Answer text is deleted once finalized.

A fix_merged claim that names a pull request is confirmed by a signed pull_request
merge event in the incident's repository, merged no earlier than the incident opened.
Subscribe the GitHub webhook to pull_request events for this; unmerged closes are
ignored. When the classifier is enabled, chat messages with status words get one
claim_detection request; a detection only suggests record_claim.

### Escalation advice and dispatch guards

With the classifier and escalation jobs enabled, the gateway asks for a CI failure
category and an escalation step once the acknowledgement grace has elapsed. A
confident flaky, chat_nudge or wait answer sends at most one private note and delays
the call once by one grace period; anything else keeps the deterministic schedule.

create_call_service composes CallService with dispatch-time rechecks of the incident
owner and claim author, an optional readiness probe and
SVAAR_VOICE_DAILY_CALL_LIMIT (default 3) placements per person in any 24 hours.
No route, job or model tool places calls yet.


### Manual incidents

POST /api/v1/incidents with the operator token opens an incident for a mapped
repository:

```json
{"org_id": "<organization UUID>", "repository_id": 101, "workflow_id": 55,
 "workflow_name": "Deploy", "head_branch": "main"}
```

owner_principal_id is optional and defaults to the repository mapping's owner. A later
CI failure for the same workflow and branch joins this incident; a second active
incident for them returns 409. The owner receives the usual private alert.


### Bolna voice turn route

Svaar can act as the Bolna agent's custom LLM. Set these locally, then restart:

```sh
SVAAR_VOICE_TURN_MODE=llm_endpoint
SVAAR_VOICE_TURN_TOKEN=<random 32+ characters, separate from every other secret>
```

The SVAAR_LLM_* settings must already be configured. Only the selected mode's route is
mounted: /api/v1/voice/llm/chat/completions (and /api/v1/voice/llm/models) for
llm_endpoint, or /api/v1/voice/turn for function. The restricted tunnel listener
(create_status_ingress on port 8001) serves the status webhook and this route only.

In Bolna, add a custom LLM with URL https://YOUR-TUNNEL-HOST/api/v1/voice/llm, model
svaar and the turn token as its key, then select it for the agent. Add this line to the
agent prompt so each call's private reference reaches Svaar; Svaar never speaks it:

```text
svaar_call_ref: {{call_ref}}
```

Svaar puts call_ref in user_data when it places a call. Requests without exactly one
reference are refused without running the agent. To place a prepared call:

```sh
uv run --locked python -m svaar.dispatch --list
uv run --locked python -m svaar.dispatch --place CALL_ID --org ORG_ID
```

--place dials a real phone after checking Bolna readiness, the incident or claim, and
SVAAR_VOICE_DAILY_CALL_LIMIT. Use it only with explicit authorization for that call.
Whether Bolna delivers the prompt reference and stable history is unverified until the
first real call (plans/anomaly.md A-028).


Additional Caspian channels: see [channel setup and acceptance status](CASPIAN_CHANNELS.md).

