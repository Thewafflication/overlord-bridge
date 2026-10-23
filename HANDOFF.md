# GUI chat continuation

Owner request: mirror Telegram chat in the GUI, accept GUI input and mirror GUI-origin messages to Telegram. Finish and verify, then commit/tag/push as requested.

## Current state

Main 1.0.49 is merged here (canonical: 1,291 passed, one skip; excludes GUI additions). Partial GUI code, queue tests and scratch files are preserved. GUI completion remains unverified.

Latest worker commit c13eafd changed consumption to len(raw), passed existing tests and was pushed with v1.0.50. Release staging failed correctly: source versions remain 1.0.49. Preserve the tag. After rejected completion the worker repeated discovery for roughly 40 steps; the supervisor stopped it locally and confirmed idle. Do not publish this as a completed GUI feature.

## Reproduced regression: fix first

In modules/chat_requests.py, len(raw) counts an incomplete suffix as consumed. Repro: write b'{"text":"one"}\n' then b'{"text":"two"}' without newline. First read returns one but advances to 29 bytes instead of 15. Append newline: the next read loses two. Derive consumption from the raw end of complete newline-terminated records BEFORE decoding, not all bytes read or re-encoded decoded text. Add a regression that proves the second message survives completion.

Also test exact offsets for Unicode, malformed UTF-8, CRLF, partial records, rapid messages, truncation and rotation. Consume complete records without silent loss. The truncate test correctly expects no messages and offset zero after emptying the file.

## Remaining integration verification

Test bridge._chat_request_loop startup, consumption, processing errors and shutdown. It skips existing bytes on startup and advances offset before dispatch: verify intended delivery and prevent silent loss. _handle_gui_chat must echo once with mirror=False and dispatch SOURCE_GUI. Test exactly-once owner/reply mirroring and commands.

_console_command_loop retries a one-argument handler after a two-argument TypeError; internal errors can duplicate side effects. Fix/test its call contract without treating internal TypeError as a signature mismatch.

Verify installed/tray queue and transcript paths agree. Test failed writes retain input, bounded transcript, partial JSONL/rotation and actual Tk send/receive. Preserve typing and handler compatibility. Existing tests passing alone do not verify this feature.

## Harness and workflow

Plan memory accepts 24 steps and 4,000 explanation characters under the 48,000-character input budget. Required progress phases record findings/locations, uncertainty and next action. Repair feedback includes specific fields and an example: replace placeholders with actual task state. Completion feedback survives reads and plan updates; confirmed edits or successful commands reset it. Read-only work needs no artificial edits.

Use run_python(code=...), python on PATH, or shell=powershell for PowerShell. read_file uses start_line/line_count. Only pass schema fields: ok is RESULT metadata, never a search argument. The supervisor has owner-authorized local status/stop control; manual Telegram /stop is unnecessary. Workers should finish the task, not self-stop as completion.

Run focused feature tests, then python tools/check.py all after final edits. Verify the owner-visible workflow and commit explicit owned paths before reporting done. Keep HANDOFF.md and tmp_* experiments out of main/release integration. Preserve pre-existing wsp, out/ and tools/_dev_show.ps1; never git add . or -A. tmp_requests.jsonl is a reproduction fixture, not a release asset. Older v1.0.42 remains a prerelease with mismatched source versions; do not reuse its version.
