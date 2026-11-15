# Release automation â€” 2026-11-14

## Availability recovered; delivery target still unmet

Cohort from 2026-11-13T21:57:21.174981Z through 2026-11-14T04:06:26.984089Z:
seven terminal runs, five stalled, two incomplete, zero finished or acceptance-verified
runs, zero unique verified tasks, zero acceptance preflights, 3,491.423 recorded
worker seconds. Verified delivery rate: 0%. This measures journaled worker time,
not elapsed uptime. Raw evidence: out/checks/automation-20261114-cohort.json.

Local control initially reported control_unavailable: recorded PID 53576 had exited.
The stale ready startup record did not establish health. Cause and exit time remain
unknown; no log files were read. Restarted the existing managed installation using
its run-windows.ps1 launcher in a hidden PowerShell window. Live protocol acknowledgement
confirmed v1.0.112 instance 9b9ab961e6fc4c16b8bbdcc700612613 with Free-tinypp active.
This restores availability; it does not demonstrate task completion or a permanent
fix for process exits.

Compared the 17 schedule IDs, prompts, states and intervals before/after restart:
all match, four active and 13 paused. Owner queue SHA256 unchanged. Installed
workers.py, worker_outcomes.py and version.py match repository bytes. Recovery proof:
out/checks/automation-20261114-recovery.json. No original acceptance hashes or
Pydecipher quarantine were changed.

Published v1.0.112 remains non-prerelease. Tag checks 43460814948 and signed build
43460814969 both conclude success. Prior signature/install preservation evidence
remains in docs/release-automation-2026-11-13.md. No new runtime patch, release or
reinstallation is claimed. Releasing identical code would not fix the outstanding
worker loops or unexplained process exit.

Reviewed context trimming and paired discovery-result retention. Existing regressions
already cover evicted successful reads with retained denials and pinned project
orientation. This inspection has not reproduced the live loop's root cause.
Next work must reproduce that loop using actual plan/source/checkpoint boundaries,
and investigate unexpected process exit through permitted diagnostics. Preserve
unfinished failures when advancing the cohort cursor to 04:06:26.984089Z.

Validation: 234 accounting and free-worker regressions passed in 127.40 seconds;
git diff --check passed. These checks verify existing guards, not live delivery.


## 09:58 UTC follow-up â€” stable process, repeated-action failures persist

Measured cohort 04:06:26.984089Zâ€“09:58:36.385368Z: 22 terminal runs,
21 stalled and one incomplete; zero finished, acceptance-verified runs, unique
verified tasks or preflights. Recorded worker time: 19,817.777 seconds across
1,335 actions. Verified delivery rate remains 0%. TinyPP contributed eight runs;
KerTeX and Silver seven each. All 21 stalls have repeated_observations as their
recorded reason. This is no measurable delivery improvement.

Evidence: out/checks/automation-20261114-1000-cohort.json and
out/checks/automation-20261114-1000-terminal-evidence.json. These retain bounded
plan/progress diagnostics, not inferred product completion.

Discriminating findings from actual reports:

- KerTeX 2e2196b0618a4486abf6c26e5e9f6626: 48 actions; final checkpoint
  19/24 repeated or failed observations. Recorded configure step 19 fails:
  WCRT headers not found under C:/WCRT/include. The generated mpd.h edit in the
  plan cannot resolve that prerequisite. The next experiment is reconciling
  toolchain locations with the configure failure before another header edit.
- Silver e0bde6ca1449495a88028fb1617cdb4e: 48 actions, 23 repeated toolchain
  reads and 16 repeated CMakeLists reads. Actual configure evidence includes
  CMAKE_C_COMPILER unset inside a CMake try_compile. A plan to set AG_TCC_ROOT
  in the parent environment is not proof of propagation into that nested build.
- TinyPP 08b6a1993dd7437c97a9ac5232873c1a: 48 actions, repeated test/validator
  reads. Its model-authored continuation reports 19 failures and seven errors
  after an existing version-field edit. These are retained claims to reconcile,
  not independently rerun project tests or accepted delivery. No new harness
  context-loss cause has been demonstrated by these metadata-only reports.

Live control acknowledged v1.0.112, same instance as the 04:07 recovery,
9b9ab961e6fc4c16b8bbdcc700612613, with Free-kertex_package active. Thus the
previous recovery remained live at this check; continuous uptime is unproven.
Installed workers.py, worker_outcomes.py and version.py match repository hashes.
Published v1.0.112 is non-prerelease; tag CI 43460814948 and signed build
43460814969 remain successful. Fourteen accounting/progress tests passed in
0.33 seconds. No workers stopped, schedules changed, acceptance weakened or
quarantined projects resumed.

This follow-up commits measurement and concrete failed prerequisites. It does
not claim a runtime repair, new release or installation. Release/install work
remains outstanding until a demonstrated harness repair passes required checks.
Next cohort cursor: 2026-11-14T09:58:36.385368Z; retain these unresolved failures.

