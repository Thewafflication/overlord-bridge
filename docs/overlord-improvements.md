# Overlord improvement record

This is the durable change and results ledger. A successful dispatch, model
"finished" report, repeated validation or recovery of an earlier mistake is not
counted as a new product feature. Keep failed experiments and limitations here.

## Baseline frozen before 1.0.94

Source: installed events.1.jsonl plus events.jsonl, deduplicated by event_id;
free workers only, terminal reports since 2026-11-09T16:00:00Z. Snapshot generated
2026-11-10T16:11:19Z. Only the retained event window is measured.

| Measure | 1.0.93 baseline |
| --- | ---: |
| Terminal runs | 39 |
| Model finished | 3 |
| Incomplete | 28 |
| Stalled | 8 |
| Finished with passing owner acceptance | 1 (2.56%) |
| Unique accepted task IDs | 1 |
| Product features proven by this count | 0 |

The one accepted task was wkey-owner-cache-tracking-recovery-1, an index-only
owner-file recovery. The other two finished reports had no owner acceptance
contract. Independent Word-GPT full-suite validation is useful evidence, but is
not a new implementation or an automatically acceptance-verified task.
Machine snapshot: out/monitoring/improvement-baseline-1.0.93.json (local audit artifact).

## Change ledger

| Version | Evidence and change | Verified result / limitation |
| --- | --- | --- |
| 1.0.87 | Difficulty routing within admitted free models | Routing preferences tested; no measured product-delivery improvement established. |
| 1.0.88–1.0.89 | Repeated discovery windows and continuation handoffs | Automatic unfinished stops observed; novel output and repeated rewrites can still prolong runs. |
| 1.0.90 | Structured readiness assessment | Prevented unsupported completion; models repeatedly confused pending work with missing owner decisions. |
| 1.0.91 | Explicit PowerShell script invocation | Script launch fixture executes and returns real exit status; arbitrary indirect Python subprocess code is outside rewriting. |
| 1.0.92 | Bounded second assessment of readiness stops | Some owner work proceeded; repeated false needs-planning outcomes remained. |
| 1.0.93 | Reject observed process-kill verbs; preserve oversized-plan handoff | 1550 tests passed, both CI platforms passed, installed verified. Actual incomplete budget outcomes observed; static command checks are not a sandbox. |
| 1.0.94 | Ready owner contracts, pinned compact task context, check_acceptance, outcome accounting | Controlled before/after below; live delivery cohort recorded after installation. |

## 1.0.94 experiments

The exact new regression cases were run against detached source commit 5ea3121
(1.0.93) and the changed worker. Test models are deterministic fixtures; these
results measure harness behavior, not real model intelligence or product output.

| Reproduction | Before | After |
| --- | --- | --- |
| Explicit ready task with model proposing needs_planning, blocked, discovery or already_complete | 0/4 reach verified fixture completion | 4/4 complete after actual owner checks |
| Owner contract remains pinned under context pressure without copying check implementation into prompts | Fails | Passes |
| Combined regression cases | 0/5 pass | 5/5 pass |

Additional controls: failed acceptance still overrides a positive model reviewer;
a passing probe followed by a bad edit is rejected at final validation; metrics
deduplicate rotated events and do not classify unchecked finishes as verified.
Eleven focused checks pass. The full suite caught extra tool overhead breaking an existing constrained-Groq input test; restricting check_acceptance to assigned owner tasks restored that test (1/1 passes), without increasing the provider budget. Local artifacts: out/checks/owner-contract-before.txt,
out/checks/owner-contract-after.txt. The baseline checkout is isolated under out/.

Implementation: queue state ready supplies admission, while the model continues
to plan, select difficulty and report concrete blocked outcomes. Exact acceptance
code stays in the harness. The worker can call check_acceptance to obtain actual
failures. A probe neither completes a task nor publishes code. Final completion
and publication checks still run independently. Projects without an owner queue
retain their existing readiness assessment. Free mode never gains a paid fallback.

## Measurement and next targets

Run `python -m modules.worker_outcomes --reports <installed worker_reports>
--since <UTC ISO cohort start> --output <results.json>` after deployment. Reports
now include action_steps, readiness_source and delivery_status. The CLI also
classifies historical reports from actual acceptance results. Model-reviewed
finishes remain visible separately; passing checks do not establish test quality.

Track: terminal runs, acceptance-verified runs, unique accepted task IDs,
unfinished reasons, wall time and actual commit/test evidence. Never count the
same accepted task again as a new deliverable. Keep recovery, validation-only and
product implementation outcomes separate in this ledger.

Initial target: a normal existing scheduled pilot reaches its actual acceptance
checks without false needs-planning or lost contract context. Desired follow-up:
at least one independently rechecked newly accepted pending task. A sustained
rate comparison needs a comparable multi-run window; a short pilot cannot prove
that overall delivery rate improved.

## Deployment and live observations

Local canonical check: 1557 passed, 2 skipped in 197.56 seconds; tools/check.py all exited zero.
1.0.94 release/install verification and the post-install pilot are pending.
Do not interpret the deterministic fixture results as completed project work.
Update this section with release commit, CI, installed checks, cohort timestamps,
actual task IDs, commits, independent checks and remaining blockers.
