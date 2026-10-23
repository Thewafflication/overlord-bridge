# GUI chat continuation

The GUI feature is completed and published as 1.0.51, main commit 29bbb2f. Main is merged into this branch. Do not repeat discovery or release the older worker commit/tag v1.0.50; its version guard failed correctly and that tag remains unchanged.

GUI input now goes through _handle_gui_chat, echoes to Telegram without duplicate transcript records, and uses the same command/turn path. Raw-byte queue boundaries preserve partial records. Durable receipts prevent normal restart replay, pause on receipt-write failure, and detect queue replacement/truncation. A crash between dispatch and receipt persistence can replay the last message; this is not transactional exactly-once delivery.

The console retains failed input, reads shared outbound messages, refreshes rotated transcripts and bounds both display and memory. Console handler compatibility is checked before execution so internal TypeError does not duplicate an action.

Validation: canonical checks passed locally with 1,304 tests and two skips. Main Windows/Linux CI passed. Real Tk tests passed. Installed preview accepted two rapid /help messages, displayed both inputs once and both replies, and did not replay after bridge restart. The signed 1.0.51 package passed signature verification and excludes this handoff and tmp_* experiments. Final signed install verification is recorded in the release notes when complete.

Owner-authorized local_control status/stop uses the installed run directory and requires an idle acknowledgement; manual Telegram /stop is unnecessary. Stop keeps the bridge alive. For bridge shutdown before installation use console-command.json action shutdown, verify exit, then install and restart hidden with run-windows.ps1.

Keep HANDOFF.md and tmp_* experiments out of main/release integration. Preserve pre-existing wsp, out/ and tools/_dev_show.ps1; stage explicit owned paths only. Production secrets and sessions are never manually read or printed.
