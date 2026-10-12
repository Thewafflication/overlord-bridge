import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from modules.version import display_version  # noqa: E402


MODULE_PATH = Path(__file__).resolve().parent.parent / "tools" / "overlord_console.py"
SPEC = importlib.util.spec_from_file_location("overlord_console", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_log_lines_are_classified_for_rich_text():
    assert MODULE.level_for_line("2026 overlord INFO Ready") == "info"
    assert MODULE.level_for_line("2026 overlord WARNING Retry") == "warning"
    assert MODULE.level_for_line("2026 overlord ERROR Failed") == "error"
    assert MODULE.level_for_line("plain output") == "plain"


def test_brain_status_card_marks_active_brain_and_usage():
    text = MODULE.format_brain_summary(
        "claude",
        {
            "model": "opus",
            "session_id": "session-1",
            "usage": {
                "session": {"used": 18, "gas": 82},
                "weekly": {"used": 36, "gas": 64},
            },
        },
        "claude",
    )

    assert "CLAUDE  •  ACTIVE" in text
    assert "Model: opus" in text
    assert "5-hour: 18% used, 82% left" in text
    assert "Weekly: 36% used, 64% left" in text


def test_brain_status_card_marks_inactive_brain_standby():
    text = MODULE.format_brain_summary("codex", {}, "claude")
    assert "CODEX  •  STANDBY" in text
    assert "Usage: unavailable" in text


def test_status_cards_show_effort_and_token_totals():
    text = MODULE.format_brain_summary(
        "claude", {"model": "opus", "effort": "high", "session_id": "s"}, "claude"
    )
    assert "Effort: high" in text
    # The card is the same renderer Telegram uses, minus its header lines.
    assert not text.startswith("🤖")
    assert "Brain: claude" not in text


def test_a_standby_brain_says_its_session_is_saved_not_running():
    text = MODULE.format_brain_summary("codex", {"session_id": "saved"}, "claude")
    assert "Session: saved, not loaded" in text


def _console(tmp_path, command_path):
    """A console instance without a Tk mainloop, for the file-writing path."""
    console = MODULE.OverlordConsole.__new__(MODULE.OverlordConsole)
    console.command_path = command_path
    console.interpreter = MODULE.tk.Tcl()
    console.action_status = MODULE.tk.StringVar(
        master=console.interpreter, value=""
    )
    console.root = type("Root", (), {"after": lambda self, *a: None})()
    return console


def test_a_status_button_writes_a_command_the_bridge_can_read(tmp_path):
    target = tmp_path / "console-command.json"
    console = _console(tmp_path, target)
    console.send_command("refresh_all")
    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload["action"] == "refresh_all"
    assert isinstance(payload["at"], int)
    assert "refresh all" in console.action_status.get()


def test_stop_overlord_writes_shutdown_request(tmp_path):
    target = tmp_path / "console-command.json"
    console = _console(tmp_path, target)
    console.send_command("shutdown")
    assert json.loads(target.read_text(encoding="utf-8"))["action"] == "shutdown"


def test_pressing_the_same_button_twice_is_two_distinct_requests(tmp_path, monkeypatch):
    monkeypatch.setattr(MODULE.time, "time_ns", lambda: 100)
    target = tmp_path / "console-command.json"
    console = _console(tmp_path, target)
    console.send_command("refresh_status")
    first = json.loads(target.read_text(encoding="utf-8"))["at"]
    console.send_command("refresh_status")
    second = json.loads(target.read_text(encoding="utf-8"))["at"]
    assert second > first


def test_without_a_bridge_the_buttons_say_so_instead_of_failing(tmp_path):
    console = _console(tmp_path, None)
    console.send_command("refresh_status")
    assert console.action_status.get() == "No bridge connected"


def test_the_console_knows_its_own_version():
    assert display_version().startswith("v")
