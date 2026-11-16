# Release automation: 2026-11-16

## Owner-directed persistent project memory: 1.0.119

Implemented local source/command evidence and model-plan persistence under the
existing worker report tree, shared by canonical project path. memory_search
and paged memory_read retrieve bounded historical data, with freshness checks,
timestamps, run/action IDs and run-start Git revision provenance. The startup
index includes recent IDs and the latest model-assessed next action. No extra
provider calls or embedding service are required. Current owner instructions,
permissions, acceptance and completion challenges remain authoritative.

Retention is 512 distinct records per project, at most 32,000 body characters
plus a truncation marker; long command streams retain 6,000 characters per tail.
Source freshness reads are capped at two megabytes. Retrieval defaults to 3,000
characters and is capped at 6,000; counts/evictions are explicit. Source policy
is rechecked, known environment secrets are redacted, linked storage is rejected
and memory failures preserve actual current tool results. Cancellation waits for
owned local memory I/O before idle acknowledgement.

Controlled restarted-worker regression: source observed in run one, retrieved in
a new manager with no prior dialogue, then an actual edit, assertion and local
Git commit. Run two uses one search and one page of at most 1,000 characters,
with zero read_file calls. Tests separately cover stale/missing source, paging
through compaction, scope isolation, bounded eviction, redaction, corrupt storage
and cancellation. This is a scripted model integration, not a live delivery gain.

Added tool schemas exposed a small-provider-context regression: an estimated
Groq character limit fell below protected instructions/plan, preventing further
work. Compact duplicate checkpoint coaching and find a smaller valid request
when that estimate cannot preserve protected context. The existing provider
retry bound remains unchanged; no owner evidence is dropped. The unchanged
integration again reaches actual validation, commit and push.

Focused checks: 256 passed / one skipped in 92.47 seconds before final provenance
metadata; final memory-specific coverage: eight passed / one skipped. The skip
requires Windows symlink creation privileges; the separate linked-parent test
passes without them. Full release validation and publication are recorded below
after they complete.

Committed and pushed 217b4076e06be573bef43caf7e5221085b63a450; published
non-draft, non-prerelease v1.0.119. Final canonical lint, fresh-wheel build and
offline tests passed: 1,665 passed / four skipped in 181.66 seconds. Skips were
one unavailable local Tk test, two platform cases and symlink creation without
Windows privilege. Main CI 43877352431 and tag CI 43877359207 passed both platforms.
Tag Windows: 1,666 passed / three skipped in 123.118 seconds; Linux: 1,622 passed /
47 skipped in 57.626 seconds. Signed build 43877359421 passed. WPM verification
accepted existing trusted signing key
6c21ebda96b16bfa64700d28fcdeb20dc4b19de448a723a970ac09b720f04b1d;
published SHA256SUMS matched archive SHA256
995a015bb332566444ffaf86e3caef8d2bed333d1a98b9219294d1efa8f791ce.

The final controlled restart proof retrieved exactly 339 characters, using one
search and one page, with zero second-run read_file requests, one actual mutation,
three distinct successful command results and a new local Git commit. Artifact:
out/checks/project-memory-1.0.119-proof.json. The result is a scripted offline
workflow, not a claimed increase in live accepted deliveries. Pre-install capture
2026-11-16T13:37:34.041328Z contains no terminal runs since the 1.0.118 launch;
there is no new delivery-rate denominator. Evidence:
out/checks/automation-20261116-pre119.json.

Installation exited zero. Paused only the four active schedules, froze all
seventeen, confirmed local-control worker cleanup idle, requested normal shutdown
and verified old PID 4532 exited before installer launch. Frozen schedules and
owner task queue survived exactly. Restored four active 60-second schedules and
thirteen intentional pauses while stopped; verified all IDs/prompts/intervals/
states and the task queue again after launch. Four session metadata records
survived; settings checked by size only. Owned installed source, including
worker_memory.py and its documentation, matched the release checkout before
the final ledger edits.

