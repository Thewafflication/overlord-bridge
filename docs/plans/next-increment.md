# Overlord next increment: reliable adaptive conversations

**Content type:** Proposed milestone work plan
**Identifier:** OVL-M02
**Date:** 2026-10-10
**Owner:** Overlord maintainer
**Baseline:** Overlord 1.0.5, source `6bb76de64aa51b6bc3208321f23de3145b313d52`
**Target:** Proposed 1.1.0; confirm after compatibility review.
**Status:** Planned; functional implementation and verification remain open.

## Execution progress

2026-10-10: WP1's initial offline Python check runner, controlled pre-commit
configuration, Windows/Linux CI definition, test collection isolation, and
usage-resilience regression tests are implemented. Headless console fixtures
were repaired. An infinite usage counter no longer crashes accounting.
See `docs/testing.md` for the declared inventory and remaining verification.
The rest of WP1 and WP2 through WP5 remain open; no increment release is claimed.

WP2 prompting slice: registered all documented Telegram commands, preserved
arguments, added explicit question IDs/reply/cancel controls, and prevented
unrelated messages from answering questions. Gate callbacks now resolve on the
owning loop and cancellation removes pending records. Native Claude and Codex
question tools have paired offline end-to-end tests through the real gate and
Telegram handler. Full multi-question review and restart recovery remain open.
The WP1 hosted Windows/Linux check workflow passed for `bed6cb7`.

WP2 permissions slice: replaced the global keyboard grant with exact-action
session grants, binding workspace, native arguments, and resolved paths.
Added grant inspection/revocation and cancellation-safe button invalidation.
`/new` stops an active turn before acquiring its lock and revokes grants.
Existing configured global auto mode is labelled and can be revoked at runtime.
Task/project grant persistence, full action audit, and equivalent enforcement
for the Linux Claude shared-job transport remain open WP2 requirements.

WP3 durability slice: workspace-bound versioned conversation checkpoints,
atomic saves, previous-snapshot recovery, bounded retention, and `/context`
inspection are implemented. Interrupted/failed turns retain reconciliation
warnings. `/new` clears the recovery copy. Structured summaries and native/
automatic compaction remain open. Hosted Windows testing exposed a duplicate
console timestamp bug, repaired with monotonic IDs and a frozen-clock test.

## Objective and scope

Every prompt should reach a suitable available model, retain the conversation's
intent, respect the owner's permission policy, and reliably return questions,
answers, usage, and results across Telegram and the supported local surfaces.

Include both meaningfully broader Claude/Codex workflow tests and stronger
validation of their usage accounting and quota measurements. Include additional
free services, durable compaction, per-prompt model selection, scoped approvals,
reliable user questions, and WSP integration.

## Observed starting point

- Both brains expose token usage, status, model/effort controls, interruption,
  and native interactive questions. Tests cover several of these separately.
- `modules/token_meter.py` accounts for cache usage and partial/failed turns.
- `SharedConversationHistory` is bounded in-memory recent history for switching
  brains, rather than durable structured memory or compaction management.
- `PermissionGate` makes “Always allow” process-wide until restart. Its path
  backstop scans normalized strings; it is not a complete authorization model.
- Claude shared-job injection follows the job's permissions and bypasses the
  bridge approval round trip. Unknown usage on that path is skipped.
- Worker routing exists in `plugins/overlord/scripts/engine_gauge.py`, with
  NVIDIA and local-agent workers. Routing is not a per-prompt conversation policy.
- The existing GitHub workflow packages/releases WPM artifacts; it does not
  define the proposed cross-platform behavioral and evidence gates.
- WSP was pinned to `1592880d0db6ace5919fc578f3f6070251e6fb34`, four commits
  beyond 1.1.0. This planning change pins released WSP 1.4.0 at
  `f009399dd1406219571ac978bfee85e85bbdfeac`.

## Work packages and acceptance allocation

Execute these in order. Each package needs a design review, tests, evidence,
and a local commit before reporting complete. Do not push automatically.

### WP1 — WSP adoption and testing foundation

1. Pin WSP 1.4.0 and retain the upgrade impact record.
2. Complete the requirement-by-requirement adoption/disposition matrix.
3. Define project requirements, test cases, and machine-readable traceability.
4. Add one reproducible check entry point used by pre-commit and independent CI:
   Python/style checks, tests, traceability, and applicable documentation checks.
   Control `.pre-commit-config.yaml` with lint, build, and full-test hooks in
   that order, `fail_fast: true`, and full-scope serial execution. Provision
   pinned dependencies before checks; preserve existing hooks during setup.
