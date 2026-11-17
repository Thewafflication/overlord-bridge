# Release automation: 2026-11-17

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
