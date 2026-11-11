# Overlord improvement record

## Protected owner-byte failure (1.0.104)

Report da033837f6ec43969c0b02961febdc70 failed Pydecipher's exact owner-byte
acceptance. All four files now equal HEAD but differ from the recorded baseline;
LF/CRLF and BOM transformations do not explain the mismatch. The retained reports
show the same preservation failure at 2026-11-11T07:02:01Z. Earlier monitor
summaries recorded failed acceptance/stalls without surfacing the ownership
failure. That audit omission is corrected; failed-check stderr is now included
in the local collector's summary instead of only a boolean.

The files, relative to the Pydecipher repository, are:

- pydecipher/artifact_types/__init__.py
- pydecipher/artifact_types/pyc.py
- pydecipher/artifact_types/pyinstaller.py
- pydecipher/bytecode.py

Exact expected/current hashes and recovery searches are retained in
out/checks/pydecipher-owner-baseline-mismatch.json. Known path history, five
reflog/unreachable commits and project-local source backup searches found no
matching original copies; no unreachable objects remained. The specific
overwrite cause is not established. Do not label the difference a stat-cache
artifact or change expected hashes to pass. Owner originals/backups are needed.

Existing schedule 2b692635e7db is intentionally paused; retain all16 definitions
and 7200-second intervals, with15 other schedules enabled. Resume only after all
four original hashes match and the read-only guard is installed and verified.
This exception is recorded in intentional_paused_schedules, not treated as a
lost schedule. The four hashes are mirrored into the task's protected_files
contract without weakening the original acceptance checks.

The old Windows guard denied deletion but allowed writes. Explicit protected
files now receive write/deletion-denying handles, including committed clean
files. Hash verification occurs while locked, before preflight and model calls.
Mismatches yield incomplete with structured paths/hashes and zero model actions.
Other platforms fail closed for this explicit contract. This protects future
ordinary child-process writes; it cannot recover already-changed data or provide
an administrative sandbox.

The same changed-baseline integration fails on4b35054 (1.0.103): it invokes the
model. With the repair, it stops before any model call and releases handles.
Native Windows tests prove old-policy writes succeed, explicit read-only writes
fail, and owner editing works after cleanup. Eight focused tests pass with one
platform-specific skip. Canonical checks exited zero: lint, fresh wheel build,
1,591 tests passed and three skipped in265.12seconds. Release/install proof follows.

## Multiline commit and temporary-lock repair (1.0.103)

The WSP report 4b4f145e131f4cf9808078ef1a01f816 stalled after 108 actions;
the next run's step6 again failed a valid multiline commit message. The worker
attributed the lock to bridge Python processes and proposed removing it after
stopping them. Inspection reproduced the actual cause: the guard rejected all
newlines, including quoted message data, then held its own index lock during Git.

Literal standalone double-quoted messages now pass ownership validation. A native Git
test exposed a second defect: Windows CMD discarded the body even after the guard
unlocked. Default Windows execution now selects the existing encoded PowerShell
mode for this narrow literal form; approval and result metadata expose that mode.
Expansion-bearing inputs and outside-quote command boundaries remain blocked.
Known unsupported Git write wrappers return explicit separate-command guidance
before launch; lock-inspection results explain the temporary harness lock.

Eleven focused checks pass. The end-to-end worker validates an actual file edit,
commits it with the exact full multiline message, and leaves owner.ps1 untracked
and unchanged. Negative cases cover command injection boundaries and expansion
forms. This is a harness reproduction, not a claim that WSP's factual approval
fields or project deliverable have been independently accepted. Previous project
stalls and Word-GPT's validation-only finish remain excluded from new deliveries.

## Alternate-index incident (1.0.101)

At 2026-11-11T05:43Z the installed 1.0.100 process was offline; no shutdown
request or installed Python process was present. The exit cause is unknown.
No new completed reports existed. The work log instead exposed WSH bypassing
the default-index guard with `set GIT_INDEX_FILE=...`. Its local commit
3df90a1b2a53c74e4b396a53145157e0bea508d9 recorded 458 file deletions despite
the files remaining in the normal index and working directory. Default remote
master remained f305eeecec151acff99cd393babc19911f481205.

