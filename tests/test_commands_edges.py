"""Edge cases of the /status, /quote and .env helpers in modules/commands.py."""

import datetime

import pytest

from modules import commands
from modules.commands import (
    _age,
    _format_reset,
    _format_tokens,
    _format_window,
    _friendly_local_time,
    format_brain_card,
    format_quote,
    format_status,
    format_status_all,
    set_env_value,
)
from modules.token_meter import TokenLedger, normalize_usage


# ------------------------------------------------------------------ .env file
def test_env_value_is_created_when_the_file_is_missing(tmp_path):
    path = tmp_path / ".env"
    set_env_value(path, "OVERLORD_BRAIN", "codex")
    assert path.read_text(encoding="utf-8") == "OVERLORD_BRAIN=codex\n"


def test_env_value_keeps_comments_ordering_and_crlf(tmp_path):
    path = tmp_path / ".env"
    path.write_bytes(b"# brain below\r\nOTHER=1\r\n#OVERLORD_BRAIN=commented\r\nOVERLORD_BRAIN=claude\r\n")
    set_env_value(path, "OVERLORD_BRAIN", "codex")
    assert path.read_bytes() == (
        b"# brain below\r\nOTHER=1\r\n#OVERLORD_BRAIN=commented\r\nOVERLORD_BRAIN=codex\r\n"
    )


def test_env_value_updates_every_duplicate_and_spaced_assignment(tmp_path):
    path = tmp_path / ".env"
    path.write_text("KEY = old\nOTHER=x\nKEY=older\n", encoding="utf-8")
    set_env_value(path, "KEY", "new")
    assert path.read_text(encoding="utf-8") == "KEY=new\nOTHER=x\nKEY=new\n"


def test_env_value_appends_without_disturbing_a_file_lacking_a_final_newline(tmp_path):
    path = tmp_path / ".env"
    path.write_text("A=1", encoding="utf-8")
    set_env_value(path, "B", "")
    assert path.read_text(encoding="utf-8") == "A=1\nB=\n"


def test_env_value_survives_equals_signs_and_unicode(tmp_path):
    path = tmp_path / ".env"
    set_env_value(path, "NOTE", "a=b=c — ✓")
    assert path.read_text(encoding="utf-8") == "NOTE=a=b=c — ✓\n"
    set_env_value(path, "NOTE", "plain")
    assert path.read_text(encoding="utf-8") == "NOTE=plain\n"


def test_env_value_does_not_match_a_longer_key(tmp_path):
    path = tmp_path / ".env"
    path.write_text("OVERLORD_BRAIN_EXTRA=1\n", encoding="utf-8")
    set_env_value(path, "OVERLORD_BRAIN", "codex")
    assert path.read_text(encoding="utf-8") == "OVERLORD_BRAIN_EXTRA=1\nOVERLORD_BRAIN=codex\n"


# ---------------------------------------------------------------------- time
def local(*args):
    return datetime.datetime(*args).astimezone()


def test_friendly_time_names_nearby_days():
    now = local(2026, 7, 15, 9, 0)
    assert _friendly_local_time(local(2026, 7, 15, 17, 5), now=now).startswith("Today at 5:05 PM")
    assert _friendly_local_time(local(2026, 7, 16, 0, 30), now=now).startswith("Tomorrow at 12:30 AM")
    assert _friendly_local_time(local(2026, 7, 14, 23, 59), now=now).startswith("Yesterday at 11:59 PM")


def test_friendly_time_uses_a_date_for_distant_days_without_a_leading_zero():
    now = local(2026, 7, 15, 9, 0)
    text = _friendly_local_time(local(2026, 8, 5, 8, 0), now=now)
    assert text.startswith("Wed, Aug 5 at 8:00 AM")


@pytest.mark.parametrize("value", [None, "", "   ", [], {}])
def test_reset_without_usable_input_is_none(value):
    assert _format_reset(value) is None


def test_reset_accepts_epoch_seconds_and_iso_strings():
    assert "at" in _format_reset(1_900_000_000)
    assert "at" in _format_reset("2030-03-04T05:06:07Z")
    assert "at" in _format_reset("2030-03-04T05:06:07")  # naive: treated as local


@pytest.mark.parametrize("value", [1e30, -1e30, float("inf")])
def test_absurd_epochs_are_dropped(value):
    assert _format_reset(value) is None


@pytest.mark.parametrize("value", ["0001-01-01T00:00:00Z", "9999-12-31T23:59:59Z"])
def test_dates_the_platform_cannot_localize_do_not_crash_status(value):
    # Windows raises OSError for these; /status must show the raw text instead.
    assert _format_reset(value)


def test_unparseable_reset_text_is_shown_as_given():
    assert _format_reset("when the moon is full") == "when the moon is full"


# ------------------------------------------------------------ window rendering
def test_window_shows_used_left_and_reset():
    text = _format_window("5-hour", {"used": 42.5, "gas": 57.5, "resets_at": "2030-01-01T00:00:00Z"})
    assert text.startswith("5-hour: 42.5% used, 57.5% left · resets ")


def test_window_without_a_left_figure_or_reset():
    assert _format_window("Weekly", {"used": 10}) == "Weekly: 10% used"


@pytest.mark.parametrize("window", [None, "x", {}, {"used": "lots"}, {"gas": 5}])
def test_unusable_windows_are_reported_unavailable(window):
    assert _format_window("Weekly", window) == "Weekly: unavailable"


