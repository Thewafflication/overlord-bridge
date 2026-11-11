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


## Follow-up cohort at 15:57 UTC

Inclusive cutoff: 2026-11-11T10:01:31.850Z. Snapshot generated at
2026-11-11T15:57:20.890960Z, deduplicated by event ID from the installed
report journals. Evidence: out/checks/automation-20261111-1600-cohort.json.

| Measure | Observed |
| --- | ---: |
| Terminal runs | 11 |
| Incomplete | 6 |
| Stalled | 4 |
| Interrupted | 1 |
| Model-finished runs | 0 |
| Acceptance-verified runs / unique tasks | 0 / 0 |
| Preflights / initially failing contracts | 2 / 2 |
| Recorded worker seconds | 14,364.829 |

No delivery-rate improvement is established. These cohorts overlap around the
prior release and have different populations; they are not a controlled before/
after experiment. Maintenance interruption is included in terminal runs and must
not be counted as a completed delivery. Projects assessed already complete by the
model are still unverified here.

Important failure: Pydecipher report da033837f6ec43969c0b02961febdc70
failed the owner check "Owned source quality and unrelated owner bytes preserved"
with `AssertionError: Unrelated owner source changed:
pydecipher/artifact_types/__init__.py`. Its terminal status is stalled, but that
label alone hides the more serious failed preservation check. Do not normalize
expected hashes or claim recovery. The active "Fix Overlord command execution"
chat is investigating four baseline hash mismatches and adding explicit owner
write protection; it reported pausing Pydecipher pending recovery evidence.
This audit does not independently prove the provenance or recoverability of
those bytes.

Other concrete follow-ups: WCRT report 9a0c2eee0b5249e9bcbfb5b316b46fd3
cannot fit protected planning context; TCC package report
be21151a8e87419d95fbe9a262d16869 could not admit owner-file protection
(OSError). WSH ready task wsh-public-header-repair-1 still fails acceptance
(report 75d90f607fb5450898db2684acd46400). Ordinary project implementation
remains with Overlord workers.

Independent status acknowledgement at 15:57 UTC: v1.0.103, instance
76aa033a66af45f38112ffed768ead7b, Free-wsp active. Four outcome-accounting
tests passed in 0.13 seconds. This documentation audit does not alter running
workers, task checks, schedules or release code. Release/install remains
serialized behind the active repair chat; no newer deployment is claimed here.


## Follow-up cohort at 21:56 UTC

Inclusive cutoff: 2026-11-11T15:57:20.890960Z. Snapshot generated at
2026-11-11T21:56:26.895938Z from installed journals, deduplicated by event ID.
Evidence: out/checks/automation-20261111-2200-cohort.json.

| Measure | Observed |
| --- | ---: |
| Terminal runs | 7 |
| Incomplete / stalled / interrupted | 3 / 3 / 1 |
| Model-finished runs | 0 |
| Acceptance-verified runs / unique tasks | 0 / 0 |
| Preflights / initially failing contracts | 1 / 1 |
| Recorded worker seconds | 18,186.562 |
| Verified acceptance rate | 0% |

These are mixed-version operational measurements, not a controlled experiment.
No new delivery gain is demonstrated. Outcome-accounting regressions independently
passed: four tests in 0.16 seconds.

Follow-up terminal reports:

- KerTeX 08d520301ba34f54953da320583e8a6f stalled on repeated observations;
  09adbd498b2842daaf033d2296ba0965 subsequently remained incomplete.
- Silver Searcher 3a36b908afc24d7288fad00f0aed0340 incomplete; the concurrent
  repair investigation identifies protected-context capacity as a separate issue.
- WSH c8082282e2fa40a888b1eae04d5cf3c5 stalled on ready owner task
  wsh-public-header-repair-1. Full acceptance remains unverified after timeout.
- TinyPP ccce1f9c5e8d40aab79dc9d508794f0b stalled on repeated observations,
  without an executable owner task ID attached to this report.
- WSP c9ba85d5de3a4db7aae79db9408207d2 interrupted; Jordan site
  d3692a96d2654ef19a2d166eec758fd7 incomplete. Neither is a delivery.

Independent local-control acknowledgement: v1.0.105, instance
392e4daa4bc3491195ddd1c1ac4f6d1c, Free-kertex_package active. Installed schedule
inventory has 17 entries: four active, 13 paused. This count check does not
establish full prompt/ID equivalence or installation preservation.

The active chat "Fix Overlord command execution" owns the uncommitted 1.0.106
source-reacquisition repair and deployment. Its controlled regression reproduces
retained denials blocking evicted source; its focused checks passed while the
canonical suite is still running. This automation preserves those changes and
serializes behind that release/install rather than issuing a competing version
or restarting healthy work. No 1.0.106 release/install success is claimed here.
Next verify its signed release, installed-module regression, schedule/queue
preservation and live acknowledgement, then measure newly terminated runs.
Pydecipher remains quarantined pending the four original owner hashes; preserve
the four-active/13-paused policy and independent acceptance checks.