Recovery: preserve the bad commit under
refs/heads/codex/monitor-wsh-damaged-index-3df90a1, then soft-reset master to
a2d84c50714a6976c9102b743915f245de9c9ef8. Index bytes and the edited header
bytes matched before/after. This repairs automation-caused history damage;
it does not count as a new project deliverable. Proof:
out/checks/wsh-alternate-index-recovery.json. No hard reset or file deletion.

The known literal GIT_INDEX_FILE bypass now fails before shell/Python execution.
Five focused cases pass, including ordinary Git compatibility. Constructed names
and arbitrary database writes remain outside this mechanical rule; do not claim
a general sandbox or full ownership isolation. The offline exit remains an
unreproduced separate finding. Release and install evidence follows.

This is the durable change and results ledger. A successful dispatch, model
"finished" report, repeated validation or recovery of an earlier mistake is not
counted as a new product feature. Keep failed experiments and limitations here.

## Baseline frozen before 1.0.94

Source: installed events.1.jsonl plus events.jsonl, deduplicated by event_id;
free workers only, terminal reports since 2026-11-09T16:00:00Z. Snapshot generated
2026-11-10T16:11:19Z. Only the retained event window is measured.

| Measure | 1.0.93 baseline |
| --- | ---: |
| Terminal runs | 39 |
| Model finished | 3 |
| Incomplete | 28 |
| Stalled | 8 |
| Finished with passing owner acceptance | 1 (2.56%) |
| Unique accepted task IDs | 1 |
| Product features proven by this count | 0 |

The one accepted task was wkey-owner-cache-tracking-recovery-1, an index-only
owner-file recovery. The other two finished reports had no owner acceptance
contract. Independent Word-GPT full-suite validation is useful evidence, but is
not a new implementation or an automatically acceptance-verified task.
Machine snapshot: out/monitoring/improvement-baseline-1.0.93.json (local audit artifact).

## Change ledger

| Version | Evidence and change | Verified result / limitation |
| --- | --- | --- |
| 1.0.87 | Difficulty routing within admitted free models | Routing preferences tested; no measured product-delivery improvement established. |
| 1.0.88â€“1.0.89 | Repeated discovery windows and continuation handoffs | Automatic unfinished stops observed; novel output and repeated rewrites can still prolong runs. |
| 1.0.90 | Structured readiness assessment | Prevented unsupported completion; models repeatedly confused pending work with missing owner decisions. |
| 1.0.91 | Explicit PowerShell script invocation | Script launch fixture executes and returns real exit status; arbitrary indirect Python subprocess code is outside rewriting. |
| 1.0.92 | Bounded second assessment of readiness stops | Some owner work proceeded; repeated false needs-planning outcomes remained. |
| 1.0.93 | Reject observed process-kill verbs; preserve oversized-plan handoff | 1550 tests passed, both CI platforms passed, installed verified. Actual incomplete budget outcomes observed; static command checks are not a sandbox. |
| 1.0.94 | Ready owner contracts, pinned compact task context, check_acceptance, outcome accounting | Controlled before/after below; live delivery cohort recorded after installation. |
| 1.0.95 | Execute acceptance before planning; pin actual failure and project instructions | 1,558 tests passed; live Pydecipher pilot remained incomplete after 22 actions. |
| 1.0.96 | Repair preferred NVIDIA Super route and explicit non-streaming response profile | 1,560 tests passed; installed checks 15/15; live route HTTP 200, first plan rejected. No delivery improvement claimed. |

## 1.0.94 experiments

The exact new regression cases were run against detached source commit 5ea3121
(1.0.93) and the changed worker. Test models are deterministic fixtures; these
results measure harness behavior, not real model intelligence or product output.

| Reproduction | Before | After |
| --- | --- | --- |
| Explicit ready task with model proposing needs_planning, blocked, discovery or already_complete | 0/4 reach verified fixture completion | 4/4 complete after actual owner checks |
| Owner contract remains pinned under context pressure without copying check implementation into prompts | Fails | Passes |
| Combined regression cases | 0/5 pass | 5/5 pass |