Eleven tests against installed memory/worker/provider modules passed, one skipped,
in 5.16 seconds, including restart/edit/validation/commit and protected-budget
recovery. Live control acknowledged v1.0.119, instance
8a1b9b7a6c4140f69ded73dce37ed291, with Silver active. A scoped live SQLite store
initialized; the first metadata check had no entries yet while planning was
pending. Do not claim actual live retrieval or delivery improvement from that
initialization. Evidence: out/checks/project-task-1.0.119-install-preservation.json,
out/checks/verify-installed-memory-1.0.119.txt and
out/checks/project-memory-1.0.119-live.json. Durable monitor records
persistent_project_memory as installed_verified.

Final capture 2026-11-16T13:44:53.549389Z adds one maintenance interruption from
the pre-install KerTeX run: two recorded mutations, 114 command results, 397
observations, 44 diagnostics and three repository-change checkpoints. Its zero
duration is unavailable accounting, not an instantaneous run. No accepted
delivery is attributed to the interruption or this memory release. Continue
from 2026-11-16T13:44:53.549389Z, preserving unfinished work and separating
maintenance/pre-install starts from post-install outcomes. Original owner hashes,
Pydecipher quarantine, exclusions and four-active/thirteen-paused policy remain.

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

## Post-1.0.116 cohort and diagnostic repair

Capture: 2026-11-16T05:59:00.044383Z, since 00:17:06.792054Z.
Twelve terminal runs, all stalled on repeated observations: four each for
KerTeX, Silver and TinyPP. Zero finished runs, acceptance-verified deliveries,
unique accepted tasks, confirmed file mutations or preflights. Recorded worker
time: 20,487.265 seconds (5.69 hours). Activity totals: 120 distinct successful
command results summed per run, 1,347 new observations, 57 failure diagnostics
and one repository-change checkpoint. All twelve have activity counters; these
are not accepted subtasks. Live control acknowledged the same 1.0.116 instance
6e0e15354b1f480a96fdd7c2f774334e with KerTeX active. Evidence:
out/checks/automation-20261116-post116.json and
out/checks/automation-20261116-post116-evidence.json.

Silver 2faab2dde4344919b9983bdf0ff2afa7 records PowerShell errors and startup
progress as CLIXML. Reproduced the underlying host-mode defect independently:
-OutputFormat Text does not fix -EncodedCommand's redirected stderr. A new
worker regression fails on 1.0.116 because the diagnostic is serialized.
The repair executes the identical base64 source in a fixed -Command script-block
invocation, avoiding command quoting damage and encoded-host serialization.
An additional compatibility experiment caught implicit failures becoming zero
when returning from the first script-block implementation. The final repair
maps the last success status to the host's 0/1 result inside the script block;
explicit exit statements keep their codes. Five additional worker regressions
cover native failure, nonterminating error, exception, success and recovery.

Controlled 400-progress-record experiment: before, 86,062 stderr bytes and the
original error absent from the retained 24,000-character tail; after, 543 bytes,
the original diagnostic present and readable, same stdout and exit code 7.
The new Windows worker regression checks this before output bounding, plus
multiline scripts, quotes, dollar signs, pipes and native stderr. Evidence:
out/checks/powershell-1.0.117-before.txt,
out/checks/powershell-1.0.117-before-after.json and
out/checks/powershell-1.0.117-focused.txt. This fixes observability of failures;
it does not establish that PowerShell serialization caused the source-read
loops or demonstrate improved project delivery.

## 1.0.117 publication and validation

Committed and pushed 55f95a202e931623253f71f2e3e96938da765954;
published non-draft, non-prerelease
https://github.com/Thewafflication/overlord-bridge/releases/tag/v1.0.117.
Final canonical lint, fresh-wheel build and tests passed: 1,642 passed,
three skipped in 161.60 seconds. One local Tk test lacked a usable graphical
installation; the other skips are platform-specific. Nine focused worker tests
passed in 18.68 seconds. Six additional before/after subprocess probes matched
exit status and stdout (out/checks/powershell-1.0.117-semantics.json).