## Owner-directed change â€” longer runs, smaller subtasks, partial measurement

Implemented in 14c6c2f, release v1.0.113. Repetition allowance increases from
three to twelve consecutive repeated-observation windows; coaching remains every
twelve actions without a direct edit. In unchanged-checkout integration scenarios,
the old stop near 48 actions now occurs near 156. This is a repetition allowance,
not a total action limit. Productive runs can continue longer; cancellation,
configured explicit limits and actual blocked outcomes remain available.

Startup and checkpoint planning ask for independently checkable subtasks, one
concrete action with one observable check. A failed experiment may resolve an
uncertainty without completing the requested feature. Overall acceptance remains
required. Plan completion is model-reported and explicitly unverified.

New run-wide activity counters survive dialogue trimming and checkpoint resets:
confirmed file mutations, distinct successful command results, new successful
observations, new failure diagnostics and repository change checkpoints. Outcome
summaries aggregate them, report measured-run coverage and mutation-bearing runs,
and keep model-completed steps separate. Repeated identical results are counted
once per run for distinct-observation metrics; this is activity, not proof of a
unique accepted subtask or delivery.

Controlled integration: after 55 repeated probes the worker can still write a
small result and finish, recording one confirmed mutation and one distinct
successful command result. This case passed in 13 seconds. Focused accounting,
progress and worker regressions passed 245 tests in 147.20 seconds before this
additional case. Canonical lint/fresh-wheel/full tests completed with 1,618 passed,
three skipped and two stop-control failures in 434.64 seconds. The unchanged
control module passed all 11 tests when rerun alone in 7.78 seconds; both original
failures remain recorded in out/checks/release-1.0.113-checks.txt. Hosted main
checks 43626122648 passed Windows and Linux; signed tag build 43626582542 passed.

Pre-install cohort since 09:58:36.385368Z, captured 18:22:22.331384Z: eight
terminal stalled runs, zero verified deliveries, 10,379.251 worker seconds.
All eight are unmeasured for the new partial counters. Evidence:
out/checks/automation-20261114-pre113.json. Live improvement is not yet claimed.

Deployment verified: tag checks 43626582576 passed on Windows and Linux.
WPM verified the trusted signing key and archive SHA256
9b6bd5c41e7121633c432166797996c71e349e6ae1070ffc54147ae195f88ff3.
Installation exited zero. Eighteen tests against the installed modules passed in
5.73 seconds, including the beyond-48-action subtask case. Frozen schedule
records and owner task queue survived exactly; all four original active schedules
were restored at 60 seconds, with 13 intentional pauses retained. Four session
metadata records survived, and settings were checked by size only. Installed
owned source matches the release. Preservation evidence:
out/checks/project-task-1.0.113-install-preservation.json.

Live control acknowledged v1.0.113, instance d52c086ea50645cb99a6d00682efc456,
with Free-the_silver_searcher active at 18:33 UTC. New runs now receive the longer
allowance and partial counters. No increase in live accepted deliveries is yet
claimed. Continue measuring from 18:22:22.331384Z, retaining prior failures and
identifying the maintenance interruption separately from productive execution.


## 2026-11-15 00:05 UTC — longer runs have not produced deliveries

Post-1.0.113 cohort from 2026-11-14T18:22:22.331384Z through
2026-11-15T00:05:45.410165Z: 17 terminal runs (12 stalled, four incomplete,
one maintenance interruption), zero finished or acceptance-verified deliveries,
and 19,397.279 recorded worker seconds (5.39 hours). Sixteen runs have the new
partial counters; the interrupted legacy run is unmeasured. Across measured runs:
zero confirmed file mutations, 255 distinct successful command results, 706 new
successful observations, 130 new failure diagnostics, zero repository-change
checkpoints and zero model-reported completed steps. These are per-run activity
counts; they do not establish useful commands, accepted subtasks or delivery.

All twelve stalls report repeated_observations. Action counts now reach 156–240,
so the longer allowance is exercised in production. More actions have not yet
produced measurable delivery improvement. KerTeX d98867a9 read mpd.h 69 times;
its continuation still proposes reading that header. Silver 3570ffb8 ends before
implementation with needs_planning and zero actions: the proposed next action
is reconciling current checkout/toolchain evidence. Neither finding independently
proves source eviction or a parser defect. Next discriminating experiment: replay
a stalled run's actual model-visible header result and checkpoint exchange to
establish whether useful source is present when the model asks for it again.
Do not increase repetition limits again without demonstrating productive work.

Evidence: out/checks/automation-20261115-post113.json and
out/checks/automation-20261115-evidence.json. Seven accounting tests passed in
0.10 seconds. Live local control acknowledged v1.0.113, instance
d52c086ea50645cb99a6d00682efc456, Free-tinypp active. Installed workers.py,
worker_outcomes.py and version.py match repository hashes. Published v1.0.113
remains non-prerelease; tag CI 43626582576 and signed build 43626582542 succeeded.
The earlier installation/signature/preservation evidence remains recorded above;
this run verified the existing deployment and did not perform another install.

