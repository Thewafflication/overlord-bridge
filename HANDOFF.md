# GUI chat continuation

Owner request: mirror Telegram chat in the desktop GUI, accept GUI chat input and mirror GUI-origin messages to Telegram. Finish the actual workflow and validation, then commit/tag/push as requested.

## Current state

This local branch holds partial GUI work from adbb751, 4bbdaf0, 0295b75 and c5fda2f, plus main 1.0.40. The last run repaired the 15 existing test failures, added/started _chat_request_loop, passed the existing 1,194-test suite and canonical checks, then committed. It exhausted its free pool before final review or publication. No focused GUI feature tests were added. The feature remains unreleased.

The worker accidentally used git add . and swept pre-existing out/ and tools/_dev_show.ps1 into c5fda2f. Cleanup commit a10ca51 removed only their tracking, preserving the files. Do not stage them again. Preserve wsp and all unrelated edits. Stage explicit owned paths only. Keep this HANDOFF out of main/release integration.

The last continuation attempt ended incomplete at step 292 without editing: it repeatedly lost source context. Main now retains this handoff and supports update_plan. Begin by recording a short plan: add focused queue/GUI tests, repair observed failures, validate, then commit/publish. Keep the plan current; do not repeat a broad source survey. Review feedback was evidence-limited: GUI code does exist, so verify it instead of assuming it must be recreated.

## Start here: verify behavior, add missing tests

Do not repeat a broad repository survey. The queue consumer now exists in bridge.py and starts alongside _console_command_loop. Review actual code and test behavior rather than reimplementing it. It skips existing queue bytes at startup, reads requests with offsets, echoes GUI messages once to Telegram and enters normal dispatch. Test startup, partial records, two rapid submissions, processing failures and shutdown; verify no message is silently lost or duplicated.

_review point_: _console_command_loop now catches TypeError from _run_console_action(action, payload) and retries the one-argument form. A TypeError inside a handler could cause a second execution. Test/fix this behavior without masking actual failures.

modules/chat_requests.py supplies append_request/read_requests. modules/chat_mirror.py supplies ChatMirror append/read_since/iter_all plus a NullChatMirror. tools/overlord_console.py already has chat input, rendering helpers, _send_chat, _read_new_chat and --chat-request. Verify paths agree for the tray-launched console and installed bridge. Test failed queue writes preserve typed input, transcript stays bounded, partial JSONL and rotation handling work, and owner/reply messages mirror exactly once.

TelegramHandler.send now tolerates missing on_send on test fakes; console tag setup tolerates missing chat_text on partial test objects. Preserve typing ownership/refresh behavior. Add real tests for the new queue/GUI workflow instead of relying only on old compatibility tests.

## Completion

Use python on PATH for commands (the project .venv interpreter is selected), run_python for Python code, and shell=powershell for PowerShell syntax. Avoid nested shells and Unix tail pipelines on Windows. Main 1.0.40 passed 1,217 tests and one skip. Run focused feature tests, then python tools/check.py all on the final branch. Exercise Tk construction and send/receive behavior before claiming the feature works. Revalidate after final edits, commit explicit paths, and perform requested publication only after the implementation is complete. Do not tag incomplete work.
