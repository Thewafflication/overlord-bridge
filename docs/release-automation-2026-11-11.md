# Release automation measurement — 2026-11-11

Snapshot generated at 2026-11-11T10:02:26.945654Z from retained installed
worker_reports/events.jsonl and events.1.jsonl, using the inclusive cutoff
2026-11-11T04:01:36.044Z (this automation's previous run). Events are
deduplicated by event_id by modules.worker_outcomes.

| Measure | Observed |
| --- | ---: |
| Terminal runs | 12 |
| Incomplete | 6 |
| Stalled | 5 |
| Model-finished, unverified | 1 |
| Acceptance-verified runs | 0 |
| Unique acceptance-verified task IDs | 0 |
| Acceptance preflights | 3 |
| Initially failing contracts | 3 |
| Recorded worker seconds | 13,261.156 |

This is a retained mixed-version cohort, not a cumulative delivery count or a
controlled comparison. Terminal runs exclude started runs with no terminal report.
A model-finished report alone is not a verified delivery. No live delivery-rate
increase is established. Raw evidence: out/checks/automation-20261111-cohort.json.

The concurrent command-execution repair owns release 1.0.103 (code 8112427).
Its Git-backed multiline-commit regression fails on 1.0.102 and passes after
repair, preserving the complete message and keeping owner helpers untracked.
Eleven focused checks passed. Canonical lint, fresh wheel and full tests passed:
1,584 passed, one skipped in 304.44 seconds. This proves the reproduced harness
repair; it does not establish a new live project deliverable.

Deployment verification is recorded below after release CI and installation.

## Verified deployment

Release: https://github.com/Thewafflication/overlord-bridge/releases/tag/v1.0.103
Code commit 8112427 and tag v1.0.103 were pushed by the concurrent repair chat.
Tagged Project checks 43000250224 passed on Windows and Linux; signed-package
build 43000250090 passed. WPM signature/hash verification preceded installation.
Package SHA256: 1bd9d177df1baed8c264e956cc3535124b833e685b818dd934af1a82809b1729.
WPM installation exited zero. Installed-module checks: 14 passed in 29.50 seconds.
Independent local-control status acknowledged v1.0.103 with instance
76aa033a66af45f38112ffed768ead7b after restart.

The installation proof confirms exact frozen schedules and owner queue preserved,
16 original schedules restored active, matching installed source, and four session
metadata records unchanged. Settings were checked by size only; secret contents
were not compared. Proof: out/checks/project-task-1.0.103-install-preservation.json.

The automation separately reran four outcome-accounting regressions: all passed
in 0.23 seconds. This report preserves the pre-deployment cohort rather than
silently replacing its denominator after installation. Next evaluate new runs
against owner acceptance checks; investigate the separately recorded Pydecipher
protected-planning-context fitting failure. A higher delivery rate remains unproven.
