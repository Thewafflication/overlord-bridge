# OVL-M02 implementation checkpoint

**Content type:** Work and verification record

**Date:** 2026-10-11

**State:** In progress; development checkpoints, not a product release

The owner authorized implementation, local commits, tags and pushes while
preserving at least 30% of the five-hour Codex allowance for scheduled tasks.
No scheduled tasks or allowance reset credits were changed. All qualification
in this checkpoint is offline; provider model calls were not made by the tests.

## Requirement coverage

| Increment requirement | Implemented evidence | Required work still open |
| --- | --- | --- |
| REQ-OVL-001 conversation parity | Paired native question adapters, review/edit/cancel, routing, permission and interruption regressions; canonical Windows/Linux CI | Full live scenario, shared-terminal policy parity, restart and long-session qualification |
| REQ-OVL-002 usage | Counter resilience, malformed-value rejection, per-turn accounting checks, classifier uses a local endpoint | Live invoice/allowance reconciliation, comparable fresh context occupancy; opt-in context control costs are outside the turn ledger |
| REQ-OVL-003 permissions | Exact scoped grants, resolved paths, revoke races, bounded hashed audit, audit failure denies approval | Project/task grant persistence, shared Claude and worker parity, security acceptance review |
| REQ-OVL-004 user questions | Explicit request replies, stale callback handling, progress and whole-set review, edit/cancel, responsive Codex reader | Live Telegram acceptance, restart restoration and further accessibility review |
| REQ-OVL-005 context | Durable neutral checkpoints with previous-snapshot recovery, verified native compaction, uncertain-state guard, bounded stop controls | Structured objective/action reconciliation, measured automatic thresholds, shared-terminal compaction and live long-session qualification |
| REQ-OVL-006 free providers | Opt-in manual OpenRouter tool worker; current catalog checks, zero-price ceiling on every request, no paid fallback | Live qualification, refreshed capabilities/cooldowns, additional providers and conversational adapters |
| REQ-OVL-007 model choice | Local LLM prompt/context interpretation into qualified active-provider models; manual override, native refusal fallback, same-session paired tests | Native model catalog discovery, gas/privacy-aware cross-provider and worker routing, effort selection, curated live evaluation |

Every requirement remains an increment gate. Offline coverage does not turn a
missing live qualification into a pass. The owner requested releasing the latest
build as 1.0.6 on 2026-10-11; this does not close the remaining increment gates.
Annotated `increment/ovl-m02-*` tags identify reviewable development slices.

## WSP integration

WSP is pinned to release 1.4.0. The controlled inventory covers all 258 numbered
requirements and checks titles, source hashes, complete identifiers, checkout
revision and index gitlink. Every disposition review is pending. This inventory
is not approved tailoring, a deferral approval or a conformance declaration.
Canonical lint/build/test checks, pre-commit configuration and independent
Windows/Linux CI are implemented. Complete profile selection, requirement
dispositions, traceability, design/security/UX reviews and release records remain
open.

## Validation and development slices

The full local offline suite for the native model catalog guard produced 346
passes and one platform skip. Syntax checks and wheel build passed. Hosted
Windows/Linux checks passed through `37a50b6` on both Windows and Linux.
Canonical JUnit and wheel artifacts are retained under `out/checks/` locally and
uploaded by CI. No runtime logs or private conversations are test evidence.

Recent development checkpoints:

- `b31c7bf`: manual zero-price OpenRouter worker pilot.
- `1233b0d`: revoke pending/queued permission grants.
- `d04f0db`: WSP inventory and baseline drift gate.
- `e46d213`: local LLM per-prompt model routing.
- `bb4a1f1`: native context snapshots, disabled by default pending cost qualification.
- `be050fe`: multi-question review/edit/cancel.
- `ef22608`: bounded controls and uncertain compaction transport loss.
- `548062c`: bounded permission audit with fail-closed approval writes.
- `12c0cb3`: responsive Codex reader with ordered, cancellable operator requests.
- `37a50b6`: reject local classifier redirects and record remaining release gates.
- `311e752`: delayed approvals/questions cannot reopen prompts
  for the latest 256 completed turns; identifiers are scoped to their native thread.
- Native Codex model catalog: bounded visible-model discovery narrows qualified
  routing candidates; malformed catalogs retain the current model and single turn.

See [the increment plan](next-increment.md), [WSP adoption](../wsp-adoption.md),
and [the implementation decisions](../design/ovl-m02-decisions.md).
