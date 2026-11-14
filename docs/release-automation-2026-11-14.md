# Release automation — 2026-11-14

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


## 09:58 UTC follow-up — stable process, repeated-action failures persist

Measured cohort 04:06:26.984089Z–09:58:36.385368Z: 22 terminal runs,
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
