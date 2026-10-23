# Live worker evaluations

## 2026-10-23: contained command-loop check

The installed 1.0.55 free worker received an isolated Git repository under `out/evals/command-loop-20261023`. Its task was to fix a JSON-lines totals function, leave the three existing tests unchanged, run unittest, and commit locally. The fixture has no remote and must not be published as a product release.

The worker read both files, edited the function correctly, ran all three tests successfully, checked Git status, and staged the implementation. Independent verification also passed all three tests. The provider pool then became unavailable (rate limits, cooldowns and empty responses), so the worker correctly reported incomplete instead of claiming completion. The fixture's changes remain staged; no worker commit was made.

The run also exposed the tool name `run_python<|channel|>json`, which was rejected as unknown. The model recovered by using run_command, but the known mechanical wrapper should be normalized through the same approval and command-restriction path as the existing analysis/commentary wrappers.

Next evaluation step: after installing the wrapper fix and confirming provider availability, resume `Command-loop-eval` from the session in its latest installed worker report. Verify the unchanged tests, local commit and completion report independently. Continue from the staged work rather than recreating the fixture. The untracked Python cache is test output, not product source.

The wrapper fix is installed in 1.0.56 and independently verified in installed Python. A resume request is being submitted using the saved session and staged fixture; follow its current live status and latest report before dispatching another run. Provider unavailability remains a possible external blocker and must not be reported as successful completion.