Additional controls: failed acceptance still overrides a positive model reviewer;
a passing probe followed by a bad edit is rejected at final validation; metrics
deduplicate rotated events and do not classify unchecked finishes as verified.
Eleven focused checks pass. The full suite caught extra tool overhead breaking an existing constrained-Groq input test; restricting check_acceptance to assigned owner tasks restored that test (1/1 passes), without increasing the provider budget. Local artifacts: out/checks/owner-contract-before.txt,
out/checks/owner-contract-after.txt. The baseline checkout is isolated under out/.

Implementation: queue state ready supplies admission, while the model continues
to plan, select difficulty and report concrete blocked outcomes. Exact acceptance
code stays in the harness. The worker can call check_acceptance to obtain actual
failures. A probe neither completes a task nor publishes code. Final completion
and publication checks still run independently. Projects without an owner queue
retain their existing readiness assessment. Free mode never gains a paid fallback.

## Measurement and next targets

Run `python -m modules.worker_outcomes --reports <installed worker_reports>
--since <UTC ISO cohort start> --output <results.json>` after deployment. Reports
now include action_steps, readiness_source and delivery_status. The CLI also
classifies historical reports from actual acceptance results. Model-reviewed
finishes remain visible separately; passing checks do not establish test quality.

Track: terminal runs, acceptance-verified runs, unique accepted task IDs,
unfinished reasons, wall time and actual commit/test evidence. Never count the
same accepted task again as a new deliverable. Keep recovery, validation-only and
product implementation outcomes separate in this ledger.

Initial target: a normal existing scheduled pilot reaches its actual acceptance
checks without false needs-planning or lost contract context. Desired follow-up:
at least one independently rechecked newly accepted pending task. A sustained
rate comparison needs a comparable multi-run window; a short pilot cannot prove
that overall delivery rate improved.

## Deployment and live observations

Local canonical check: 1557 passed, 2 skipped in 197.56 seconds; tools/check.py all exited zero.
1.0.94 is committed and pushed as ac1d397, tagged and released. Project checks
42854350091 passed on Windows and Linux; signed-package build 42854349888 passed.
Signed ZIP SHA256: 6fde0dbc20e40e90d20227a03642dce40ac1698726df0e0988fb33d06684c7c4.
Trusted signing fingerprint: 6c21ebda96b16bfa64700d28fcdeb20dc4b19de448a723a970ac09b720f04b1d.

Normal local-control stop acknowledged idle, shutdown left no installed Python
process, WPM installed successfully, and 11 installed regression checks passed in
12.46 seconds. All 16 original schedules retained their prompts and 7200-second
intervals; owner queues and four session files were preserved. Settings size was
unchanged (secret contents were not read); runtime free mode was verified.
Preservation proof: out/checks/project-task-1.0.94-install-preservation.json.

The existing Pydecipher schedule 2b692635e7db was prioritized while offline after
preservation verification; the other 15 schedule records were unchanged. No new
schedule or task was created. Pilot started 2026-11-10T16:32:32Z, event
c08e10dfb0b7449b9bba8113f05b516f, owner task
pydecipher-remap-committed-cleanup-1. Cohort start: 2026-11-10T16:32:24.597783Z.

The pilot reached execution instead of its previous immediate unready stop,
but was interrupted for the follow-up deployment after 105 actions. Its terminal
report is 8802288edd734ecebc81e45bf94f7a9e. No verified delivery is counted.
Do not interpret deterministic fixtures or a started run as completed project work.


## Follow-up: acceptance-first execution (1.0.95)

The 1.0.94 live pilot exposed an insufficient change: admission worked, but the
worker spent about 40 actions rediscovering xdis interpreter/API facts and
editing from stale assumptions, without calling check_acceptance. This is not
counted as successful delivery or evidence of a higher real completion rate.

