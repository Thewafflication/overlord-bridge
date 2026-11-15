# Release automation: 2026-11-15

## Post-install delivery measurement

Verified the existing 1.0.114 deployment rather than attributing its earlier
installation to this run. Live local control acknowledged version v1.0.114,
instance d9896953d54b4c70bf51b066b45678f2, KerTeX active. Installed workers.py,
worker_outcomes.py and version.py match repository bytes. All 17 schedules remain:
four active, thirteen paused. No schedule or project acceptance was changed.

Published release: https://github.com/Thewafflication/overlord-bridge/releases/tag/v1.0.114
(non-draft, non-prerelease). Tag CI 43666834149 and signed build 43666834154
both completed successfully. Prior signature/install preservation evidence
remains in the November 14 ledger. Seven outcome-accounting tests passed in
0.15 seconds this run.

| Metric | Runs started after installation |
| --- | ---: |
| Terminal runs | 11 |
| Stalled / incomplete | 9 / 2 |
| Acceptance-verified runs / unique tasks | 0 / 0 |
| Confirmed worker file mutations | 0 |
| Distinct successful command results (summed per run) | 211 |
| New observations / failure diagnostics | 1098 / 77 |
| Repository change checkpoints | 2 |
| Recorded worker seconds | 12200.703 |

All eleven runs have activity counters. Repository checkpoints are observations
of checkout changes, not attributed worker edits or deliveries. No acceptance
preflights or model-completed steps were recorded. Delivery rate remains 0%.
The source-retention regression improved from zero to four retained replies,
but this live cohort demonstrates no resulting delivery gain.

The journal cohort since 02:13:43.654096Z also contains one maintenance
interruption from the previous version. Its 59 command results, 73 observations
and ten diagnostics are excluded from the post-install table. Capture time:
2026-11-15T05:57:00.919045Z. Raw local artifacts:
`out/checks/automation-20261115-post114.json`,
`out/checks/automation-20261115-post114-started.json`, and
`out/checks/automation-20261115-post114-evidence.json`.

## Remaining experiments

Silver b5b1c7f98c3d44688a8bbeae004a26aa reread CMakeLists.txt 136 times
and its toolchain 39 times in 180 actions. Its final plan still selects reading
the toolchain and CMakeLists.txt despite those observations, and retains an
unresolved WCRT path. Next: replay the exact model-visible source/checkpoint
exchange and verify whether the selected next action survives successive fits.
Do not infer another context eviction solely from repetition counts.

TinyPP 5b90bd9287f44427aaed6b1eb33d5569 ended needs_planning with zero
actions; its readiness proposal names a bounded TPP-001 implementation and
existing acceptance commands. Compare its readiness review with the preceding
stalled run before changing routing. KerTeX has two repository-change
checkpoints but no confirmed tool edits; these must not count as delivered work.

No demonstrated new harness defect was isolated in this audit, so no new
runtime release or reinstall was performed. The requested completed-delivery
outcome remains unresolved. Preserve original owner hashes, Pydecipher quarantine,
and unrelated wsp/out/tools edits. Continue the next journal cohort from the
capture time above, retaining these unresolved failures.

## Follow-up cohort captured 12:03 UTC

Since 2026-11-15T05:57:00.919045Z, 18 terminal runs recorded 11 incomplete
and seven stalled outcomes. Acceptance-verified runs, unique verified tasks,
preflights and confirmed file mutations all remain zero. All 18 have activity
counters: 194 distinct successful command results (summed per run), 1,391 new
observations, 102 new failure diagnostics and zero repository change checkpoints.
Recorded worker time was 21,027.859 seconds (5.84 hours). One model-reported
completed plan step is unverified and does not count as a delivery. Delivery
rate remains 0%; no measurable product improvement is demonstrated.

Local control acknowledged v1.0.114, instance
d9896953d54b4c70bf51b066b45678f2, Silver active. The existing published
non-prerelease and tag CI 43666834149 / signed build 43666834154 remain
successful. Seven outcome-accounting tests passed in 0.85 seconds.

Specific unresolved evidence:

- Silver cbba052760084c5f9e72e12b94c17aae recorded 297 CMakeLists reads
  and 166 toolchain reads. Its predecessor 8741faa7d3484962b7f4127d715f9614
  retained a source page with explicit next_line=61, yet its next-action
  assessment requested later lines. Repetition alone does not establish that
  the harness dropped the cursor; capture/replay the actual next model request.
