# Release automation: 2026-11-16

## Measured baseline

Capture: 2026-11-16T00:05:36.013416Z. Since the previous cursor
2026-11-15T18:02:21.048050Z, twelve terminal events include one maintenance
interruption. Eleven runs started after the 1.0.115 process launch at
18:05:22.485055Z: nine stalled, two incomplete, zero acceptance-verified
deliveries, zero confirmed mutations and zero preflights. All eleven have
activity counters: 126 distinct successful command results summed per run,
1,110 new observations, 69 new failure diagnostics and no repository change
checkpoints or model-completed steps. Recorded worker time: 20,484.419 seconds
(5.69 hours). Verified delivery rate: 0%.

Live control acknowledged v1.0.115, instance
1cd6148df6674bfc95e074fd10d52fa6, TinyPP active. Evidence:
out/checks/automation-20261116-post115.json,
out/checks/automation-20261116-post115-started.json and
out/checks/automation-20261116-post115-evidence.json.

## Reproduced defect and repair

TinyPP 40d953bc0d9e41a88ecf63c97e99624b ended after 300 actions with
needs_planning and no readiness review. Its actual proposal was more discovery
of five source ranges. The harness converted a repeated discovery decision
directly into needs_planning, bypassing independent review and the specific
owner-question requirement introduced in 1.0.115.

A new worker integration failed on the previous implementation because no
review occurred. With the fix, another discovery proposal receives review;
review can admit bounded technical work or confirm a concrete early stop.
Repeated discovery is rejected within the existing three correction attempts,
and the six-action discovery allowance remains unchanged. An invalid reviewer
leaves the actual proposal intact and the result incomplete; the harness no
longer invents a needs_planning assessment.

The regression now performs an existing-file edit and assertion command after
six discovery actions and corrected review. Additional coverage verifies two
invalid reviewer decisions followed by ready admission, and exhaustion without
renewed discovery, file changes or a fabricated owner question. These controlled
results prove repaired control flow, not an accepted project delivery. Silver
source repetition and KerTeX build failures remain unresolved.

Canonical lint, fresh-wheel build and offline tests passed: 1,633 passed,
two skipped in 139.71 seconds. Final focused readiness coverage: 31 passed in
3.72 seconds. Outcome/readiness unit coverage: twelve passed in 0.17 seconds.
Version consistency check passed for 1.0.116. Controlled before/after evidence:
out/checks/discovery-review-1.0.116-before-after.json. Release and installation
evidence will be recorded after verification.

## Verified 1.0.116 release and installation

Committed and pushed 44c6f5e; published non-draft, non-prerelease
https://github.com/Thewafflication/overlord-bridge/releases/tag/v1.0.116.
Main checks 43778771987 and tag checks 43778783555 succeeded on both platforms.
Tag Windows: 1,634 passed / three skipped in 109.399 seconds; Linux: 1,602
passed / 35 skipped in 55.692 seconds. Signed build 43778783579 succeeded.
The final added bounded-review retry cases are included in these hosted totals
and the focused suite above.

WPM verification accepted existing trusted signing key
6c21ebda96b16bfa64700d28fcdeb20dc4b19de448a723a970ac09b720f04b1d.
Archive SHA256 matched published SHA256SUMS:
a35f73f22ddc15c50183ba2780cd5d35268ebd78173f45ec830adfdc7748c669.
Installation exited zero. Sixteen tests against installed modules passed in
3.76 seconds, including reviewed discovery, bounded correction and real-edit
regressions. No project acceptance definition or permission was changed.

Before installation, paused only the four active schedules, froze all seventeen,
confirmed worker cleanup idle through local control, requested normal shutdown
and verified the old process exited. Frozen schedules and owner task queue
survived exactly. Restored four active 60-second schedules and thirteen existing
pauses while the bridge was stopped; verified all IDs/prompts/intervals/states
again after launch. Four session metadata records survived; settings checked
by size only. Owned installed runtime/document bytes matched the release checkout
before this final ledger update. No unrelated wsp/out/tools edits were committed.

Live local control acknowledged v1.0.116, instance
6e0e15354b1f480a96fdd7c2f774334e, KerTeX active. Proof:
out/checks/project-task-1.0.116-install-preservation.json;
out/checks/verify-installed-readiness-1.0.116.txt;
out/checks/install-1.0.116.txt. Durable monitor records installed_verified.

A final journal capture at 2026-11-16T00:17:06.792054Z contains only one
additional maintenance interruption since the baseline, with zero mutations,
six command results, 219 observations and five diagnostics. It is excluded from
the eleven-run product cohort. Continue from this final capture, retaining
unfinished blockers. The release fixes a demonstrated harness defect; accepted
project-delivery improvement remains unproven. Preserve original owner hashes,
Pydecipher quarantine, and the four-active/thirteen-paused schedule policy.
