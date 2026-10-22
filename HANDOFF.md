# GUI chat continuation

Owner request: mirror Telegram chat in the desktop GUI, accept GUI chat input and mirror GUI-origin messages to Telegram. Finish and verify the workflow, then commit/tag/push as requested.

## Current state

Partial GUI work, queue tests and scratch files are preserved. cd3953c changed queue reading to bytes and fixed the truncate test, but GUI completion was rejected. Worker tag v1.0.42 used source versions 1.0.41; it remains a prerelease. Do not reuse it.

Main 1.0.45 is merged here. Its canonical checks passed (1,261 tests, one skip), excluding this GUI branch's additional tests. The last run reached 65 steps without edits, repeating passing tests, GUI discovery and invalid search arguments containing result metadata (ok). The owner interrupted it after repeated empty primary replies; fallback models also returned 404/400/429. No GUI completion was established.

The harness now requires a bounded plan-only progress phase after 12 steps without a confirmed file edit. Record confirmed findings and file/line locations, unresolved uncertainty and the next concrete action in explanation; this state survives trimming. Three invalid plans or pool exhaustion stop incomplete. No file/command tool executes during that phase. Do not manufacture edits for a read-only task. Normal work must still produce the requested implementation and verification.

The harness also rejects malformed call wrappers and ignored/wrongly typed parameters, preserves confirmed edit metadata, and verifies release tag/source versions. Continue from existing code; use run_python(code=...), python on PATH, or shell=powershell for PowerShell syntax. read_file uses start_line/line_count, not start/end. Arguments contain only schema fields: ok is tool RESULT metadata, never a search argument. Avoid broad rediscovery.

## First verify queue byte offsets

Read modules/chat_requests.py and tests/test_chat_requests.py. Binary reading fixes CRLF conversion, but consumption still derives offsets by re-encoding decoded text. Invalid UTF-8 decoded with replacement can change byte length. Test valid Unicode, malformed bytes, CRLF, partial final records, two rapid messages, truncation and rotation; consume exact raw bytes through complete records. Do not fabricate deleted messages. The truncate-reset test correctly expects an empty list and zero offset after emptying the file.

## Remaining integration verification

Test bridge._chat_request_loop startup, consumption, processing errors and shutdown. It currently skips existing queue bytes at startup and advances offset before dispatch; verify the intended delivery behavior and avoid silent message loss on processing errors. _handle_gui_chat should echo once with mirror=False and dispatch as SOURCE_GUI. Test exactly-once owner/reply mirroring and commands.

_console_command_loop retries the one-argument action handler after TypeError from a two-argument call. Internal TypeError can duplicate side effects. Fix/test the actual call contract without catching internal handler errors as signature mismatches.

The console has input, _send_chat, _read_new_chat, formatting and --chat-request. Verify queue/transcript paths agree for installed bridge and tray-launched console. Test failed writes retain typed input, bounded transcript, partial JSONL/rotation, and actual Tk construction/send/receive. Preserve typing and existing handler compatibility. Passing the old suite alone does not verify the feature.

## Completion and scope

Run focused feature tests, then python tools/check.py all after final edits. Validate the owner-visible workflow, commit explicit owned paths and publish only when required functionality works. Keep HANDOFF.md and tmp_* experiments out of main/release integration. Preserve pre-existing wsp, out/ and tools/_dev_show.ps1; never sweep them in with git add . or -A. tmp_requests.jsonl is a saved queue reproduction fixture (13166be), not a release asset.
