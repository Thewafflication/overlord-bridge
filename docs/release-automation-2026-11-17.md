# Release automation: 2026-11-17

## 12:03 UTC cohort and 1.0.121 execution evidence

The cohort since 06:00:06.396097Z, captured at 12:03:44.318657Z, contains
27 terminal outcomes: 17 stalled, three incomplete and seven skipped queues.
Acceptance-verified deliveries, finished runs, confirmed file mutations,
repository-change checkpoints and preflights are all zero. Twenty measured
runs record 138 distinct successful command results, 1,882 observations,
74 failure diagnostics and one unverified model-completed plan step.
Recorded worker time is 22,042.859 seconds (6.12 hours), not accepted work.
Start-time coverage is 27 started / 26 resolved / one unresolved, zero verified.

Workers recorded 6,347 archive links but zero memory searches, pages or
retrieved characters. The installed source matches the checkout at the start
of this run. Live control at 12:05:14Z acknowledges v1.0.120 instance
ad6c4a6438364f53b570490f55c11f98 with KerTeX active. All seventeen schedule
IDs, four active 60-second schedules, thirteen intentional pauses, completed
WSH queue and original Pydecipher protected hashes remain intact.

Older unresolved KerTeX start 1a21f81bcb564cc1923d1e9c163c195b remains in
retained coverage. The current unresolved start is dd6ebbc813ee469e852ed54152b59fd4
at 11:58:56.317007Z. Older Silver start 04a908cc104e4ce19cba7219a2553008
is no longer present in the retained journals; its absence does not prove
resolution. Keep that previously recorded evidence gap open across cursors.

The new improvement is bounded execution-request evidence, documented in
[1.0.121](releases/1.0.121.md). Prior reports could not establish the actual
source visible before a repeated-read decision. The provider boundary now
retains two redacted requests/responses per worker/project after context
fitting, with run/action provenance. Tests demonstrate actual fitted payload
capture and source-to-following-decision pairing. No project implementation,
acceptance contract or schedule prompt was changed. This is diagnosis support;
no live delivery gain is claimed.

Pre-change local evidence (untracked):

- out/checks/automation-20261117-1200.json
- out/checks/automation-20261117-1200-evidence.json
- out/checks/automation-20261117-1200-verification.json
- out/checks/audit-20261117-1200.py

Canonical local validation passed: lint, fresh wheel and 1,684 tests with
four skips in 201.43 seconds. The controlled execution-loop capture test and
provider-fitting, failure and cancellation tests pass. Code 2fca74f was pushed,
tagged v1.0.121, published and installed. Main CI 44081228148 and tag CI
44081250528 passed; tagged Windows had 1,685 passed / three skipped in 152s,
Linux 1,641 passed / 47 skipped in 67.47s. Signed build 44081250418 passed.
Existing WPM trust verified signature key
6c21ebda96b16bfa64700d28fcdeb20dc4b19de448a723a970ac09b720f04b1d;
archive SHA-256 f01a4c95bee2fa2f974a78b33c40b7fe5c8eb20c93571c95b2d4801a52c609d6
matches publication. Installer exited zero. Ten installed checks passed with
one symlink-privilege skip in 0.84s.

Preservation passed for all seventeen frozen schedules, exact owner queue,
31 report/memory files and four session metadata records. Original four active
60-second / thirteen paused states were restored while stopped and reverified
after launch. Settings size only was compared. Normal shutdown acknowledged
idle and removed discovery, but old PID 26244 persisted; the existing installer
lifecycle terminated owned processes. Its paused automatic restart exited
normally before state restoration. The underlying shutdown cause is unproven.
Live v1.0.121 instance 157a3ccfbfda4d1da6c86b9f9fa721ac resumed Silver.

Two actual live captures at steps 11/12 returned HTTP 200, at 56,685/56,593 bytes,
with no omitted request/response sections. Both hold source and the subsequent
read decision. Samples are preserved locally in
out/checks/request-1.0.121-live-samples, with bounded metadata in
out/checks/worker-request-1.0.121-live.json. Other proof:
out/checks/release-1.0.121/verification.json,
out/checks/project-task-1.0.121-install-preservation.json and
out/checks/automation-20261117-post121-verification.json.

## Follow-up repair from captured source eviction (1.0.122)

Silver's actual captures alternate CMakeLists.txt pages 167 and 1. A replay
assembled from those two captured exchanges and their recorded checkpoint
metadata reproduces loss of the older page: 53,087 input characters become
47,905 characters with only one source result. The fitter previously prioritized
the newest exchange over optional metadata but stopped before doing the same
for its immediately preceding exchange.

The fix prioritizes that earlier pair too, using existing structural source
compaction when needed. The identical replay now retains two results in 46,834
characters; newest content and all three pinned prefix messages are unchanged.
Older content has an explicit continuation at line 211, column 71. This is
honest shortened evidence, not a claim that the full older page still fits.
Regression tests failed before the fix and pass for intact/shortened earlier
pages with protected plan, mutation and feedback. Existing parallel-batch
regressions also pass. Proof: out/checks/request-retention-1.0.122-before-after.json.
Live accepted-delivery improvement is still unproven. Canonical lint, fresh
wheel and full tests passed: 1,686 passed / four skipped in 171.35 seconds.
Release and installation verification follows below.

