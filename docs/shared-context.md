# Shared context across Claude, Codex and free mode

Overlord separates three kinds of context:

| Data | Shared surface | Lifetime |
| --- | --- | --- |
| Owner rules and operating instructions | Canonical `AGENTS.md` | Loaded when an engine is built |
| Recent Telegram conversation | `run/conversation.json` handoff | Bounded; cleared by `/new` |
| Preferences, project decisions and unfinished work | Shared memory store | Persists across engine switches, restarts and `/new` |

The configured `OVERLORD_INSTRUCTIONS_FILE` wins over the bridge's `AGENTS.md`.
Claude and Codex receive it through their existing developer/system instruction
interfaces; free mode now receives the same text in its system context. This
does not give free mode native file access or expand its execution tools.

Shared memory is a local, human-inspectable JSON file. Every owner turn reads a
fresh snapshot, so updating a note in one engine is visible to the next engine.
The bridge injects notes as stored context, not new owner instructions or proof
of verification. Recent worker results are saved automatically as explicitly
worker-reported claims, one latest note per worker/project. This does not turn a
worker's successful exit into independent verification of its conclusions.

The default store is `%LOCALAPPDATA%/Overlord/state/shared-memory.json` on Windows,
outside the replaceable installation, and `run/shared-memory.json` on other hosts.
Set `OVERLORD_SHARED_MEMORY_FILE` to choose another location. The running engine
receives the resolved path. The command examples below use an explicit local
store for illustration.

## Owner interaction

Examples of natural requests:

- "Remember that I prefer short replies unless I ask for details."
- "Remember for project X: the build fix is still unverified; next check is Y."
- "Show shared memory."
- "Update memory entry ID to say …"
- "Forget memory entry ID."

Free mode receives a `shared_memory` tool even without configured project folders.
Claude and Codex receive the absolute Python/helper/store paths and use the same
helper with their native command tools. A memory write is acknowledged only after
the tool or helper succeeds. New notes receive an ID; updating uses that ID, so
obsolete facts can be replaced rather than contradicted by another note.

The helper is also directly callable:

```text
python modules/shared_memory.py --store run/shared-memory.json list
python modules/shared_memory.py --store run/shared-memory.json remember --category preference --text "Concise replies by default"
python modules/shared_memory.py --store run/shared-memory.json remember --category project --id EXISTING_ID --text "Updated decision and next step"
python modules/shared_memory.py --store run/shared-memory.json forget --id EXISTING_ID
```

Use the paths supplied by the running bridge when its working directory differs
from its installation directory. Do not edit the JSON while an engine is writing
it. The helper serializes writes and replaces the file atomically. Corruption is
reported rather than silently discarded. Keep personal memory out of commits.

## Bounds and limitations

The store retains at most 100 notes, each at most 2,000 characters. Full stores
reject new notes rather than silently forgetting older facts. Prompt snapshots
are bounded to 16,000 characters, preferring owner preferences and recent notes;
omission is labelled and all stored notes remain inspectable through the helper.
Worker result previews may be truncated; the full existing worker report remains
the source for detailed inspection.

This shares Overlord's engine context, not separate desktop-app chats or a
provider's private memory. Existing older worker reports are not retroactively
imported. Native engine sessions can retain older snapshots in their own history;
the current snapshot is explicitly identified as superseding those copies.
Forgetting removes the active durable note; it does not erase native transcripts
or backups of conversations. Shared notes are sent to whichever configured engine
handles the turn, including the configured free provider.

## Validation on October 20, 2026

Full lint and wheel build passed; 1,135 offline tests passed and one skipped.
Coverage includes concurrent writers, persistence, updates and forgetting,
corruption preservation, bounded snapshots, fresh context in Claude/Codex turns,
free-mode tools without project folders, and worker report sharing.

In the live Telegram conversation, free mode saved a temporary project note.
After switching engines, Codex updated that same note through the helper; direct
inspection confirmed the file changed. An existing Codex model selection of
`all` initially prevented the test. Selecting the native catalog's default
`gpt-6.1-sol` exposed a resumed-session model override issue, fixed by explicitly
passing the selected model on each `turn/start` request.

Claude switched successfully but hit its session usage limit before executing
the memory test. Live Claude read/write verification therefore remains pending;
its prompt/helper integration is covered offline. No native conversation was
reset to conduct these tests.

After restoring free mode, a natural-language forget request successfully removed
the temporary note. Direct inspection confirmed the shared store was empty. The
owner's unsent Telegram draft was restored without being sent.
