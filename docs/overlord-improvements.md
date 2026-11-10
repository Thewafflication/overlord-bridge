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
1.0.94 is committed and pushed as ac1d397, tagged and released. Project checks
42854350091 passed on Windows and Linux; signed-package build 42854349888 passed.
Signed ZIP SHA256: 6fde0dbc20e40e90d20227a03642dce40ac1698726df0e0988fb33d06684c7c4.
Trusted signing fingerprint: 6c21ebda96b16bfa64700d28fcdeb20dc4b19de448a723a970ac09b720f04b1d.

Normal local-control stop acknowledged idle, shutdown left no installed Python
process, WPM installed successfully, and 11 installed regression checks passed in
12.46 seconds. All 16 original schedules retained their prompts and 7200-second
intervals; owner queues and four session files were preserved. Settings size was
unchanged (secret contents were not read); runtime free mode was verified.
Preservation proof: out/checks/project-task-1.0.94-install-preservation.json.

The existing Pydecipher schedule 2b692635e7db was prioritized while offline after
preservation verification; the other 15 schedule records were unchanged. No new
schedule or task was created. Pilot started 2026-11-10T16:32:32Z, event
c08e10dfb0b7449b9bba8113f05b516f, owner task
pydecipher-remap-committed-cleanup-1. Cohort start: 2026-11-10T16:32:24.597783Z.

The pilot reached execution instead of its previous immediate unready stop.
Final acceptance and commit evidence are still pending. Do not interpret the
deterministic fixture results or a started live run as completed project work.
Update this section with release commit, CI, installed checks, cohort timestamps,
actual task IDs, commits, independent checks and remaining blockers.


## Follow-up: acceptance-first execution (1.0.95)

The 1.0.94 live pilot exposed an insufficient change: admission worked, but the
worker spent about40 actions rediscovering xdis interpreter/API facts and
editing from stale assumptions, without calling check_acceptance. This is not
counted as successful delivery or evidence of a higher real completion rate.

1.0.95 runs actual owner acceptance before planning, pins the observed result,
omits the prior inferred model plan for these explicit owner contracts, and
pins project AGENTS.md instructions. acceptance_baseline is retained independently
of final acceptance. Passing the baseline never waives completion/publication.
The new preflight regression fails against ac1d397 (1.0.94) and passes with the
follow-up; twelve contract/outcome focused checks pass. Artifacts:
out/checks/owner-preflight-before.txt and owner-preflight-focused.txt.

An audit also found a flaw in the monitor-authored Pydecipher acceptance: its
old fixed temporary directory already exists and must be preserved. The updated
check redirects only temporary-directory allocation to a fresh isolated root,
runs the same real pytest test_data3 with unchanged assertions, and requires the
test itself to remove that directory before harness cleanup. It requires an
actual passed test report, so a skip cannot satisfy it. Existing source-hash,
commit and no-op cleanup protections remain. This is an isolation correction,
not permission to delete owner artifacts or weaken the runtime check.

1.0.95 local canonical check: 1558 passed, 2 skipped in 195.07 seconds; tools/check.py all exited zero. Release/install proof: ff4027b, tag1.0.95; Windows/Linux checks42859883042 and package42859883044 passed. SignedZIP SHA2569231e1f6a4bba902a7d4ada7ab44a0cf8b31c17b71f86566e1ee226ef6ebed59; trusted fingerprint unchanged. WPM install exitedzero;12installedregressions passed6.68s. All16schedules,8ownerqueueentries and4sessionfiles preserved; free mode verified. Proof out/checks/project-task-1.0.95-install-preservation.json.

Secondpilot started2026-11-10T17:07:46Z (badc54e2833040acaed654d636c3494d). Preflight ran beforeplanning; firstplan targeted the observed cleanup failure. Terminalbc2fbba54cac4125a204172227358f9d was incomplete after22actions, missing finalcontract, with no verifieddelivery. This is a failed live outcome, not a synthetic success.


## Follow-up: unavailable preferred model (1.0.96)

The acceptance-first pilot received the real cleanup failure before planning,
but ended incomplete after22 actions without a valid final result. No delivery
is counted. Logs showed repeated OpenRouter HTTP429s and the preferred larger
NVIDIA nvidia/nemotron-3-super-120b-a12b route returning HTTP404. Smaller fallback
models produced invalid tool code and failed to complete the task.

The public https://integrate.api.nvidia.com/v1/models catalog still lists the old
Super ID, so catalog presence is not proof of chat availability. It also lists
nvidia/nemotron-3.5-super-vl-120b-a12b. NVIDIA's official API reference documents
that current endpoint and low/none/high reasoning effort:
https://docs.api.nvidia.com/nim/reference/nvidia-nemotron-3_5-super-vl-120b-a12b-infer

1.0.96 repairs the nemotron aliases and known legacy saved Super selection to
that current route, adds its reasoning preference, and canonicalizes its provider
IDs so the same model is not mislabeled as an independent reviewer. Reasoning
uses the documented low setting inside the existing output cap. Existing free
provider admission, opt-ins, limits and saved configuration stay in place. This
requires live account validation; it is not yet a measured coding improvement.
Eighty-seven focused provider/routing checks pass.

A local API check also corrected an earlier audit assumption: xdis6.3.0 accepts
both positional False and CPython/cpython strings for get_opcode((3,6), value).
Do not infer a runtime regression merely from that positional argument type;
validate the actual remap behavior. The isolated remap trial still fails its
real reconstruction case and preserves the old temporary directory.

1.0.96 canonical check:1560passed2skipped189.19s; tools/check.py all exitedzero. The current Super payload explicitly requests stream=false because the model API defaults to streaming and the harness expects one JSON response. Release/install and live current-model results pending.
