# OVL-M02 WP1 verification record

**Date:** 2026-10-10
**Status:** Initial testing foundation complete; WP1 remains open.
**Environment:** Windows, Python 3.12, project virtual environment.

## Delivered and verified

- Controlled lint/build/full-offline-test pre-commit stages, in order.
- Canonical commands shared by developer checks and independent CI.
- Windows/Linux CI definition retaining wheel and JUnit test artifacts.
- Project-only collection, invalid test credentials, and an external socket
  guard. Local sockets remain usable for asyncio; local services need mocks.
- Headless Tcl fixtures for console commands, repairing three failing tests.
- Seventeen usage-resilience cases across Claude/Codex counter shapes.
- Four negative infrastructure tests for network isolation, invalid source,
  missing build dependencies, and first-failure propagation.
- Runtime repair: non-finite token input no longer raises OverflowError.

Baseline: 192 passed, 3 failed, 1 skipped when supplied test credentials.
Without credentials, baseline collection terminated on bridge configuration.
Final: 216 passed, 1 skipped. `python -m pre_commit run --all-files` passed
all three stages. Wheel build and pre-commit configuration validation passed.
JUnit output is retained locally at `out/checks/tests.xml` and will be uploaded
by CI. Hosted Windows/Linux execution is pending; no remote push was made.
The existing package license metadata emits a setuptools deprecation warning;
the build succeeds, and metadata migration remains separate maintenance work.

## Remaining WP1 gates

Full WSP applicability/disposition and traceability, source-style enforcement,
the common multi-step brain workflow harness, sanitized live protocol fixtures,
Linux shell-runner integration, and budgeted live provider verification remain
open. Offline tests do not establish live qualification or full REQ-OVL-001/002
acceptance. WP2 through WP5 have not started in this slice.

## Usage reserve

No Claude/Codex provider smoke turns or additional agents were launched.
Codex account readings moved from 10% to 13% used in the five-hour window and
19% to 20% used weekly during this work. At the last reading, 87% and 80%
remained respectively. This preserves headroom rather than guaranteeing the
cost of future scheduled runs. Existing schedules were unchanged.