1.0.95 runs actual owner acceptance before planning, pins the observed result,
omits the prior inferred model plan for these explicit owner contracts, and
pins project AGENTS.md instructions. acceptance_baseline is retained independently
of final acceptance. Passing the baseline never waives completion/publication.
The new preflight regression fails against ac1d397 (1.0.94) and passes with the
follow-up; twelve contract/outcome focused checks pass. Artifacts:
out/checks/owner-preflight-before.txt and owner-preflight-focused.txt.

An audit also found a flaw in the monitor-authored Pydecipher acceptance: its
old fixed temporary directory already exists and must be preserved. The updated
check redirects only temporary-directory allocation to a fresh isolated root,
runs the same real pytest test_data3 with unchanged assertions, and requires the
test itself to remove that directory before harness cleanup. It requires an
actual passed test report, so a skip cannot satisfy it. Existing source-hash,
commit and no-op cleanup protections remain. This is an isolation correction,
not permission to delete owner artifacts or weaken the runtime check.

1.0.95 local canonical check: 1558 passed, 2 skipped in 195.07 seconds; tools/check.py all exited zero. Release/install proof: ff4027b, tag1.0.95; Windows/Linux checks42859883042 and package42859883044 passed. SignedZIP SHA2569231e1f6a4bba902a7d4ada7ab44a0cf8b31c17b71f86566e1ee226ef6ebed59; trusted fingerprint unchanged. WPM install exitedzero;12installedregressions passed6.68s. All16schedules,8ownerqueueentries and4sessionfiles preserved; free mode verified. Proof out/checks/project-task-1.0.95-install-preservation.json.

Secondpilot started2026-11-10T17:07:46Z (badc54e2833040acaed654d636c3494d). Preflight ran beforeplanning; firstplan targeted the observed cleanup failure. Terminalbc2fbba54cac4125a204172227358f9d was incomplete after22actions, missing finalcontract, with no verifieddelivery. This is a failed live outcome, not a synthetic success.


## Follow-up: unavailable preferred model (1.0.96)

The acceptance-first pilot received the real cleanup failure before planning,
but ended incomplete after 22 actions without a valid final result. No delivery
is counted. Logs showed repeated OpenRouter HTTP 429s and the preferred larger
NVIDIA nvidia/nemotron-3-super-120b-a12b route returning HTTP 404. Smaller fallback
models produced invalid tool code and failed to complete the task.

The public https://integrate.api.nvidia.com/v1/models catalog still lists the old
Super ID, so catalog presence is not proof of chat availability. It also lists
nvidia/nemotron-3.5-super-vl-120b-a12b. NVIDIA's official API reference documents
that current endpoint and low/none/high reasoning effort:
https://docs.api.nvidia.com/nim/reference/nvidia-nemotron-3_5-super-vl-120b-a12b-infer

1.0.96 repairs the nemotron aliases and known legacy saved Super selection to
that current route, adds its reasoning preference, and canonicalizes its provider
IDs so the same model is not mislabeled as an independent reviewer. Reasoning
uses the documented low setting inside the existing output cap. Existing free
provider admission, opt-ins, limits and saved configuration stay in place. This
requires live account validation; it is not yet a measured coding improvement.
Eighty-seven focused provider/routing checks pass.

A local API check also corrected an earlier audit assumption: xdis6.3.0 accepts
both positional False and CPython/cpython strings for get_opcode((3,6), value).
Do not infer a runtime regression merely from that positional argument type;
validate the actual remap behavior. The isolated remap trial still fails its
real reconstruction case and preserves the old temporary directory.

1.0.96 canonical check: 1,560 passed, 2 skipped in 189.19 seconds;
tools/check.py all exited zero. The Super payload explicitly requests stream=false
because the model API defaults to streaming and the harness expects one JSON response.

Deployment: commit f4f5f4f, tag 1.0.96. Project checks 42866364225 and package
build 42866364313 passed. WPM verified the trusted signature and SHA256
dfe3d5e781b03ac8ace3d5ec5472f053506eb435bde428c7c5e57f1c58998018.
Installation exited zero. All 15 installed regression checks passed in 6.11 seconds.
The first attempt used system Python without Telegram dependencies; it failed
collection, then passed using the repository test environment against installed
modules. This was a verification-environment failure, not a hidden passing result.