5. Add Windows and Linux CI, with explicit skips for unsupported surfaces.
6. Build a common scenario harness with fake Telegram and scripted provider
   transports, then replay sanitized protocol fixtures captured from real runs.
7. Add an opt-in live smoke suite for both brains with explicit turn/token
   budgets. Record CLI/SDK versions, model, platform, source, and timestamps.

**REQ-OVL-001 / TC-OVL-001:** The same conversation scenario passes on Claude
and Codex: start, resume, tool action, approval, question, stop, steer, switch,
restart, and failure recovery. Assert visible results and side effects.

**REQ-OVL-002 / TC-OVL-002:** Token and limit evidence distinguishes fresh input,
cache reads/writes, output, provider totals, estimates, and unknown values.
Cover duplicate/out-of-order events, cumulative totals, interrupted/failed turns,
reset, restart, stale cache, missing fields, reversed quota windows, multiple
limit buckets, and provider accounting changes. Reconcile live evidence against
provider-reported values using documented field semantics and tolerances.
No unknown usage becomes zero or proof of spare quota.

### WP2 — Permissions and user prompting

Introduce structured action requests and a shared policy decision contract.
Keep provider sandbox controls as enforcement layers beneath bridge policy.
Replace global “Always allow” with clearly stated grants: once, this task,
this session, or saved project rule. Grants bind action type, canonical targets,
workspace, expiry, and policy version. Provide listing and revocation.
Migrate existing auto-approval configuration explicitly; never silently broaden
its authority. Preserve non-overridable off-limits restrictions.

Resolve target paths, symlinks/junctions, case, and traversal before evaluation.
Use provider-native shell/sandbox controls for opaque commands; a substring
scanner or LLM judgment must not be the sole authorization boundary.
Shared-terminal execution must enforce equivalent policy through a supported
hook or controlled transport. If enforcement is unavailable, use the gated
execution path and report the operational consequence.

Create a shared question record with stable IDs, originating turn/session,
question IDs, choices, descriptions, custom answers, and lifecycle state.
Separate approvals from clarifications. Support multi-question progress,
editing answers before submission, cancellation, expiration, and restart
recovery. A new message must not accidentally answer an unrelated question.
Show pending requests in status and allow explicit reply/cancel commands.
Keep secret-input requests out of Telegram.

**REQ-OVL-003 / TC-OVL-003:** Equivalent allowed/denied actions produce equivalent
decisions on both brains and supported execution paths. Test traversal,
junctions, compound commands, revoked grants, cross-project access, cancellation,
late callbacks, timeout, and restart. A scoped approval never authorizes an
unrelated action. Every decision retains an audit reason and scope.

**REQ-OVL-004 / TC-OVL-004:** Choice and typed responses reach the correct native
tool exactly once. Test multi-question requests, duplicate/stale buttons,
interruption, brain switch, delivery retry/failure, and restart. Clarification
timeout yields an explicit unresolved state, never fabricated consent.

### WP3 — Durable session and compaction management

Add a provider-neutral conversation checkpoint containing objective, constraints,
decisions, task progress, artifact references, unresolved questions, and pending
actions. Retain source sequence references and recent verbatim context.
Store permissions separately as authoritative policy; summaries cannot grant
authority. Save checkpoints atomically with schema versions and recovery history.

Expose context pressure and compaction status. Prefer native compaction when
the installed transport supports it; discover capabilities rather than assuming
matching APIs. Otherwise make a controlled continuation from the checkpoint.
Use configurable thresholds and reserved headroom; missing context measurements
must be shown as unknown. Provide `/context` and `/compact` controls.
Never compact mid-tool or mid-approval. Validate and persist the checkpoint
before changing the session, then resume pending work without repeating effects.

**REQ-OVL-005 / TC-OVL-005:** A long scripted conversation survives compaction,
restart, and brain switching with constraints, decisions, pending questions,
and artifact references intact. Inject crashes before/after checkpoint writes
and session transitions. Verify no repeated command or broadened permission.
Corrupt/incomplete checkpoints recover from the last valid record explicitly.

### WP4 — Free-service support

