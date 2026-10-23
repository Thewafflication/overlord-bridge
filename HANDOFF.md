# GUI chat continuation

Owner request: mirror Telegram chat in the desktop GUI, accept GUI input and mirror GUI-origin messages to Telegram. Finish and verify, then commit/tag/push as requested.

## Current state

Partial GUI code, queue tests and scratch files are preserved. cd3953c changed queue reading to bytes and corrected the truncate test. Worker tag v1.0.42 used source versions 1.0.41; it remains a prerelease, not completed GUI functionality. Never reuse it.

Main 1.0.48 is merged here (canonical: 1,282 passed, one skip; excludes GUI additions). The last 1.0.47 run repaired its first oversized explanation, but ended incomplete at step 48 after repeated plan-shape/size failures. It made no edits. No GUI completion was established.

Plans now support 24 steps and 4,000 explanation characters under the existing 48,000-character input budget. Shape errors differ from count errors; size diagnostics give actual counts. Repair feedback and a valid example survive trimming. Record actual findings/locations and the next action, not example placeholders.

The harness retains completion challenges across reads/searches/listings, plan updates and unchanged writes; confirmed edits or successful commands reset them. Feedback survives trimming and progress planning. Valid final reports still receive review, including read-only work.

After 12 steps without a confirmed edit, a bounded plan-only phase requires findings, file/line locations, uncertainty and next action in explanation. Three invalid plans or pool exhaustion stop incomplete. No file/command action executes in that phase. Do not manufacture edits. Continue from known code rather than rediscovering broadly.

Use run_python(code=...), python on PATH, or shell=powershell for PowerShell. read_file uses start_line/line_count, not start/end. Arguments contain only schema fields: ok is tool RESULT metadata, never a search argument.

## Queue offsets first

Read modules/chat_requests.py and tests/test_chat_requests.py. Binary reading fixes CRLF conversion, but consumption still re-encodes decoded text. Invalid UTF-8 replacement can change byte length. Test exact raw-byte offsets for Unicode, malformed bytes, CRLF, partial records, rapid messages, truncation/rotation. Consume complete records without silent loss. The truncate test correctly expects no messages and offset zero after emptying the file.

## Integration verification

Test bridge._chat_request_loop startup, consumption, processing errors and shutdown. It skips existing bytes on startup and advances offset before dispatch: verify intended delivery and avoid silent loss. _handle_gui_chat must echo once with mirror=False and dispatch SOURCE_GUI. Test exactly-once owner/reply mirroring and commands.

_console_command_loop retries a one-argument handler after a two-argument TypeError; internal errors can duplicate side effects. Fix/test its call contract without catching internal TypeError as a signature mismatch.

The console has input, _send_chat, _read_new_chat, formatting and --chat-request. Verify installed/tray queue and transcript paths agree. Test failed writes retain input, bounded transcript, partial JSONL/rotation and actual Tk send/receive. Preserve typing and handler compatibility. Old tests passing alone do not verify this feature.

## Completion

Run focused feature tests, then python tools/check.py all after final edits. Verify the owner-visible workflow and commit explicit owned paths; publish when functionality works. Keep HANDOFF.md and tmp_* experiments out of main/release integration. Preserve pre-existing wsp, out/ and tools/_dev_show.ps1; never git add . or -A. tmp_requests.jsonl is a saved reproduction fixture (13166be), not a release asset.