Preservation proof: out/checks/project-task-1.0.96-install-preservation.json.
All 16 existing schedules remain active at 7,200-second intervals, with original
IDs and prompts. Eight owner queue entries and four sessions survived. Settings
were checked by metadata only; secret contents were not read. Online instance
8804de7a41c04a9e94cf813249abbe68 reports version 1.0.96 and active brain free.

The existing Mypal schedule was moved first while stopped; the other 15 schedules
were unchanged. Cohort start: 2026-11-10T17:44:04.947524Z. The actual preflight
failed, as expected for the unfinished harness. The new NVIDIA Super chat/tool
request returned HTTP 200 in 29.64 seconds, proving account availability. Its first
plan failed schema validation; another admitted free model supplied a valid plan
and execution began. This proves a repaired route, not a completed project task.
Live outcome independently verified at 2026-11-10T19:42:02Z: Mypal completed
the production-backed digest regression harness in 46 actions and 1,532.328
recorded seconds (25.5 minutes). Terminal report ca0940de35e84cb085014681a56967a5
has passing owner acceptance. Commit 0353c66eea5a03eb566e6fa72de18d4b4b7662a9
matches live origin/master; its only changed path is the owned harness.
Manual review confirmed execution of the AST-extracted production guard, not a
copied comparison or simulated mutant result. Independent rerun passed the real
source and rejected removed/inverted comparisons with the same harness. Production
source SHA remained unchanged. Proof: out/checks/mypal-independent-delivery-1.0.96.json.
This is meaningful new regression coverage, not a new end-user product feature.
One quality limitation remains: the harness leaves uniquely named temporary input
files behind; cleanup belongs in a bounded project follow-up.

At 2026-11-10T19:42:03Z, the post-install cohort had 10 terminal runs: 2 model
finishes, 4 incomplete, 4 stalled. Only Mypal was acceptance-verified: 1/10 (10%),
one unique task. Word-GPT-Plus repeated validation without new code, so its finish
is not another delivery. All three recorded preflights initially failed; only
one subsequently reached verified acceptance. Snapshot:
out/monitoring/improvement-after-1.0.96.json. Compared with the earlier 1/39 baseline,
this is an encouraging observation, not evidence of a sustained rate improvement.

The next Kertex run still repeated generated mpd.h reads and status commands at
steps 81–89, including relative/absolute path variants and denied duplicate calls.
Local control acknowledged stop and idle at 2026-11-10T19:43Z; checkout/handoff
were preserved. This shows the observation guard still misses some mixed loops.
Record it for focused reproduction; do not claim the anti-loop problem solved.

## Ownership failure and repair (1.0.98–1.0.99)

At 2026-11-11T01:49Z, active Word-GPT work had committed four pre-existing owner
helpers as 9513809392044f47c1abefcb8a0a4ec753a880d5. The reviewer demanded a
clean tree and called those files worker-created; the worker explicitly stated
they were pre-existing, then staged them anyway. The files and local commit are
preserved for owner review. The worker was stopped with acknowledged idle. This
is an ownership failure and is not counted as a meaningful delivery.

The deletion guard did not cover Git index state. A separate guard now snapshots
pre-existing untracked paths, pins that ownership for worker/reviewer, and uses
a temporary default-index lock around model command/Python tools. Only separate,
literal owned-path adds and commits may proceed without the temporary lock.
Explicit queue publication paths are exempt. External locks remain untouched;
cancellation releases the worker's lock. No secret or owner file contents are
read by this new inventory. See release notes for the cooperating-Git boundary;
it is not a general code sandbox and does not rewrite owner history.

