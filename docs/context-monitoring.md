# Context monitoring and compaction

`/context` shows the active engine's latest usable context observation, its
timestamp, and the configured warning/compaction thresholds. Checkpoint and
handoff details are available in an expandable log block. `/compact` remains
available for manual compaction while idle.

```text
OVERLORD_CONTEXT_WARN_PERCENT=75
OVERLORD_CONTEXT_COMPACT_PERCENT=85
OVERLORD_CONTEXT_AUTO_COMPACT=1
OVERLORD_CLAUDE_CONTEXT_SNAPSHOTS=1
```

Automatic compaction is off by default for installations that have not enabled
it. The owner's running Windows bridge has the above settings enabled.

## What is measured

| Engine | Measurement | Limitation |
| --- | --- | --- |
| Claude | Native context usage control snapshot | Requires snapshot opt-in and SDK/provider support; collection is not assumed free on every provider |
| Codex | Last native request token usage / reported model window | A last observation, not a continuously updated current-context guarantee; cumulative billing is never used |
| Free | Retained chat characters / configured history character budget | This is the bridge's history budget, not the provider's full model window; the last conversation request's reported input tokens are shown separately when available |

Native observations older than ten minutes or belonging to another session or
model are ignored. Invalid or unavailable readings remain unknown and do not
trigger automatic compaction. Free mode computes its retained-history size
directly. Extra instructions, tools and shared memory are outside its local
history character budget.

## Behavior

The bridge checks after a successful owner turn. At 75% it warns once. At 85%,
when enabled, it checkpoints the shared conversation and compacts between turns.
If the first observation is already above 85%, it goes directly to the automatic
compaction notice. It never interrupts a tool operation to compact. Pending
approvals or questions defer the attempt. Typing indication stays active while
compaction runs. Session identity, permission grants and durable shared memory
are preserved.

Claude and Codex use their existing native compaction mechanisms and require
completion evidence. Free mode uses one tool-free model summary, preserving the
latest exchange, with the original transcript saved as `.session.precompact` next
to `.session.free`. Empty, non-reducing, failed or unsaved summaries are rejected.
Summary generation consumes free-provider requests/tokens and can fail when its
provider budget is unavailable. Existing hard history bounds still apply.

Compaction can lose details; retain important preferences, decisions and unfinished
work in shared memory. A summary is conversation context, not a verified source.
An automatic attempt is not repeated continuously if it fails or remains above
the threshold. Alerts rearm once pressure drops below 70%; `/compact` allows an
explicit retry. The thresholds are configurable, not claims about every model's
ideal operating point.

## Validation on October 20, 2026

The live Telegram free-mode history was 21,456/24,000 characters (89.4%). After a
normal reply, the threshold observation was 21,711 characters (90.5%). The bridge
automatically compacted it to 2,054 characters (8.6%). Direct file inspection
confirmed four retained messages and the pre-compaction transcript backup.

Offline tests cover threshold deduplication/rearming, warning-only mode, stale or
mismatched readings, invalid counters, using Codex's last observation rather
than cumulative totals, approval deferral, checkpoint-before-compaction ordering,
preservation of the latest free-mode exchange, and rejection of non-reducing
summaries. Existing native compaction tests check completion evidence and session
preservation. Live automatic Claude/Codex threshold compaction has not been forced
for this change; Claude's account was usage-limited during the preceding feature
validation.