Main CI 43814763481 and tag CI 43814778092 succeeded on Windows/Linux.
Tag Windows: 1,643 passed / two skipped in 115.804 seconds; Linux: 1,602 passed /
43 skipped in 59.014 seconds. Signed build 43814778038 succeeded. WPM accepted
the existing trusted signing key
6c21ebda96b16bfa64700d28fcdeb20dc4b19de448a723a970ac09b720f04b1d.
Archive SHA256 matched published SHA256SUMS:
6a39d74358b17e2fbff9bb0aafa10b864dd9f55bdb03ced7068f7aa111897129.
Evidence: out/checks/release-1.0.117/verification.json and hosted test artifacts
under out/checks/ci-1.0.117-windows and out/checks/ci-1.0.117-linux.

Maintenance paused only the four active schedules, froze all seventeen and
confirmed local-control worker cleanup idle. Normal shutdown removed control
discovery, but Python PID 28116 remained alive after repeated checks. No normal
process-exit claim is made: the existing package lifecycle stopped its owned
processes before replacing the installation. The shutdown hang's cause remains
unproven and warrants a separate bounded investigation.

Installation exited zero. While stopped, verified exact preservation of all
seventeen frozen schedules and the owner task queue, restored four active
60-second schedules and thirteen intentional pauses, and compared owned
installed runtime/document bytes with the release checkout. Four session
metadata records survived; settings were compared by size only. Launched the
managed install hidden and independently verified every schedule ID, prompt,
interval and state again, together with the unchanged task queue.

All 22 PowerShell regressions against installed modules passed in 29.39 seconds.
Live control acknowledged v1.0.117, instance
4cf762252f52413b996ac9754e087fbe, with Silver active. Proof:
out/checks/project-task-1.0.117-install-preservation.json,
out/checks/verify-installed-powershell-1.0.117.txt and
out/checks/install-1.0.117.txt. Durable monitor records powershell_diagnostics_repair
as installed_verified. Unrelated wsp/out/tools changes were left untouched.

Capture 2026-11-16T06:16:27.310161Z adds only one maintenance interruption since
the twelve-run baseline; it is separate from the product cohort. Its counters
are zero mutations, sixteen command results, 95 observations and eleven
diagnostics (recorded duration unavailable/zero). Next cohort cursor:
2026-11-16T06:16:27.310161Z. Retain unfinished source-read loops, KerTeX build and
TinyPP IR failures; preserve original owner hashes, Pydecipher quarantine and
four-active/thirteen-paused scheduling. Diagnostic preservation is demonstrated;
post-install project-delivery improvement remains unproven.

## Post-1.0.117 cohort and command-launch repair

Capture: 2026-11-16T12:03:13.174622Z, since 06:16:27.310161Z.
Nineteen terminal runs: six crashed, five incomplete and eight stalled. Zero
finished runs, acceptance-verified deliveries, unique accepted tasks, mutations
or preflights. Recorded worker time: 19,625.578 seconds (5.45 hours). Thirteen
runs have activity counters: 135 distinct successful command results summed
per run, 1,357 observations, 80 failure diagnostics and zero repository-change
checkpoints. One model-completed plan step is unverified. Evidence:
out/checks/automation-20261116-post117.json and
out/checks/automation-20261116-post117-evidence.json. Live v1.0.117 remained
online, instance 4cf762252f52413b996ac9754e087fbe, TinyPP active.

All six crashed runs report Windows access denied: Silver
4e8b5d14106d406895de9c9b17fd20f2 and 84adf872e1234fa3b60b79e702a398a0;
KerTeX 28476004dfdd4a85bee897f6d42351cb,
5c84a70cec5d44c4995f32e63ebb8407, 424e86b837eb40289f96876cf9acba17
and e08aca1030ef4f13b8609307a2782aa1. Prior monitor investigation traced the
first to process creation during a command tool call. No permissions are changed
or bypassed. Subsequent independent reproduction below identifies a concrete
Defender detection for the version-probe command.

Eleven new regressions failed on 1.0.117: process-creation OSError escaped the
command tool, including a real attempt to execute a directory. A scripted
worker crashed before its second action. With the repair, the tool returns
command_launch_failed, bounded/redacted OS diagnostics and null exit status;
the worker receives the failure, executes a subsequent Python probe and
retains both results in its continuation. That worker correctly remains
incomplete/blocked with no acceptance claim. Cancellation still propagates,
and no automatic retry or alternate shell is attempted. The focused final
suite passes twelve cases in 1.59 seconds, including cancellation and retained
continuation diagnostics. Evidence: out/checks/launch-1.0.118-focused.txt.