Controlled before/after: the same integration case on caac3bf (1.0.97) fails
because original_backup.ps1 becomes staged. With the repair it remains untracked,
and the completion reviewer receives its ownership baseline. Seven focused checks
pass. This measures the reproduced ownership bug, not live delivery throughput.
Artifacts: out/checks/index-guard-before.txt and index-guard-focused-final.txt.
The first broad test run caught two publication fixtures using Python subprocesses
for Git staging/commit, now intentionally locked when owner files exist. Those
fixtures now use separate explicit Git commands and retain their real regression,
commit and remote-SHA assertions; both pass. The fresh canonical tools/check.py all
exited zero: 1,571 passed, one skipped in 166.92 seconds, with lint/build checks.
Release and installation evidence follows after verification.

## Continuing measurement policy (ongoing)

For each new terminal report, retain the task ID, baseline check results, final
acceptance, action count, recorded duration, local commit and required remote SHA.
Review actual changed code and tests before describing a new product deliverable.
Count unique accepted task IDs separately from repeated verification runs and
owner-file recoveries. Keep maintenance interruptions separate from autonomous
failures when comparing cohorts. A small pilot is not comparable to the whole
39-run baseline; report both denominators rather than implying a global rate gain.

The durable cursor and inventory live in out/monitoring/overlord-project-work.json.
Use modules.worker_outcomes for rotated-event deduplication and machine snapshots.
Keep this document current when a repair, release, experiment or failed pilot adds
evidence. Do not release cosmetic ledger-only updates.

## 1.0.97 — repeated file path aliases (2026-11-10)

The Kertex observation motivated a focused repair: the progress watcher used raw
result paths as evidence identity. Relative, absolute and dot-component aliases
could register the same file contents as fresh observations. Worker-root lexical
normalization now treats those aliases consistently, using host case semantics.
No filesystem contents or links are read during normalization. Different paths
and changed contents remain independent evidence. Command stdout is not rewritten;
this repair does not claim to detect every mixed command/discovery loop.

Measured regression: four aliases across 48 reads now produce one new observation,
then zero; the unchanged checkout yields at the fourth checkpoint (three repeated
windows). Previously the first window counted four new observations. Seven focused
progress/handoff tests pass. This measures evidence accounting, not higher live
completion or delivered-feature rates. The prior live baseline remains 1/10 verified
runs, one unique task. Next assess comparable post-install terminal cohorts and
independently review their actual deliverables before claiming a rate improvement.

Additional traced finding: successful read_file results already carry relative
paths, so path aliases are a defensive accounting repair, not a demonstrated root
cause of the Kertex incident. The bounded 4,096-entry cache had a separate proven
bug: once full, unknown observations counted as novel but were never remembered,
allowing identical uncached results to renew discovery indefinitely. At capacity,
unknown observations now conservatively count against progress until repository
changes are observed. A regression fills the cache then repeats 12 uncached
results per window: before, every window counted 12 new results and never yielded;
after, zero new results and a yield after three windows. Tradeoff: genuinely new
read-only evidence after capacity no longer extends discovery. This is a bounded
4096-observation safety policy; checkout changes still reset the stall streak.

Validation: canonical checks exited zero: 1,563 passed, one skipped in 196.92s. After the saturation addition, eight focused checks, lint and a fresh wheel build passed. Live completion improvement remains unmeasured.

Deployment: code commit 8e62d1e and tag v1.0.97 pushed. GitHub Project checks
42911753567 and signed package build 42911753649 passed. WPM trusted-signature
verification passed; archive SHA256:
552531a2b0633be7deb15b77e7266b90b29f28ae578bb4b8db2487b5165abef8.
Installation exited zero. Three regressions rerun against the installed module
passed. Local control acknowledged v1.0.97, instance
72d5b5f561a8404f8c2763290dfa6950, with scheduled Free-wsp work active.
All 16 schedule IDs, prompts, enabled flags and intervals matched preserved
pre-install state. The initial exact schedule hash check failed because normal
scheduler last_dispatch/next_run fields advanced; those were the only differing
fields. The project task queue hash stayed unchanged. Proof:
out/checks/1.0.97-installed-verification.json. No new live deliverable or cohort
rate gain is claimed by this release.

