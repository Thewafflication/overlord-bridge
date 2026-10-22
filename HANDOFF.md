# GUI chat continuation

Owner request: mirror Telegram chat in the desktop GUI, accept GUI chat input and mirror GUI-origin messages to Telegram. Finish and verify the workflow, then commit/tag/push as requested.

## Current state

This branch preserves partial GUI code and the latest unfinished tests/experiments (3de747a), plus main 1.0.41. The last worker created tests/test_chat_requests.py and scratch tmp_* files but did not finish a fix. Earlier existing tests passed, but new queue tests fail and the GUI feature is unreleased. Do not assume completion from the old suite.

Main now obtains a validated plan before project actions. Record known remaining steps, keep the plan current, and use targeted reads. Source reads now begin at the start, default to 6,000 characters and return next_line/next_column for continuation. Use python on PATH, run_python(code=...), or shell=powershell for PowerShell syntax. Do not repeatedly survey the repo.

## Start with queue tests and byte offsets

Read modules/chat_requests.py and tests/test_chat_requests.py. A concrete Windows bug is visible: read_requests opens in text mode, so CRLF becomes LF, then derives a byte offset from re-encoded text. That offset does not match the bytes on disk. Test and repair byte-based consumption, UTF-8 text, partial final records, two rapid messages, truncation and rotation. Keep the offset at the end of complete records and do not silently lose messages.

The new test_truncate_reset has an incorrect expectation: it empties the file, then expects the old messages to return. Correct the test to expect no messages and offset zero. Do not change production code to fabricate deleted messages. Scratch files tmp_p.jsonl, tmp_size.py, tmp_test_reader.py and tmp_testing.jsonl are experiments, not release assets.

## Remaining integration verification

bridge._chat_request_loop exists and starts alongside _console_command_loop. Test queue consumption, startup, processing errors and shutdown. _handle_gui_chat should echo once with mirror=False and dispatch as SOURCE_GUI. Test exactly-once owner/reply mirroring and GUI commands. _console_command_loop currently retries the one-argument action handler after TypeError; a TypeError inside the handler can cause duplicate execution. Fix/test the actual call contract.

The console already has chat input, _send_chat, _read_new_chat, formatting and --chat-request. Verify queue/transcript paths agree for the installed bridge and tray-launched console. Test that failed writes retain typed input, transcript remains bounded, partial JSONL and rotation work, and actual Tk construction and send/receive behave correctly. Preserve typing and existing handler compatibility.

## Completion and scope

Run focused feature tests, then python tools/check.py all on the final branch; main 1.0.41 passed 1,226 tests and one skip. Validate after final edits, commit explicit owned paths and perform requested publication only when the feature works. Keep HANDOFF.md and scratch experiments out of main/release integration. Preserve pre-existing wsp, out/ and tools/_dev_show.ps1. Never sweep them in with git add . or -A.
