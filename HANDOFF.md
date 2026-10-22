# GUI chat continuation

Owner request: mirror Telegram chat in the desktop GUI, accept GUI chat input and mirror GUI-origin messages to Telegram. Finish and verify the workflow, then commit/tag/push as requested.

## Current state

This branch preserves partial GUI work, queue tests and scratch experiments. Worker commit cd3953c changed chat_requests to read bytes and corrected the truncate test; the worker reported 1,230 tests passing, but final review rejected GUI completion. It pushed v1.0.42 while source versions still declared 1.0.41. That tag/assets are preserved as a prerelease, not a completed stable GUI feature. Do not reuse that version.

Main 1.0.44 is merged here. Its canonical checks passed (1,256 tests, two platform/display skips), excluding this GUI branch's additional tests. The last 1.0.43 run passed both pytest and canonical checks but made no edits in 32 steps; it repeated discovery, emitted an empty-name call, then received empty replies and a fallback HTTP 400 before owner interruption. No GUI completion was established. The 1.0.44 wrapper validation prevents malformed call batches from entering history or executing valid siblings; never infer a missing tool name. It rejects ignored/wrongly typed tool parameters, preserves confirmed edit metadata across context trimming, and requires release tag/source versions to agree. Obtain/update a concrete plan and continue from existing code. Use run_python(code=...), python on PATH, or shell=powershell for PowerShell syntax. read_file uses start_line/line_count, not start/end. Avoid broad rediscovery.

## First verify queue byte offsets

Read modules/chat_requests.py and tests/test_chat_requests.py. Binary reading fixes CRLF conversion, but consumption still derives offsets by re-encoding decoded text. Invalid UTF-8 decoded with replacement can change byte length. Test valid Unicode, malformed bytes, CRLF, partial final records, two rapid messages, truncation and rotation; consume exact raw bytes through complete records. Do not fabricate deleted messages. The truncate-reset test correctly expects an empty list and zero offset after emptying the file.

## Remaining integration verification

Test bridge._chat_request_loop startup, consumption, processing errors and shutdown. It currently skips existing queue bytes at startup and advances offset before dispatch; verify the intended delivery behavior and avoid silent message loss on processing errors. _handle_gui_chat should echo once with mirror=False and dispatch as SOURCE_GUI. Test exactly-once owner/reply mirroring and commands.

_console_command_loop retries the one-argument action handler after TypeError from a two-argument call. Internal TypeError can duplicate side effects. Fix/test the actual call contract without catching internal handler errors as signature mismatches.

The console has input, _send_chat, _read_new_chat, formatting and --chat-request. Verify queue/transcript paths agree for installed bridge and tray-launched console. Test failed writes retain typed input, bounded transcript, partial JSONL/rotation, and actual Tk construction/send/receive. Preserve typing and existing handler compatibility. Passing the old suite alone does not verify the feature.

## Completion and scope

Run focused feature tests, then python tools/check.py all after final edits. Validate the owner-visible workflow, commit explicit owned paths and publish only when required functionality works. Keep HANDOFF.md and tmp_* experiments out of main/release integration. Preserve pre-existing wsp, out/ and tools/_dev_show.ps1; never sweep them in with git add . or -A. tmp_requests.jsonl is a saved queue reproduction fixture (13166be), not a release asset.
