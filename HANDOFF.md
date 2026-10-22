# GUI chat continuation

Owner request: mirror Telegram chat in the desktop GUI, accept GUI chat input, and mirror GUI-origin messages to Telegram. Finish implementation and validation, then commit, tag and push as requested. Do not claim completion with tests pending.

## Current state

This branch preserves partial GUI work from adbb751, 4bbdaf0 and 0295b75, plus main 1.0.38. No broad repository survey is needed. Main now reviews free-worker final claims against tool evidence; validation and commits must actually happen. Typing visibility was confirmed by the owner. GUI work remains unvalidated and unreleased.

## Start here: missing queue consumer

The last worker claimed it wired a chat polling loop but did not. bridge.py imports read_requests and sets _chat_request_path, but never defines or starts _chat_request_loop. Implement and start the consumer alongside existing bridge tasks. Reuse _handle_gui_chat so GUI messages echo to Telegram once with mirror=False and enter normal _dispatch_inbound as SOURCE_GUI. Test lifecycle, offsets, two rapid submissions, and shutdown. Existing _console_command_loop still handles buttons; preserve it.

modules/chat_requests.py now has append_request and read_requests; inspect actual signatures. tools/overlord_console.py now implements _send_chat, _read_new_chat and formatting helpers, plus --chat-request. Verify default queue paths match the installed bridge and tray-launched console. Test failed writes preserve typed input and transcript rendering stays bounded. Do not duplicate these methods.

modules/chat_mirror.py already supplies ChatMirror.append, read_since and iter_all. Test partial JSONL lines and truncation/rotation. bridge._dispatch_inbound already records owner messages, and TelegramHandler.send already has on_send/mirror hooks. Verify exactly-once mirroring for owner messages and replies, GUI commands, and compatibility with existing fake Telegram handlers that bypass __init__. Preserve typing behavior.

## Validation and completion

No GUI feature tests were written in the last attempt. Add focused tests for queue consumption, GUI submission, transcript formatting, exactly-once mirroring, partial records, two rapid messages and failure recovery. Run them, fix failures, then use .venv/Scripts/python.exe tools/check.py all. Main 1.0.38 passed 1,194 tests and one skip; this branch has not passed full validation. Syntax checks alone do not verify Tk construction or sending/receiving chat.

Finish the actual user workflow, run validation, and commit changes before final. Requested tags/pushes must be supported by actual command results; do not tag an incomplete feature. Preserve unrelated wsp/out/tools changes. Keep HANDOFF.md out of main/release integration (it is intentionally tracked only on this continuation branch).
