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
