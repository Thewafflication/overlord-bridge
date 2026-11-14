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