## Independent post-1.0.120 measurement at 06:00 UTC

The installed release remains operational, but accepted project delivery has
not improved in this cohort. This run made no runtime change, release or
reinstallation. It independently checked the existing deployment and committed
the new measurements. Source-read loops and absent terminal evidence remain
unresolved; this audit does not call them fixed.

Inclusive terminal cutoff: 2026-11-17T00:12:40.596959Z. Snapshot generated
2026-11-17T06:00:06.396097Z from the installed worker_reports journals.

| Measure | Observed |
| --- | ---: |
| Terminal outcomes | 16 |
| Stalled / incomplete / skipped | 11 / 1 / 4 |
| Finished / acceptance-verified / unique accepted tasks | 0 / 0 / 0 |
| Recorded worker seconds | 17,847.639 (4.96 hours) |
| Runs with activity counters | 12 |
| Confirmed mutations / repository-change checkpoints / preflights | 0 / 0 / 0 |
| Distinct successful command results, summed per run | 262 |
| Successful observations / failure diagnostics | 1,378 / 104 |
| Model-reported completed plan steps | 0 |
| Start-time cohort: started / resolved / unresolved | 17 / 15 / 2 |
| Start-time acceptance verification | 0 / 17 |

Terminal and start-time denominators describe different cohorts. Skipped queues
are outcomes, not deliveries. Recorded time excludes absent durations. Activity
counts are not useful completed subtasks or independently accepted work.

Ten stalls explicitly cite repeated observations. TinyPP event
01c79b0c4cdf40b2998dcca22b3e579c instead yielded after the free-model pool could
not produce a usable response within 600 seconds. TinyPP event
9c6b7cb182244b6e946e397c3862511c stopped before actions with readiness
needs_planning over an error-message expectation. The latter is a model
assessment, not evidence that an owner decision is actually required.

Silver's repeated next-action assessments still ask to read CMakeLists.txt
around WCRT detection; TinyPP still proposes running its baseline; KerTeX still
proposes source inspection or reproduction of a compiler invocation. These
are proposals, not actions this audit executed or verified. No project
implementation was taken over and no acceptance check was weakened.

## Memory is populated but unused for retrieval

The twelve measured terminal runs report 3,990 archive links and **zero**
memory_search calls, memory_read pages or retrieved characters. Archive links
include repeated records. At 06:01:27Z, three project stores each contain the
512-record retention maximum; the fourth is empty. Persistence is working,
but this cohort provides no evidence of useful recall or a delivery gain.
Increasing storage or claiming these archives as progress would not address
the observed behavior.

The next investigation should retain the actual model-visible request around
a repeated source read and its following decision, then reproduce whether
needed evidence was missing, shortened or ignored. Existing retained reports
show outputs and assessments; they do not establish which of those mechanisms
caused a particular model decision. Any repair should be tested against that
request and an actual accepted task, with time/actions and retrieval usage
reported separately. A scripted retrieval test alone cannot prove live quality.

## Coverage gaps and deployment checks

The older unresolved Silver start 04a908cc104e4ce19cba7219a2553008 remains.
An additional KerTeX start 1a21f81bcb564cc1923d1e9c163c195b at
2026-11-17T03:27:19.187796Z lacks matching terminal evidence. Current Silver
start 60670455cdb9452c8f8244a2aebdce28 at 05:50:18.424583Z is also unresolved.
Live control at 06:01:27Z acknowledges only Silver active, v1.0.120 instance
ad6c4a6438364f53b570490f55c11f98. The instance differs from the previous
installation proof; this audit did not restart it and does not infer the exit
cause or synthesize missing outcomes.

Independently rechecked the published, non-draft/non-prerelease
[v1.0.120 release](https://github.com/Thewafflication/overlord-bridge/releases/tag/v1.0.120),
successful [tag CI](https://github.com/Thewafflication/overlord-bridge/actions/runs/43984609711)
and successful [signed package build](https://github.com/Thewafflication/overlord-bridge/actions/runs/43984609800).
Prior signature, checksum and installation evidence remains in the
[previous ledger](release-automation-2026-11-16.md). This audit did not repeat
installation or claim new signature verification.

Installed workers, worker_memory, worker_outcomes and version source text match
the checkout after newline normalization. Outcome and memory regressions pass:
23 passed, one symlink-privilege skip in 0.70 seconds. Verified all seventeen
schedule IDs and the four active 60-second/thirteen intentionally paused
states, completed WSH queue state and original Pydecipher protected hashes.
No schedule, owner queue or runtime file was changed. Unrelated wsp, out and
tools/_dev_show.ps1 changes remain outside the commit.

Raw local evidence (untracked):

- out/checks/automation-20261117-post120.json
- out/checks/automation-20261117-post120-evidence.json
- out/checks/automation-20261117-post120-verification.json
- out/checks/audit-20261117-post120.py

Next cohort cursor: 2026-11-17T06:00:06.396097Z. Retain all unresolved starts
and unfinished failures across that cursor. The measurable result remains
zero accepted deliveries; no delivery-rate improvement is claimed.
