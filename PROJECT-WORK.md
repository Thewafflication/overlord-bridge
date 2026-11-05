# Overlord project work

Overlord harness changes require an owner request or a demonstrated harness
failure. Overlord remains excluded from autonomous scheduled project work.
Use [AGENT-TASKS.md](AGENT-TASKS.md) for the shared execution workflow.

## Current contracts

- Owner instructions are in [AGENTS.md](AGENTS.md).
- Shared capabilities are in [CAPABILITIES.md](CAPABILITIES.md).
- Existing plans and deferred capabilities are in [ROADMAP.md](ROADMAP.md).
- Canonical checks are `python tools/check.py all`.
- The durable scheduled-project audit and exact continuation cursor are in
  `out/monitoring/overlord-project-work.json`.
- Project acceptance queues are described in [docs/project-tasks.md](docs/project-tasks.md).
- WFC and VB6 project work remain excluded from autonomous schedules.

## Task queue

### OVL-PROJECT-WORK-001 — Discoverable work for WSP adopters

- State: in-progress
- Requirement: Owner request for easy-to-find roadmaps and predefined agent
  prompts, implemented through WSP-PROC-0012.
- Product outcome: Adopting projects maintain PROJECT-WORK.md and AGENT-TASKS.md.
  Overlord loads both before planning and retains them through context trimming.
- Scope: Shared WSP templates/helper and Overlord discovery/adoption integration.
- Prerequisites: Publish the shared WSP revision before updating consumers.
- Acceptance commands: WSP common-tool tests using a Python interpreter with
  `wsp/tools/pdf/requirements.txt` installed, then `python tools/check.py all`.
- Retained checks: Initialization preview, paths with spaces, existing-file
  preservation, project-document preload and context-trimming regression tests.
- Publication: Publish the WSP change and pin its actual obtainable commit.
  Commit/push the Overlord integration and verify release CI before installation.
- Last attempt: Full WSP tests and Overlord's canonical checks passed. The hosted
  PDF check exposed a table overflow; its shortened description awaits hosted
  verification in WSP PR #5. Existing schedule edits are prepared for all 16
  projects, retaining their current handoffs and acceptance gates.
- Next action: Verify hosted WSP documentation, release/install the tested
  consumer, and acknowledge the prepared edits on existing schedules. Audit
  later worker reports for populated project-specific records and actual work.
- Completion evidence: See `out/checks/wsp-project-work-*` and WSP PR #5.

Completed task records retain their evidence. Remaining product tasks require
a concrete requirement, bounded outcome and acceptance commands before ready.