1.0.98 Windows CI failed its constrained Groq case while Linux passed. It was not installed and is marked prerelease. Reproducing under a CI-length Windows path showed the expanded immutable ownership notice exhausted fitting room. A compact pinned notice retains all listed owner paths; full reviewer ownership evidence and index enforcement remain. The same long-path case passes without changing the provider limit. The corrected next patch is 1.0.99.

Corrected 1.0.99 canonical checks exited zero: 1,571 passed, one skipped in 166.17 seconds. The mechanical owner-index guard is unchanged; the pinned execution notice is compact, and the reviewer still receives the complete bounded ownership evidence.

Deployment verified: code commit abb4fd9, tag v1.0.99. Project checks 42944485484
passed on Windows and Linux; signed package build 42944485465 passed. Trusted
WPM signature and archive SHA256 verified:
3e0dfc70b50c14e59e21cad17b3f7de727b0611c514a7d7e555751adafb87ef8.
Installation exited zero. Nine tests against the installed modules passed in
21.73 seconds, including real Git index rejection and owned commit/publication.
All 16 original schedules remained active at 7,200 seconds; frozen schedule
state and owner queue were preserved exactly by installation. Four sessions
survived; settings were checked by metadata only. Preservation proof:
out/checks/project-task-1.0.99-install-preservation.json. Local control reports
v1.0.99, instance a97e2466666849478bdddec6c1d442d0; free mode verified and the
existing WSH schedule resumed. No new live project-delivery gain is claimed.

The unwanted local Word-GPT commit 9513809 remains preserved for owner review.
Origin lookup returned Repository not found; its publication state is unknown.
No automatic reset/revert or owner-file deletion was performed. Later worker
reports cannot reclassify that ownership violation as a product deliverable.
Retained event logs are not a cumulative metric: the independently proven Mypal
delivery remains recorded after its original event rotates away.


## 1.0.100 — reliable terminal cohort boundaries (2026-11-10)

Outcome accounting compared ISO timestamps lexically. Offset representations and
fractional-second boundaries could exclude runs occurring after the cutoff or
include earlier runs. Cohorts now compare parsed UTC instants, inclusively.
Legacy naive dates mean UTC; invalid cutoffs and missing/malformed terminal times
in filtered cohorts fail explicitly rather than quietly biasing the denominator.
Unfiltered legacy accounting remains available.

Measured regression: a three-event cohort (exact boundary, 30 minutes before,
30 minutes after, each with a different UTC offset) previously counted one run;
now correctly counts two for both equivalent cutoff representations. Four focused
tests cover this plus legacy timestamps and invalid input. This fixes measurement,
not worker delivery behavior, and does not establish a higher delivery rate.

Live snapshot at 2026-11-11T04:02:40Z, since the automation cursor
2026-11-10T22:03:00.042Z: 23 terminal runs, zero acceptance-verified runs,
12 stalled, eight incomplete, two interrupted, one unverified finished run.
Four preflights all started with failing contracts; 11,698.266 recorded worker
seconds. This mixed-version, overlapping cohort is not a controlled comparison.
The unverified finished report has no owner task ID; it is not a verified product
delivery. Evidence: out/checks/1.0.100-cohort.json. Next prioritize the stalled
ready-contract runs, preserving independent acceptance and ownership checks.

Validation: canonical project-environment checks passed: lint, fresh wheel build, 1,574 tests passed and one skipped in 219.68 seconds. Release version consistency and diff whitespace checks passed.


Deployment: code commit b1ce691 and tag v1.0.100 pushed. Tagged Project checks
42957141496 passed on Windows and Linux; signed package build 42957141560
passed. WPM trusted-signature verification succeeded, archive SHA256
7ab55bad148dead853c2b0946193d2c96c549263a1b3a4ab2efae4df8bdcd572.
Installation exited zero. Four tests rerun against the installed module passed.
After initial startup latency, local control acknowledged v1.0.100, instance
cf5383fb366c49c6b4cda7ba446e7148, with Free-wsh resumed. Owner queue hash
is unchanged. Sixteen schedules remain, but the schedule hash changed; only a
pre-install hash was retained, so complete schedule-definition equivalence is
unproven. Do not report this preservation check as passed. Next installation
must retain definition snapshots before restart (excluding scheduler clocks
only for an explicit semantic comparison). Proof:
out/checks/1.0.100-installed-verification.json. No live delivery gain claimed.