def test_token_lines_cover_each_available_field():
    assert _format_tokens(None) is None
    assert _format_tokens({"totalTokens": "many"}) is None
    assert _format_tokens({"totalTokens": 1234}) == "Thread tokens: 1,234 cumulative"
    text = _format_tokens({"totalTokens": 1000, "lastTotalTokens": 500, "modelContextWindow": 2000})
    assert "Latest turn: 500 / 2,000 token window (25%)" in text
    assert "(100%)" in _format_tokens(
        {"totalTokens": 1, "lastTotalTokens": 9000, "modelContextWindow": 2000}
    )
    assert "Model context window: 2,000 tokens" in _format_tokens(
        {"totalTokens": 1, "modelContextWindow": 2000}
    )
    assert "token window" not in _format_tokens(
        {"totalTokens": 1, "lastTotalTokens": 5, "modelContextWindow": 0}
    )


# ----------------------------------------------------------- status rendering
def test_status_marks_standby_sessions_and_provider_details():
    text = format_status({
        "brain": "codex", "model": "gpt-x", "model_provider": "openai",
        "session_id": "saved", "turn_state": "idle", "effort": "high",
        "usage": {"plan_type": "plus", "session": {"used": 1, "gas": 99},
                  "weekly": {"used": 2, "gas": 98}},
        "usage_note": "Usage is from the last cached update.", "checked_at": 0,
    })
    for expected in ("Brain: codex", "Model: gpt-x", "Provider: openai", "Turn: idle",
                     "Effort: high", "Session: saved, not loaded", "Plan: plus",
                     "5-hour: 1% used, 99% left", "Weekly: 2% used, 98% left",
                     "last cached update", "Checked:"):
        assert expected in text, expected


def test_status_defaults_for_a_fresh_brain():
    text = format_status({})
    assert "Brain: unknown" in text and "Model: default" in text
    assert "Effort: default" in text and "Session: not started" in text
    assert "Usage: unavailable from this brain" in text
    assert "Turn:" not in text and "Checked:" not in text


def test_status_includes_the_token_block_only_with_recorded_prompts():
    ledger = TokenLedger()
    assert "Session tokens" not in format_status({"brain": "claude", "ledger": ledger})
    ledger.record(normalize_usage({"input_tokens": 10, "output_tokens": 5}, brain="claude"))
    assert "Session tokens: 15 over 1 prompt" in format_status({"brain": "claude", "ledger": ledger})
    assert "Session tokens" not in format_status({"brain": "claude", "ledger": "not a ledger"})


def test_status_all_lists_the_active_brain_first_and_labels_roles():
    text = format_status_all(
        {"codex": {"model": "gpt-x"}, "claude": {"model": "opus"}, "alpha": None}, "codex"
    )
    assert text.index("CODEX  •  ACTIVE") < text.index("ALPHA  •  STANDBY")
    assert text.index("ALPHA") < text.index("CLAUDE")  # the rest are alphabetical
    assert "Model: opus" in text and "Standby brains are shown from their last cached reading" in text


def test_brain_card_drops_the_status_header_and_brain_line():
    card = format_brain_card("claude", {"model": "opus", "brain": "ignored"}, "claude")
    assert card.splitlines()[0] == "CLAUDE  •  ACTIVE"
    assert "Overlord status" not in card and "Brain:" not in card
    assert "Model: opus" in card


def test_age_never_goes_negative_and_rolls_through_units():
    assert _age(100, now=50) == "just now"
    assert _age(0, now=45) == "45s ago"
    assert _age(0, now=600) == "10m ago"
    assert _age(0, now=3 * 3600) == "3h ago"


# --------------------------------------------------------------------- quote
def test_quote_with_exact_count_and_pending_context():
    text = format_quote(prompt_tokens=1234, source="exact", context_tokens=20_000,
                        model="opus", brain="claude")
    assert "1,234 input tokens (exact)" in text
    assert "With pending context: ~21.2k" in text
    assert text.splitlines()[-1] == "claude · opus"


def test_quote_estimates_are_flagged_and_defaults_are_filled_in():
    text = format_quote(prompt_tokens=10, source="estimate")
    assert "(estimated)" in text and "No extra context is queued" in text
    assert text.splitlines()[-1] == "brain · default · local estimate, ±10% is normal"


def test_help_text_and_valid_brains_agree():
    assert commands.VALID_BRAINS == ("claude", "codex", "free")
    for command in ("/help", "/status", "/stop", "/steer", "/brain", "/new", "/context",
                    "/compact", "/model", "/effort", "/tokens", "/quote", "/permissions"):
        assert command in commands.HELP_TEXT


def test_env_value_update_works_on_a_bom_prefixed_file(tmp_path):
    path = tmp_path / ".env"
    path.write_bytes(b"\xef\xbb\xbfOVERLORD_BRAIN=claude\r\nX=1\r\n")
    set_env_value(path, "OVERLORD_BRAIN", "codex")
    assert path.read_bytes() == b"OVERLORD_BRAIN=codex\r\nX=1\r\n"  # no duplicate key


def test_env_value_update_tolerates_an_ansi_saved_file(tmp_path):
    path = tmp_path / ".env"
    path.write_bytes(b"NAME=caf\xe9\n")
    set_env_value(path, "A", "1")
    assert path.read_bytes().decode("utf-8") == "NAME=café\nA=1\n"


def test_a_rolled_over_window_says_so_instead_of_quoting_an_old_reset():
    text = _format_window("5-hour", {"used": 0.0, "gas": 100.0,
                                     "resets_at": "2026-09-02T20:00:00Z", "reset_passed": True})
    assert text == "5-hour: 0% used, 100% left · window has reset"


def test_reset_has_passed_handles_odd_input():
    from modules.commands import reset_has_passed

    assert reset_has_passed("2000-01-01T00:00:00Z") is True
    assert reset_has_passed("2999-01-01T00:00:00Z") is False
    assert reset_has_passed("2000-01-01T00:00:00") is True  # naive means UTC
    for odd in (None, "", "soon", 5):
        assert reset_has_passed(odd) is False