Extract the NVIDIA/local tool loop into a reusable provider adapter without
removing existing aliases. Support conversation use as well as worker execution,
with durable neutral checkpoints where native sessions do not exist.
First qualify Groq and Gemini free-tier adapters; add OpenRouter free-model
support with an explicit free-only allowlist. Keep NVIDIA and local inference
in the catalog. Model IDs and quotas must be discovered/refreshed, not frozen
from today's catalog.

Each adapter declares streaming, tool calling, structured input, context size,
usage semantics, free eligibility, health, cooldown, and privacy conditions.
Support missing keys, model removal, quota exhaustion, 429/5xx, deadlines, and
retry-after. Verify free eligibility before automatic dispatch. Free-only mode
must block paid fallback. Local inference has hardware costs and finite capacity.
The owner chooses which providers may receive project data.

**REQ-OVL-006 / TC-OVL-006:** Each admitted provider completes the shared
conversation/tool/question/permission scenario. Mock paid fallback and model
removal to prove free-only enforcement. A catalog listing alone does not qualify
a model for automatic tool execution; live qualification evidence is required.

### WP5 — Automatic model and effort selection per prompt

Unify the worker router and conversation router around the provider catalog,
fresh usage evidence, capability requirements, and measured qualification.
Use an LLM to interpret prompt intent with stored conversation context and
produce a validated structured assessment. Do not classify dialogue through
regexes or keyword lists. Bound the classifier's cost and record it separately.
If classification fails, retain an eligible current model or report a blocked
decision; never guess an unsafe fallback.

Apply deterministic eligibility rules for privacy, permissions, capabilities,
quota freshness, free-only mode, and owner overrides. Rank eligible models by
demonstrated task quality, latency, context headroom, and cost. Select provider,
model, and effort at turn boundaries. Keep session affinity where changing models
would lose context; switch through WP3 checkpoints when necessary.
Provide auto/manual modes, one-turn and persistent overrides, and a readable
decision reason. Avoid silent premium escalation or repeated fallback loops.

**REQ-OVL-007 / TC-OVL-007:** A curated prompt set covers simple questions,
writing, narrow edits, ambiguous multi-file work, reviews, private/local tasks,
long-context work, capped engines, and unavailable free services. Assert policy
constraints rather than one permanently preferred model. Measure classifier
overhead, completion quality, handoff loss, latency, and escalation frequency.

## Verification and release gates

All seven requirements above are required gates for this increment.
Retain sanitized results under project-owned evidence storage, linked to
requirement/test IDs, source revision, platform, and provider versions.
Missing credentials mark live tests unavailable; mocks do not establish live
qualification. Run live tests in a controlled environment, not automatically
on every pull request. Preserve failure evidence without secrets or full private
conversation transcripts.

Release additionally requires the WSP adoption matrix, architecture decisions
for routing/checkpoints/policy, security review, Telegram UX acceptance record,
updated command/configuration reference, migration guidance, and a release
readiness/closeout record. Documentation must identify unsupported platform
surfaces. Required checks must fail on missing tools, not silently skip.

## Risks, recovery, and estimates

- Provider/API changes: record supported versions, replay fixtures, and qualify
  updates before enabling them for routing.
- Summary loss: retain checkpoint provenance and recoverable previous snapshots.
- Side-effect duplication: stable action IDs and reconciliation after disconnect;
  never replay an uncertain external effect automatically.
- Permission bypass: verify every transport, including shared Claude jobs.
- Free-tier volatility: bounded cooldowns, eligible fallbacks, and explicit
  waiting when no suitable service is available.

Ship additive storage migrations and independent feature switches for routing,
providers, and automatic compaction. Preserve manual brain/model selection.
Rollback must retain checkpoints, usage evidence, and grant records; stricter
policy cannot silently disappear on downgrade.

Do not assign calendar dates or effort estimates without implementation spikes
and measured baseline results. Replan after WP1 and after capability spikes for
native compaction/shared-job approvals. No failed required outcome may be
relabelled a documentation caveat to close this increment.

## References

- [WSP adoption and upgrade impact](../wsp-adoption.md)
- [WSP 1.4.0 release](https://github.com/Thewafflication/wsp/releases/tag/1.4.0)
- [Groq rate limits](https://console.groq.com/docs/rate-limits)
- [Gemini API pricing](https://ai.google.dev/gemini-api/docs/pricing)
- [OpenRouter limits](https://openrouter.ai/docs/api-reference/limits)
- `CAPABILITIES.md`, `README.md`, and `wsp/processes/milestone-plan-template.md`
