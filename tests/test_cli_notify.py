"""tmux-based live delivery of worker reports into the terminal Overlord."""

import subprocess

import pytest

from modules import cli_notify

DIM = "\x1b[2m"


def completed(stdout="", returncode=0):
    return subprocess.CompletedProcess([], returncode, stdout=stdout, stderr="")


def fake_tmux(monkeypatch, responder):
    """Route every tmux call through *responder(args) -> CompletedProcess | None*."""
    calls = []

    def run(*args, timeout=3.0):
        calls.append(args)
        return responder(args)

    monkeypatch.setattr(cli_notify, "_run_tmux", run)
    return calls


# ----------------------------------------------------------------- feed file
def test_feed_blocks_are_appended_with_a_separator(tmp_path):
    feed = tmp_path / "nested" / "cli_feed.log"
    cli_notify.append_feed(feed, "\n\nfirst report\n\n")
    cli_notify.append_feed(feed, "second report")
    text = feed.read_text(encoding="utf-8")
    assert text == ("first report\n" + "-" * 60 + "\n") + ("second report\n" + "-" * 60 + "\n")


def test_feed_preserves_non_ascii_text(tmp_path):
    feed = tmp_path / "feed.log"
    cli_notify.append_feed(feed, "✅ [Chorus] finished — naïve café")
    assert "✅ [Chorus] finished — naïve café" in feed.read_text(encoding="utf-8")


# ------------------------------------------------------------ tmux detection
def test_tmux_availability_and_session_lookup(monkeypatch):
    calls = fake_tmux(monkeypatch, lambda args: completed(returncode=0))
    assert cli_notify.tmux_available() is True
    assert cli_notify.tmux_session_exists("overlord-claude") is True
    assert calls[-1] == ("has-session", "-t", "=overlord-claude")  # exact match, no prefix


def test_missing_tmux_or_session_reads_as_unavailable(monkeypatch):
    fake_tmux(monkeypatch, lambda args: None)
    assert cli_notify.tmux_available() is False
    assert cli_notify.tmux_session_exists("s") is False
    fake_tmux(monkeypatch, lambda args: completed(returncode=1))
    assert cli_notify.tmux_session_exists("s") is False


@pytest.mark.parametrize("error", [FileNotFoundError("tmux"), OSError("denied"),
                                   subprocess.TimeoutExpired("tmux", 3)])
def test_run_tmux_swallows_launch_failures(monkeypatch, error):
    def boom(*a, **k):
        raise error

    monkeypatch.setattr(cli_notify.subprocess, "run", boom)
    assert cli_notify._run_tmux("-V") is None


# -------------------------------------------------------------- idle detection
NBSP = " "


@pytest.mark.parametrize(
    "pane, expected",
    [
        (f"history\n❯{NBSP}\n", True),  # bare prompt
        (f"❯{NBSP}{DIM}Try \"fix the tests\"\x1b[0m\n", True),  # dim placeholder hint
        (f"old turn\n❯{NBSP}half typed\n", False),  # real text, no dim code
        ("no prompt anywhere\n", None),
        ("", None),
    ],
)
def test_idle_detection_reads_the_prompt_line(monkeypatch, pane, expected):
    fake_tmux(monkeypatch, lambda args: completed(stdout=pane))
    assert cli_notify.pane_input_is_idle("s") is expected


def test_the_bottom_most_prompt_decides(monkeypatch):
    pane = f"❯{NBSP}typed earlier\nreply\n❯{NBSP}\n"
    fake_tmux(monkeypatch, lambda args: completed(stdout=pane))
    assert cli_notify.pane_input_is_idle("s") is True


def test_unreadable_pane_is_unknown_not_idle(monkeypatch):
    fake_tmux(monkeypatch, lambda args: None)
    assert cli_notify.pane_input_is_idle("s") is None
    fake_tmux(monkeypatch, lambda args: completed(stdout="❯ ", returncode=1))
    assert cli_notify.pane_input_is_idle("s") is None


def test_the_brain_pane_is_pane_zero_of_an_exact_session(monkeypatch):
    calls = fake_tmux(monkeypatch, lambda args: completed(stdout=f"❯{NBSP}"))
    cli_notify.pane_input_is_idle("overlord-codex")
    assert calls[0] == ("capture-pane", "-e", "-p", "-t", "=overlord-codex.0")


# ----------------------------------------------------------------- injection
def test_inject_types_literally_then_presses_enter(monkeypatch):
    calls = fake_tmux(monkeypatch, lambda args: completed())
    assert cli_notify.inject_turn("s", "-rf worker report") is True
    assert calls == [
        ("send-keys", "-t", "=s.0", "-l", "--", "-rf worker report"),
        ("send-keys", "-t", "=s.0", "Enter"),
    ]


def test_multiline_text_is_refused_before_touching_tmux(monkeypatch):
    calls = fake_tmux(monkeypatch, lambda args: completed())
    with pytest.raises(ValueError, match="single-line"):
        cli_notify.inject_turn("s", "one\ntwo")
    assert calls == []


def test_failed_typing_never_presses_enter(monkeypatch):
    calls = fake_tmux(monkeypatch, lambda args: completed(returncode=1))
    assert cli_notify.inject_turn("s", "report") is False
    assert len(calls) == 1


def test_failed_enter_is_reported(monkeypatch):
    responses = iter([completed(), None])
    fake_tmux(monkeypatch, lambda args: next(responses))
    assert cli_notify.inject_turn("s", "report") is False
