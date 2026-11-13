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

## 1.0.110: reject invalid measurement sources

At 2026-11-13T04:02:15.270418Z, the cohort since
2026-11-13T02:21:18.297894Z contains ten terminal runs: nine stalled and one
maintenance interruption, zero finished or acceptance-verified deliveries,
and 5,466.703 recorded worker seconds. Raw evidence:
out/checks/automation-20261113-post109.json. This is a short follow-up cohort,
not a controlled comparison proving improvement or regression.

Found a concrete accounting defect: supplying run/worker_reports instead of
worker_reports silently yielded zero runs because missing journals were skipped.
The reader now rejects nonexistent directories and directories without either
journal. Existing empty journals still yield a valid empty cohort; rotated
journals retain their order. Six accounting regressions pass in 0.22 seconds.
This prevents an invalid data source from masquerading as measurement evidence.
Cross-run stalling is still unresolved; no product-delivery improvement claimed.

Canonical checks passed: syntax/inventory lint, fresh wheel build, and
1,618 tests passed with two skipped in 254.31 seconds. Release version check
matches v1.0.110. Signed publication and installation verification follow.

Deployment verified at 2026-11-13T04:15:41Z: published v1.0.110, code083d0ca.
Tag CI43363497464 passed Windows/Linux; signed build43363497473 passed.
WPM trusted-key verification passed; archive SHA256 matches published checksum:
29de7f6830f9d70256b11b16d31c1ebd8f7e0317527b9ba425801cc1ed9c78fd.
Normal stop confirmed idle, normal shutdown completed, WPM install exited zero.
Six installed-module accounting tests passed in 0.19 seconds. All owned source
files checked match; all17frozen schedules and owner task queue survived exactly,
four active60-second schedules/13intentional pauses restored, four session
metadata records retained. Settings checked by size only. Preservation proof:
out/checks/project-task-1.0.110-install-preservation.json. Live control acknowledged
v1.0.110 instancefd670bc637814f7389bd2686d05643d3, initially idle.
No new accepted project delivery is claimed. Next focus: cross-run execution
loops using unchanged acceptance checks, original hashes and Pydecipher quarantine.

## Post-1.0.110 audit at 2026-11-13T10:00Z

The cohort since 2026-11-13T04:02:15.270418Z, captured at
2026-11-13T09:59:57.996485Z, contains 21 terminal runs: 17 stalled,
three incomplete and one interrupted. Zero finished, zero acceptance-verified
runs, zero unique verified tasks, 14,903.253 recorded worker seconds.
Raw measurement: out/checks/automation-20261113-post110.json.
The maintenance interruption and service recovery make this an observational
cohort, not a controlled deployment comparison. No delivery improvement is proven.

Independent deployment checks: live control acknowledged v1.0.110, instance
a98f68ed34994fbdab05de585e15c3a4, with Free-tinypp active. The release remains
published/non-prerelease; tag checks 43363497464 and signed package build
43363497473 succeeded. Installed workers.py, worker_outcomes.py and version.py
match repository bytes. Six outcome accounting tests passed in 0.11 seconds.
The monitor records an intervening service restart at 07:47Z after process exit;
its cause remains unproven. A live acknowledgement here verifies recovery,
not continuous availability.

Saved unfinished evidence (out/checks/automation-20261113-1000-handoffs.json):

- Silver 24a1bfa9c4a44c188979b78459d246f1 stalled at action 48. Its retained
  plan names the duplicate WCRT linker symbols and asks for a verbose build,
  yet CMakeLists.txt and the TinyCC toolchain were each read 27 times. The last
  checkpoint had 18 repeated/failed observations in 19 actions and no observed
  repository change; repository evidence was partial.
- KerTeX 977f1849d455473d982c27d66c4f1c12 stalled at action 72. Its retained
  plan names the mpd.h parse error, but subsequent environment probes failed.
  The model suggests a fresh shell inherits setx changes; that is a model
  assessment, not a verified environment repair. A child normally inherits its
  parent environment. Diagnose with explicit process-local values and capture
  the actual build command/error in the project worker.
- TinyPP's active run f2a9fc06ca664c148e6654cac318a576 inherited a handoff with
  13 ADR reads and 11 semantic_ir.py reads. This active run is not a terminal
  delivery. The prior plan admits uncertainty about exact schema names and
  insertion points despite prior read-only passes.

The handoff remains available with task-specific plans and repeated-observation
counts. These observations do not establish that another serialization fix or
an increased action budget would repair execution. Next experiment should
measure whether the worker executes its bounded next action against unchanged
acceptance, rather than merely retaining another plan. Do not reset owner
hashes, relax acceptance, or resume quarantined projects to inflate completion.
No runtime patch, new tag, release or reinstall was performed for this audit;
the verified current release remains 1.0.110. Existing schedules and running
worker were left intact. The tracking document was committed and pushed.
