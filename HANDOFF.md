# GUI chat continuation

Owner request: mirror Telegram chat in the desktop GUI, allow messages to be typed in the GUI, and mirror GUI-origin messages to Telegram. Finish implementation and validation, then commit, tag and push as requested.

## Current state

This branch contains incomplete GUI work preserved in adbb751 and 4bbdaf0, plus current main (1.0.37). No need to restart a broad repository survey. Main's worker checkpoint guard was fixed: successful tool work resets the checkpoint, so planning messages separated by real progress can continue. Typing visibility was confirmed by the owner. The GUI feature itself has not been validated or released.

## Start here

- tools/overlord_console.py: chat widgets and chat_mirror_path/chat_offset exist. _build_ui references self._send_chat, but that method is missing. poll calls self._read_new_chat, which is also missing. Finish these methods first; the window can currently fail during construction/polling. Check the Console.TEntry style reference against existing styles.
- modules/chat_mirror.py: ChatMirror.append(role, text, source), read_since(offset) returning (records, next_offset), and iter_all already exist. Review and test partial-line/offset/truncation handling rather than designing a second transcript mechanism.
- bridge.py: _dispatch_inbound accepts source; _handle_gui_chat reads payload['text'], echoes to Telegram with mirror=False, then dispatches as SOURCE_GUI. _run_console_action handles action='chat'. Check that _console_command_loop forwards the whole payload. Review duplicate owner/reply mirroring and command behavior.
- modules/telegram_handler.py: send has an on_send callback and mirror=False for GUI owner echoes. Test compatibility with existing fake handlers that bypass __init__, and preserve typing ownership/refresh behavior.

## Validation and completion

Add focused tests for transcript rendering, GUI submission payloads, exactly-once owner/reply mirroring and normal dispatch of GUI commands. Preserve typed input if command submission fails. Keep the transcript widget bounded and test polling of partial/new JSONL records. Check two rapid submissions are not silently lost.

Use the project .venv interpreter. Main's full offline suite passed for 1.0.37. After targeted tests pass, run .venv/Scripts/python.exe tools/check.py all for the final branch state. A syntax-only check does not establish that the Tk window can construct and send/receive chat. Finish remaining methods and verify the user workflow before declaring completion. Preserve unrelated wsp/out/tools changes.