1.0.101 canonical checks exited zero: lint, fresh wheel build, 1,579 tests passed and one skipped in 231.69 seconds. Five focused known-bypass/normal-Git controls passed. Comparing the saved verified1.0.99 schedule snapshot with the offline1.0.100 inventory confirms identical16IDs, prompts, intervals and enabled states; scheduler clocks are excluded from that definition comparison.

1.0.101 was not installed: Windows CI passed, Linux CI caught a test assuming PowerShell tool mode exists there. The corrected test checks literal command denial on all platforms and expects unsupported_shell for unsupported tool mode. Production protection is unchanged; corrected deployment version is1.0.102. Candidate1.0.101 is marked prerelease.

Corrected1.0.102 canonical checks exited zero: lint, fresh wheel build, 1,578 tests passed and two skipped in212.64seconds. Production bypass rejection is unchanged from the Windows-verified1.0.101 candidate; the test now respects unsupported shell modes on Linux.

1.0.102 deployment verified: code commit26b0ef2, tagv1.0.102. Project checks
42969507593 passed on Windows and Linux; signed package build42969507552 passed.
Trusted signature and archive SHA256 verified:
ff252c20f0c363c6a730d889be8f1d145c7d1c2b6353889202e1807588bfd829.
WPM installation exited zero. Five checks against installed modules passed in
0.63seconds. Exact frozen schedules and owner queue survived; all16original
schedules are active at7200seconds and four sessions survived. Settings were
checked by metadata only. Proof: out/checks/project-task-1.0.102-install-preservation.json.
Local control acknowledgedv1.0.102, instance245156c51d30449e889e31af3106336c;
free mode verified and existing Pydecipher work resumed. WSH HEAD remains the
restoreda2d84c5; damaged3df90a1 remains under the backup ref. This recovery and
known-bypass repair are not counted as a new project feature. The earlier process
exit remains unexplained and requires monitoring; do not claim it was fixed.

1.0.103 controlled reproduction: the same Git-backed integration fails on086395a (1.0.102), leaving one baseline commit. An intermediate unlock-only experiment created a commit but lost its message body under CMD; the final encoded-PowerShell execution preserves the exact body. Canonical tools/check.py all exited zero: lint, fresh wheel build, 1,584 tests passed and one skipped in304.44seconds. These are harness measurements, not new project deliveries.

1.0.103 deployment verified: code commit8112427, tagv1.0.103. Project checks
43000250224 passed on Windows and Linux; signed package build43000250090 passed.
Trusted signature and archive SHA256 verified:
1bd9d177df1baed8c264e956cc3535124b833e685b818dd934af1a82809b1729.
Installation exited zero. Fourteen checks against installed modules passed in
29.50seconds, including exact multiline Git message preservation, owner-file
isolation and owned publication. All16original schedules are active at7200seconds;
owner queue and four sessions survived. Settings were checked by metadata only.
Proof: out/checks/project-task-1.0.103-install-preservation.json. Local control
acknowledgedv1.0.103, instance76aa033a66af45f38112ffed768ead7b; free mode verified
and existing Kertex work resumed. WSP HEAD remains54a5c07: its live commit and
factual project acceptance remain unverified, so no new delivery is counted.
The pre-update false blocker also appears in reportc3ec23ef47e24f278b444ebf65862849;
maintenance interruption19fcdc5d304248c2a199ef20d43686f9 is not a completed run.

1.0.104 was not installed. Windows CI passed; two fresh Linux runners failed before tests on temporary DNS resolution of azure.archive.ubuntu.com while installing Tcl. The correction probes the actual Tcl interpreter first, otherwise uses signed official Ubuntu repositories through a temporary APT source list and probes again before running all tests. Repository signatures remain enforced. The corrected release is1.0.105; runtime owner-file protection is unchanged. Candidate1.0.104 is prerelease.
