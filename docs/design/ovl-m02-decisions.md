# OVL-M02 implementation decisions

**Content type:** Design record

**Status:** Implemented engineering decisions; acceptance review pending

**Date:** 2026-10-10

## Session and context ownership

Claude and Codex keep their native resumable sessions. Compaction uses the
native operation and requires completion evidence. A Codex RPC acknowledgement
is not completion: both the context-compaction item and turn lifecycle must
settle. Timeout or transport loss remains uncertain and blocks new work in that
thread until reconciled or explicitly reset. Control deadlines keep stop/reset
commands responsive without claiming that an uncertain effect was undone.

The neutral JSON checkpoint retains bounded dialogue and seen markers, with an
atomic replacement and a recoverable previous snapshot. It is recovery and
handoff evidence, not a second conversation engine or a substitute for the
planned structured objective/action record. Interrupted work is not replayed
automatically.

Context occupancy must come from a native occupancy contract. Lifetime billing
totals do not measure a context window. Claude snapshot collection is explicitly
disabled by default: the [upstream SDK issue](https://github.com/anthropics/claude-agent-sdk-python/issues/1159)
reports invisible billable Bedrock calls. The opt-in control's costs require
provider-specific qualification and separate reconciliation.

## Permission and interactive request ownership

Session grants hash the complete screened request and provider/workspace
context. Changed arguments or resolved targets require approval again.
Off-limits screening precedes every approval mode. Revocation invalidates
pending callbacks immediately. Successful bridge-gate approval requires a
durable local audit event; denied/revoked actions remain denied if storage fails.
Audit records contain hashes and decision metadata rather than raw arguments.

The Codex reader processes RPC replies and lifecycle notifications independently
of operator waits. Interactive handlers are ordered, bound to their native
requests, and cancelled on turn end, disconnect, reset or query cancellation.
Foreign-thread requests are declined. Multi-question answers are submitted as
one reviewed set, with edits preserving native identifiers and cancellation
returning no partial answers. Pending requests are not restored on restart.

The latest 256 completed native turns are retained as thread-scoped tombstones.
Late permission/question requests for those turns are declined before operator
prompting, including when they wait behind another interactive handler. This is
a bounded in-process safeguard; it is not durable restart restoration.

## Provider admission and model routing

OpenRouter is a manual worker pilot. It requires explicit cloud opt-in, an exact
`:free` model with current zero input/output prices and advertised tools, and
the [provider zero-price ceiling](https://openrouter.ai/docs/guides/routing/provider-selection)
on every request. Provider fallback is disabled. Catalog eligibility is not live
qualification, so this provider is not automatically admitted to routing.

Per-prompt interpretation uses a local classifier with no tools, a strict JSON
response contract and a deadline. Initial endpoints must be loopback HTTP, and
HTTP redirects are rejected so classification cannot silently move to a cloud
endpoint. Deterministic validation limits selection to
operator-qualified model IDs for the active provider. Native selection happens
before the single user turn, retaining the native session. Classification or
native selection failure retains the current model. Routing does not overwrite
the saved manual selection. Live shared Claude terminals retain their own model
because their transport does not expose per-turn model control.

Model catalog discovery, quota-aware cross-provider routing and live quality
evaluation remain required work. There is no regex/keyword intent classifier in
the new conversation routing path. Existing worker recommendation heuristics
are not yet replaced by this pilot.
