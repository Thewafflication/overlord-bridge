# Reproducible project checks

**Scope:** OVL-M02 WP1, initial offline Python test inventory.

Use Python 3.12 in a project virtual environment. Provision dependencies first:

```text
python -m pip install -r requirements-dev.txt
python tools/check.py all
```

The same lint, build, and test commands run in Windows/Linux CI and the
controlled pre-commit configuration. Lint currently checks Python syntax;
full WSP source-style and traceability enforcement remain open WP1 work.
Build creates the distributable wheel without downloading build dependencies.
Missing tools fail the check. Test executes every Python test under `tests/`,
excluding explicitly marked live tests, and writes `out/checks/tests.xml`.
The Linux shell cold-resume script is outside this initial Python inventory;
add its separate platform runner before claiming full workflow verification.

Pytest collection is restricted to project tests, avoiding vendor/submodule
test discovery. Tests receive invalid Telegram placeholders before importing
the bridge. They do not need operator credentials. Console command tests use
a headless Tcl interpreter; Python must include Tk/Tcl even without a display.
Existing Windows-only tests declare their platform skips.
Offline tests reject external socket connections, so an accidentally unmocked
cloud provider or Telegram call fails. Local sockets remain available for
Windows asyncio internals; local-provider calls still require explicit mocks.

Activate the environment, then validate and install the optional local hooks:

```text
python -m pre_commit validate-config
python -m pre_commit install
```

Preserve existing hooks and reconcile any configured hooks path before
installation. Hooks execute the entire declared inventory, including on
documentation changes, and stop on the first failure. CI runs independently.

These checks launch no model turns. Sanitized real-provider protocol replay,
live qualification, full traceability, and WSP adoption dispositions are still
required before the increment can close. Do not equate mock/offline results
with live Claude/Codex qualification.