- TinyPP 6ecc6945f01b4cc395f7197ee98a8e86 ended needs_planning after
  72 actions, with TPP-001 explicitly named ready by the model. Its reported
  semantic IR baseline had 61 tests, 19 failures and seven errors. Next compare
  readiness inputs and review decisions with that bounded repair requirement;
  do not waive failing acceptance or overwrite pre-existing edits.
- KerTeX 9c7fe093eadc492f87f3ded5590a2f4c claimed TinyCC absent while
  earlier retained evidence identified an installed TinyCC path. Verify the
  actual model-visible discovery evidence and environment before accepting the
  missing-tool assertion or changing project prerequisites.

Evidence: out/checks/automation-20261115-1200.json and
out/checks/automation-20261115-1200-evidence.json. Capture cursor is
2026-11-15T12:03:49.708300Z; retain these unfinished failures next run.
No new demonstrated runtime defect was isolated, runtime release created or
installation performed in this audit. The requested completed-delivery outcome
is still unresolved. Existing workers, schedule states, owner hashes and
Pydecipher quarantine were left intact.

## 1.0.115 deployment completed at 18:06 UTC

Completed the pending installation from the "Fix tinypp edits and release"
repair chat, rather than creating a competing runtime patch. Code ce81424 was
already pushed and published as a non-prerelease. It requires a specific owner
question before a reviewer can confirm needs_planning; contradictory ready-work
stops receive bounded correction attempts. The scripted regression progresses
from the contradictory stop through corrected review to a file write. This is
harness behavior, not independent project acceptance.

Release: https://github.com/Thewafflication/overlord-bridge/releases/tag/v1.0.115
Tag CI 43737882772 passed: Windows 1,631 passed / three skipped in 116.97s;
Linux 1,599 passed / 35 skipped in 55.05s. Signed build 43737882823 succeeded.
WPM verification accepted the existing trusted signing key
6c21ebda96b16bfa64700d28fcdeb20dc4b19de448a723a970ac09b720f04b1d.
Archive SHA256 matched published SHA256SUMS:
6786d48eeae903431845284f7790ade267cd33cd28cb2b53cb8366e57acc6857.
Installation exited zero. Thirteen tests against installed modules passed in
2.14 seconds, including the contradictory readiness-stop regression.

All 17 frozen schedules and the owner queue survived exactly. Four active
60-second schedules and thirteen intentional pauses were restored. Four session
metadata records survived; settings checked by size only. Owned installed source,
including worker_readiness.py, matched the release checkout before ledger edits.
The installer automatically restarted with all schedules paused; normal shutdown
was requested again before restoring states and relaunching. This avoids changing
schedule files underneath a running scheduler. Preservation proof:
out/checks/project-task-1.0.115-install-preservation.json. Installed test evidence:
out/checks/verify-installed-readiness-1.0.115.txt.

### Pre-install measurement

From 12:03:49.708300Z through capture at 18:02:21.048050Z, thirteen terminal
runs recorded ten stalled and three incomplete outcomes, zero finished or
acceptance-verified runs, zero preflights, and one confirmed file mutation.
All thirteen have activity counters: 209 distinct successful command results
(summed per run), 1,206 new observations, 132 failure diagnostics and zero
repository-change checkpoints. Four model-completed steps remain unverified.
Recorded worker time: 21,213.906 seconds (5.89 hours). Verified delivery rate: 0%.

The mutation belongs to KerTeX run 5b17d234ff204be3bb44ce6a14fc2825,
which stalled after 222 actions. It is partial activity, not a completed delivery.
TinyPP's previously investigated uncommitted semantic IR edit still has no
established worker attribution and failing acceptance; this deployment does not
change that project or claim its completion. Silver repetition and KerTeX build
failures also remain unresolved.

Evidence: out/checks/automation-20261115-pre115.json and
out/checks/automation-20261115-pre115-evidence.json. The latter includes one
additional maintenance interruption, excluded from the thirteen-run measurement.
Continue the next journal cohort from 18:02:21.048050Z, separate maintenance and
runs started before this installation, and retain unresolved failures. Live
accepted-delivery improvement under 1.0.115 remains unproven.

Final live control acknowledged v1.0.115, instance
1cd6148df6674bfc95e074fd10d52fa6, KerTeX active. Verified all 17 schedule
IDs/prompts/intervals/states against the pre-pause snapshot after launch. Durable
monitor records the deployment as installed_verified, with delivery gain unproven.
