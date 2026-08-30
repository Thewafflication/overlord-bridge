import importlib.util
from pathlib import Path


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
