import sys
import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from modules.commands import (  # noqa: E402
    HELP_TEXT,
    _format_reset,
    format_status,
    set_env_value,
)


def test_help_lists_all_commands():
    assert "/help" in HELP_TEXT
    assert "/status" in HELP_TEXT
    assert "/stop" in HELP_TEXT
    assert "/steer" in HELP_TEXT
    assert "/brain" in HELP_TEXT
    assert "/new" in HELP_TEXT


def test_set_env_value_replaces_brain_without_touching_other_settings(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("TOKEN=keep\nOVERLORD_BRAIN=claude\n", encoding="utf-8")
    set_env_value(env_file, "OVERLORD_BRAIN", "codex")
    assert env_file.read_text(encoding="utf-8") == (
        "TOKEN=keep\nOVERLORD_BRAIN=codex\n"
    )


def test_format_status_includes_model_usage_and_context():
    text = format_status(
        {
            "brain": "codex",
            "model": "gpt-test",
            "model_provider": "openai",
            "session_id": "thread-1",
            "tokens": {
                "totalTokens": 10_000,
                "lastTotalTokens": 5_000,
                "modelContextWindow": 100_000,
            },
            "usage": {
                "plan_type": "plus",
                "session": {"used": 12.0, "gas": 88, "resets_at": None},
                "weekly": {"used": 34.0, "gas": 66, "resets_at": None},
            },
        }
    )

    assert "Brain: codex" in text
    assert "Model: gpt-test" in text
    assert "Turn: active" in format_status(
        {"brain": "codex", "model": "gpt-test", "turn_state": "active"}
    )
    assert "Thread tokens: 10,000 cumulative" in text
    assert "Latest turn: 5,000 / 100,000 token window (5%)" in text
    assert "5-hour: 12% used, 88% left" in text
    assert "Weekly: 34% used, 66% left" in text


def test_format_status_handles_unavailable_usage():
    text = format_status(
        {"brain": "claude", "model": "opus", "session_id": None, "usage": None}
    )
    assert "Session: not started" in text
    assert "Usage: unavailable from this brain" in text


def test_format_reset_converts_epoch_and_iso_to_local_friendly_time():
    epoch = 1_800_000_000
    iso = datetime.datetime.fromtimestamp(
        epoch, tz=datetime.timezone.utc
    ).isoformat()

    epoch_text = _format_reset(epoch)
    iso_text = _format_reset(iso)

    assert epoch_text == iso_text
    assert " at " in epoch_text
    assert epoch_text.endswith(
        datetime.datetime.fromtimestamp(epoch).astimezone().tzname()
    )