An actual command probe in this checkout reproduced WinError 5 for
`cmake --version; ninja --version`. Defender Operational event 1116 at
2026-11-16 06:08:17 local identifies Trojan:Win32/Commando.B!ml and the exact
1.0.117 PowerShell base64 decode/execute command line. This is a benign version
probe; the new wrapper introduced a concrete endpoint-protection compatibility
failure. Passing the original source directly as one -Command argument starts
both tools with exit zero. No Defender settings, exclusions or access rights
are changed. Quoted/multiline source and native exit behavior are tested.
The transport regression failed on the wrapper implementation. Evidence:
out/checks/launch-1.0.118-current-probe.json (failure),
out/checks/launch-1.0.118-transport-before.txt and subsequent after-probe evidence.

These controlled results demonstrate launch-error recovery and repair of the
identified transport incompatibility, not a live accepted project delivery.
Verified publication and installation evidence follows below.

Final canonical lint, fresh-wheel build and offline tests passed: 1,656 passed,
two platform skips in 160.73 seconds. Final focused launch/PowerShell coverage:
35 passed in 31.13 seconds. Six independent stdout/exit-status probes match
1.0.117. Evidence: out/checks/check-1.0.118-final.txt,
out/checks/launch-1.0.118-focused.txt,
out/checks/launch-1.0.118-semantics.json and
out/checks/launch-1.0.118-before-after.json. Version consistency passed.

## Verified 1.0.118 release and installation

Committed/pushed afb7a6d524a98bce1c9bde6eb365a7d6327adc3a and published
https://github.com/Thewafflication/overlord-bridge/releases/tag/v1.0.118
as non-draft/non-prerelease. Main CI 43864664460 and tag CI 43864669059
passed Windows/Linux; signed build 43864668993 succeeded. Tag Windows:
1,656 passed / two skipped in 100.078 seconds; Linux: 1,611 passed / 47 skipped
in 57.259 seconds. Hosted artifacts are under out/checks/ci-1.0.118-windows
and out/checks/ci-1.0.118-linux.

WPM accepted existing trusted signing key
6c21ebda96b16bfa64700d28fcdeb20dc4b19de448a723a970ac09b720f04b1d.
Archive SHA256 matches published SHA256SUMS:
e06ecc1706b5b14b2319aee94ce674ef9df41890bb20dde0d7a2dd52d11976fa.
Installation exited zero. Thirty-five regressions against installed modules
passed in 25.35 seconds. The installed interpreter/modules independently run
the formerly denied `cmake --version; ninja --version` with exit zero, reporting
CMake 4.4.2 and Ninja 1.13.2. Defender configuration remains unchanged.
Evidence: out/checks/release-1.0.118/verification.json,
out/checks/install-1.0.118.txt,
out/checks/verify-installed-launch-1.0.118.txt and
out/checks/launch-1.0.118-installed-probe.json.

Paused only the four active schedules, froze all seventeen and acknowledged
local-control cleanup idle. Normal shutdown removed discovery and old PID 29640
exited before installation; no forced process termination was required here.
All frozen schedules and the owner queue survived exactly. Restored four active
60-second schedules and thirteen intentional pauses while stopped, then verified
all schedule IDs, prompts, intervals and states after launch. Four session metadata
records survived unchanged; settings were checked by size only. Owned installed
runtime/document bytes matched the release checkout before these ledger edits.
No unrelated wsp/out/tools changes were committed.

Live control acknowledged v1.0.118 at 2026-11-16T12:20:55.761905Z, instance
b21cd09aeedc40d58eb1ca80328dc12a, KerTeX active. Preservation proof:
out/checks/project-task-1.0.118-install-preservation.json. Durable monitor records
command_launch_repair as installed_verified. Final capture since the baseline
adds one maintenance interruption with 139 observations and no mutations or
successful commands; this is separate from the nineteen-run product cohort.
Next cohort cursor: 2026-11-16T12:20:55.761905Z. Retain unfinished loops/build
failures, original owner hashes and Pydecipher quarantine. Controlled launch
repair is demonstrated; live accepted-delivery improvement remains unproven.
