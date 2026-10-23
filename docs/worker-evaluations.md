# Live worker evaluations

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