This audit commits measurement, not a runtime repair or new release. Requested
completed deliveries remain unresolved. No workers stopped, schedules changed,
acceptance weakened or quarantined projects resumed. Preserve four active and
13 paused schedules, original owner hashes and Pydecipher quarantine. Continue
from 2026-11-15T00:05:45.410165Z while retaining the unresolved failures.


## Owner-requested repair — v1.0.114 source exchange retention

Investigated the no-edit cohort rather than increasing its repetition allowance.
TinyPP 6eb3cfa7 records repeated successful first-page reads of semantic_ir.py,
its tests and ADR-0011; KerTeX d98867a9 records 69 mpd.h rereads and later
continues proposing CMakeLists.txt rereads despite an observed missing WCRT root.
These show model repetition and stale next actions; they do not alone establish
that every repeated read was caused by the harness.

A deterministic reproduction establishes a harness contributor: with a pinned
12,000-character owner task and four parallel source replies, a 24,000-character
request budget discarded all four replies. Only action metadata remained. The
duplicate guard then allowed reacquiring the evicted source. Planning and provider
request fitting use this same fitter, making repeated reads possible without
advancing to the selected edit. The regression fails on the prior implementation
with zero retained replies instead of four.

The fitter now gives the newest source exchange priority over duplicated action
metadata. If it still cannot fit, it shortens source pages structurally while
retaining every paired call/reply, source beginnings, path, exact line/column
continuation cursor, and explicit context_compacted/truncated markers. It keeps
owner instructions, task, current plan, confirmed mutations and completion
feedback pinned. Formal and fallback source results are supported. The transport
cap also preserves structured source pages instead of wrapping a serialized JSON
tail when escaping pushes a large source page over 24,000 characters. Ordinary
oversized non-source exchanges retain existing behavior.

Measured repair checks: the reproduction retains four of four source replies
instead of zero; an integration worker receives all four source regions, edits an
actual existing file and validates it with run_python. Cursor tests reconstruct
source without gaps or duplication across mid-line starts and CRLF boundaries.
Nine new focused cases pass in 1.42 seconds. The earlier focused worker/budget/
progress/accounting suite passed 258 tests in 42.04 seconds before the transport
case was added. This is controlled harness evidence, not a live product delivery
or a guarantee that model repetition and project prerequisite failures are solved.

Release validation and publication evidence follows below when complete.


Local release validation: canonical lint, fresh wheel build and full offline suite
passed: 1,630 tests passed, two skipped in 154.57 seconds. Final focused suite
passed 259 tests in 47.16 seconds; pre-commit configuration and diff whitespace
checks passed. Version consistency check confirms 1.0.114. Publication pending.


Deployment verified at 2026-11-15 02:19 UTC: code a9ea2ea, tag v1.0.114.
Main checks 43666498821 and tag checks 43666834149 passed Windows and Linux;
signed build 43666834154 passed. Published release is non-prerelease:
https://github.com/Thewafflication/overlord-bridge/releases/tag/v1.0.114 .
WPM verified trusted signing key
6c21ebda96b16bfa64700d28fcdeb20dc4b19de448a723a970ac09b720f04b1d
and SHA256 f380ebb5399fe806bc5717e5d56358f475b81e0ac6b6acc7609c552a74642e15.
Installation exited zero. Eleven installed-module regressions passed in 10.04
seconds, including the parallel-read-to-edit-and-validation integration.

All 17 frozen schedule records and owner queue survived exactly. Four original
active schedules at 60 seconds and 13 intentional pauses were restored, then
verified after launch with unchanged IDs/prompts/intervals/states. Four session
metadata records survived; settings checked by size only. Installed owned source
matches the release. Live control acknowledged v1.0.114 instance
d9896953d54b4c70bf51b066b45678f2, Free-the_silver_searcher active.
Evidence: out/checks/project-task-1.0.114-install-preservation.json,
verify-installed-source-1.0.114.txt and source-batch-1.0.114-before-after.json.
The latter records the identical 52,912-character input changing from zero
retained source replies to four under a 24,000-character budget (22,943 final
characters), with owner task preserved in both revisions.

Pre-install follow-up cohort from 00:05:45.410165Z captured 02:13:43.654096Z:
seven terminal runs (six stalled, one incomplete), zero mutations or deliveries,
7,222.234 worker seconds. All seven measured; 60 distinct successful command
results, 211 new observations and 33 new diagnostics. This is still old-version
activity and is not a post-fix outcome. Continue from 02:13:43.654096Z, separating
the maintenance interruption and any pre-install work from 1.0.114 runs. No live
accepted-delivery gain is claimed yet. Retain unresolved project prerequisites,
original acceptance hashes and Pydecipher quarantine.
