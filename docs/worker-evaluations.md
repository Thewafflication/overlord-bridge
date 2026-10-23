# Live worker evaluations

## Latest completed work: native completion in 1.0.59

The verified 1.0.59 change is merged into main, tagged, published and installed. It removes copyable placeholder answers, provides a native finish_task tool and final alias, strengthens factual-report review, recovers explicit report/outcome terminal envelopes and explains assertion-based validation. All 156 focused free-worker checks and the canonical suite (1,341 passed, one skip) pass, as do Windows/Linux release CI.

The native completion path feeds the existing LLM evidence review, preserves matching tool-call/reply history after rejection and rejects mixed action/finish batches before actions. The installed candidate preview completed CSV-native-report in three steps: unittest passed all five tests, git log confirmed d899b04, and finish_task delivered a factual report accepted by completion review. Independent hashes confirmed all fixture files unchanged. The signed package's completion modules match that live-tested candidate byte-for-byte; installed Python validates version 1.0.59 and the native schema, and the reviewed report survived installation. No unfinished 1.0.59 implementation or installation remains.

The CSV implementation fixture is complete at d899b04 and passes all five unchanged tests when independently run with the worker's UTF-8 stdio environment. Its initial final report was the literal completion-template placeholder. Preview 1 returned factual report/outcome JSON but the old parser treated it as an unnamed tool; preview 2 recovered that envelope but its reviewer demanded standalone repetition of error assertions, followed by invalid-plan retries; preview 3 reached the commands correctly but invoked an unknown final tool and created FINAL_REPORT.json despite the read-only request. The third run was stopped with an idle acknowledgement. That untracked evaluation artifact is preserved, not product source. Source modules and tests in the fixture were not changed by the reviews.

Before the native-tool trial, the original preview was restored to stable 1.0.58. The current installed bridge now runs signed 1.0.59. Historical preview backups remain under out/checks/report-preview-workers58.py and out/checks/report-preview-output_text58.py; do not restore these older files over the current release. Latest successful metadata is worker_reports/latest/CSV-native-report.json. The completed fixture should not be redispatched as another implementation task.

## 2026-10-23: contained command-loop check

The installed 1.0.55 free worker received an isolated Git repository under `out/evals/command-loop-20261023`. Its task was to fix a JSON-lines totals function, leave the three existing tests unchanged, run unittest, and commit locally. The fixture has no remote and must not be published as a product release.

The worker read both files, edited the function correctly, ran all three tests successfully, checked Git status, and staged the implementation. Independent verification also passed all three tests. The provider pool then became unavailable (rate limits, cooldowns and empty responses), so the worker correctly reported incomplete instead of claiming completion. The fixture's changes remain staged; no worker commit was made.

The run also exposed the tool name `run_python<|channel|>json`, which was rejected as unknown. The model recovered by using run_command, but the known mechanical wrapper should be normalized through the same approval and command-restriction path as the existing analysis/commentary wrappers.

Next evaluation step: after installing the wrapper fix and confirming provider availability, resume `Command-loop-eval` from the session in its latest installed worker report. Verify the unchanged tests, local commit and completion report independently. Continue from the staged work rather than recreating the fixture. The untracked Python cache is test output, not product source.

The wrapper fix is installed in 1.0.56 and independently verified in installed Python. A resume request is being submitted using the saved session and staged fixture; follow its current live status and latest report before dispatching another run. Provider unavailability remains a possible external blocker and must not be reported as successful completion.

Resume progress: the 1.0.56 worker reran the tests and committed totals.py as `57b79f3`. Independent verification passed all three unchanged tests, and the test file matches the seed commit. Its completion reviewer rejected a placeholder final summary and the worker continued; monitor this existing run rather than dispatching a duplicate. A local commit is verified, but a successful final worker report is not yet verified.

Completion: the resumed worker subsequently supplied an actual summary and finished successfully after seven steps. The bridge recorded the finished report in its active free thread. The implementation, unchanged tests and local commit were independently verified. Do not resume this completed fixture again; use a new bounded evaluation for further command-loop testing.

Next substantive issue: upgrading 1.0.55 to 1.0.56 removed the installed worker_reports/latest report needed for resume. The installer Copy-State helper preserves configuration, instructions, roster and session pins but not worker reports. The evaluation resumed using the session identifier retained from the prior inspection. Investigate upgrade preservation of worker reports and any associated worker continuation state; use synthetic fixtures to test preservation and avoid reading real credentials.

Resolved in 1.0.58: the Windows lifecycle now preserves the default worker_reports tree and includes hidden session pins. The first report-preservation release, 1.0.57, exposed the older hidden-pin scan problem in Linux CI; its tag was preserved and 1.0.58 fixed that scan. Windows/Linux CI now pass. Real signed upgrades preserved the completed evaluation's latest report and event history byte-for-byte, and a synthetic hidden pin survived with content and attributes intact. Test pin fixtures were removed afterward. The installed bridge was restarted; do not rerun the completed evaluation or repeat this resolved investigation without new evidence.

## 2026-10-23: CSV CLI and path handling

`CSV-cli-eval` is running in the isolated Git fixture `out/evals/csv-cli-20261023`, using installed 1.0.58. It must fix a standard-library CSV CLI, preserve five existing tests, run unittest and commit locally. Coverage includes paths containing spaces and Unicode, quoted CSV categories, aggregation, blank rows, invalid amounts and missing-file errors. The seeded baseline had four failing tests and one passing test. The fixture has no remote, ignores Python cache output and must not produce a product release.

The bridge accepted the dispatch and began normal tool execution. Follow this existing worker's live status and latest installed report before starting another evaluation; do not edit its fixture while running. `out/evals/current.json` retains its local session/folder metadata. Independently verify tests, unchanged test source, implementation commit and final report when it finishes. A pending healthy evaluation does not require an owner notification or a forced source change.
