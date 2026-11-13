# Release automation verification, 2026-11-13

Continued the unfinished 1.0.109 deployment rather than creating a competing
release. Code commit: 6ef7997. Published tag: v1.0.109. GitHub Project checks
43247247590 and signed package build 43247247644 succeeded. Prior canonical
checks: 1,615 passed, three skipped in 384.21 seconds.

WPM verified the package with the existing trusted signing key. Archive SHA256:
454007c5b2c3f2e77a0cef40b021b52c0ab02f775caead2ec6b6909565168b4e,
matching the release checksum. No unsigned override was used.

Installed-module regressions: 66 passed, one skipped in 36.65 seconds.
The first attempt used global Python without Telegram dependencies and failed
collection; rerunning through the repository environment succeeded. Installed
handoff replay preserved valid JSON, diagnostics and action numbers for all three
sampled workers: Silver 5,112 characters, TinyPP 7,868, KerTeX 7,513. Silver's
previous serialization was 9,087 characters and was sliced into invalid JSON.
This measures a diagnostic-retention repair, not completed project work.

## Delivery baseline before installation

Installed journals since 2026-11-12T09:59:03.643647Z, captured at
2026-11-13T02:21:18.297894Z: 34 terminal runs, 26 stalled, seven incomplete,
one crashed, zero finished, zero acceptance-verified deliveries, and
38,351.626 recorded worker seconds. Four accounting regressions passed in
0.17 seconds. Raw proof: out/checks/automation-20261113-cohort.json.

This mixed-version cohort does not establish a delivery-rate gain. The
maintenance interruption after capture is not a completed delivery. Follow up
post-installation runs for actual accepted tasks; repeated discovery across runs
remains unresolved by the bounded JSON repair.

## Installation preservation

All owned release source files match the installed copy. All 17 frozen schedule
records and the owner task queue survived exactly; four active 60-second
schedules and 13 intentional pauses were restored. Four session metadata records
survived. Settings were checked by size only, not content. Evidence:
out/checks/project-task-1.0.109-install-preservation.json.

WPM installation exited zero. Local control acknowledged v1.0.109, instance
02b32d483fc441139c3d885bcde4d2f2; Free-the_silver_searcher resumed. Initial
startup polling returned unavailable before the service came online. No new
project delivery is claimed. Runtime repair was already committed/pushed as
6ef7997; this audit completes its release/install verification.
