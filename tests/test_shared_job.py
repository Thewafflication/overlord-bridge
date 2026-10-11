"""Shared Claude job discovery, transcript parsing, and terminal-input safety."""

import json
import os
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from modules import shared_job
from modules.shared_job import DELIVERED_PENDING, SharedJob


def write_transcript(path: Path, *records):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")
    return path


def user(text):
    return {"type": "user", "message": {"content": text}}


def tool_result():
    return {"type": "user", "message": {"content": [{"type": "tool_result", "content": "ok"}]}}


def assistant(text, stop=None):
    message = {"content": [{"type": "text", "text": text}]}
    if stop:
        message["stop_reason"] = stop
    return {"type": "assistant", "message": message}


# ----------------------------------------------------------- reply extraction
def test_reply_is_not_complete_until_the_assistant_ends_its_turn(tmp_path):
    transcript = write_transcript(
        tmp_path / "t.jsonl",
        user("deploy it"),
        assistant("On it.", "tool_use"),
        tool_result(),
        assistant("Halfway there", "tool_use"),
    )
    reply, done = shared_job._reply_status(transcript, "deploy it")
    assert reply == "On it.\n\nHalfway there" and done is False


def test_final_answer_spread_over_several_end_turn_records_is_kept_whole(tmp_path):
    transcript = write_transcript(
        tmp_path / "t.jsonl",
        user("q"),
        assistant("", "end_turn"),  # a thinking record carries no visible text
        assistant("The visible answer", "end_turn"),
    )
    assert shared_job._reply_status(transcript, "q") == ("The visible answer", True)


def test_the_next_human_turn_closes_ours_and_is_not_included(tmp_path):
    transcript = write_transcript(
        tmp_path / "t.jsonl",
        user("first"),
        assistant("answer one"),
        user("second"),
        assistant("answer two", "end_turn"),
    )
    assert shared_job._reply_status(transcript, "first") == ("answer one", True)
    assert shared_job._reply_status(transcript, "second") == ("answer two", True)


def test_replayed_history_resolves_to_the_latest_copy_of_the_message(tmp_path):
    transcript = write_transcript(
        tmp_path / "t.jsonl",
        user("status?"), assistant("old answer", "end_turn"),
        user("other"), assistant("noise", "end_turn"),
        user("status?"), assistant("new answer", "end_turn"),
    )
    assert shared_job._reply_status(transcript, "status?") == ("new answer", True)


def test_message_matching_ignores_whitespace_and_tolerates_bad_lines(tmp_path):
    path = tmp_path / "t.jsonl"
    path.write_text(
        "\n   \nnot json\n"
        + json.dumps(user("a   multi\n line   message")) + "\n"
        + json.dumps(assistant("fine", "end_turn")) + "\n",
        encoding="utf-8",
    )
    assert shared_job._reply_status(path, "a multi line\nmessage") == ("fine", True)


def test_missing_transcript_or_message_yields_nothing(tmp_path):
    assert shared_job._reply_status(tmp_path / "absent.jsonl", "x") == (None, False)
    transcript = write_transcript(tmp_path / "t.jsonl", user("other"))
    assert shared_job._reply_status(transcript, "x") == (None, False)
    assert shared_job._reply_to(transcript, "other") is None


# --------------------------------------------------------- transcript location
@pytest.fixture
def projects(tmp_path, monkeypatch):
    root = tmp_path / "projects"
    root.mkdir()
    monkeypatch.setattr(shared_job, "PROJECTS_DIR", root)
    return root


def test_transcript_found_by_session_id_even_after_the_cwd_moved(projects):
    original = write_transcript(projects / "-home-ben" / "sid-1.jsonl", user("x"))
    job = SharedJob("job", "sid-1", "/home/ben/worktrees/fix")  # cwd wandered
    assert shared_job.transcript_for(job) == original


def test_newest_copy_of_a_resumed_session_wins(projects):
    old = write_transcript(projects / "-a" / "sid-1.jsonl", user("x"))
    new = write_transcript(projects / "-b" / "sid-1.jsonl", user("x"))
    os.utime(old, (1, 1))
    os.utime(new, (2_000_000_000, 2_000_000_000))
    assert shared_job.transcript_for(SharedJob("job", "sid-1", "/nowhere")) == new


def test_unwritten_transcript_resolves_to_the_expected_path_to_tail(projects):
    (projects / "-home-ben").mkdir()
    job = SharedJob("job", "sid-9", "/home/ben")
    assert shared_job.transcript_for(job) == projects / "-home-ben" / "sid-9.jsonl"
    assert shared_job.transcript_for(SharedJob("job", "sid-9", "/no/such/dir")) is None


def test_without_a_session_id_the_newest_transcript_in_the_cwd_dir_is_used(projects):
    older = write_transcript(projects / "-home-ben" / "a.jsonl", user("x"))
    newer = write_transcript(projects / "-home-ben" / "b.jsonl", user("x"))
    os.utime(older, (1, 1))
    os.utime(newer, (2_000_000_000, 2_000_000_000))
    assert shared_job.transcript_for(SharedJob("job", "", "/home/ben")) == newer
    assert shared_job.transcript_for(SharedJob("job", "", "")) is None
    assert shared_job.transcript_for(SharedJob("job", "", "/elsewhere")) is None


def test_poll_helpers_re_resolve_the_transcript_each_call(projects):
    job = SharedJob("job", "sid-1", "/home/ben")
    assert shared_job.poll_reply(job, "hi") is None
    assert shared_job.poll_reply_status(job, "hi") == (None, False)
    write_transcript(projects / "-home-ben" / "sid-1.jsonl", user("hi"), assistant("yo", "end_turn"))
    assert shared_job.poll_reply(job, "hi") == "yo"
    assert shared_job.poll_reply_status(job, "hi") == ("yo", True)


# ----------------------------------------------------------------- discovery
def test_pin_helpers_name_sibling_files():
    pin = shared_job.default_session_file("codex")
    assert pin.name == ".session.codex"
    assert shared_job.sidecar_for(pin).name == ".session.codex.job"


def roster(monkeypatch, *entries):
    monkeypatch.setattr(shared_job, "_roster", lambda: list(entries))


def test_live_job_matches_the_pin_against_live_background_sessions(tmp_path, monkeypatch):
    pin = tmp_path / ".session.claude"
    pin.write_text("sid-live\n", encoding="utf-8")
    roster(
        monkeypatch,
        {"id": "dead", "kind": "background", "status": "exited", "sessionId": "sid-live"},
        {"id": "fg", "kind": "foreground", "sessionId": "sid-live"},
        {"id": "job-1", "kind": "background", "status": "running",
         "sessionId": "sid-live", "cwd": "/work"},
    )
    assert shared_job.live_job(pin) == SharedJob("job-1", "sid-live", "/work")


def test_live_job_is_none_without_a_pin_or_a_matching_job(tmp_path, monkeypatch):
    roster(monkeypatch, {"id": "j", "kind": "background", "sessionId": "other"})
    assert shared_job.live_job(tmp_path / "missing") is None
    (tmp_path / "empty").write_text("  \n", encoding="utf-8")
    assert shared_job.live_job(tmp_path / "empty") is None
    pin = tmp_path / "pin"
    pin.write_text("sid-live", encoding="utf-8")
    assert shared_job.live_job(pin) is None


def test_sidecar_fallback_requires_a_consistent_live_job(tmp_path, monkeypatch):
    pin = tmp_path / "pin"
    pin.write_text("sid-live", encoding="utf-8")
    sidecar = shared_job.sidecar_for(pin)
    jobs = {"id": "job-7", "kind": "background", "status": "running", "cwd": "/w",
            "sessionId": "different"}
    roster(monkeypatch, jobs)
    sidecar.write_text("job-7:sid-live", encoding="utf-8")
    assert shared_job.live_job(pin) == SharedJob("job-7", "sid-live", "/w")
    sidecar.write_text("job-7:stale-sid", encoding="utf-8")  # frozen transcript: refuse
    assert shared_job.live_job(pin) is None
    sidecar.write_text(":sid-live", encoding="utf-8")
    assert shared_job.live_job(pin) is None


@pytest.mark.parametrize(
    "result",
    [
        subprocess.CompletedProcess([], 1, stdout="[]", stderr=""),
        subprocess.CompletedProcess([], 0, stdout="not json", stderr=""),
        subprocess.CompletedProcess([], 0, stdout='{"a": 1}', stderr=""),
        subprocess.CompletedProcess([], 0, stdout="", stderr=""),
    ],
)
def test_roster_failures_degrade_to_an_empty_list(monkeypatch, result):
    monkeypatch.setattr(shared_job.subprocess, "run", lambda *a, **k: result)
    assert shared_job._roster() == []


def test_roster_survives_a_missing_claude_binary(monkeypatch):
    def boom(*a, **k):
        raise FileNotFoundError("claude")

    monkeypatch.setattr(shared_job.subprocess, "run", boom)
    assert shared_job._roster() == []


def test_roster_parses_the_json_list(monkeypatch):
    done = subprocess.CompletedProcess([], 0, stdout='[{"id": "j"}]', stderr="")
    monkeypatch.setattr(shared_job.subprocess, "run", lambda *a, **k: done)
    assert shared_job._roster() == [{"id": "j"}]


# ------------------------------------------------------ input box detection
RULE = "─" * 40
STATUS = "Model: opus   Ctx: 12%   Session: abc"


def screen(*lines):
    return "\r\n".join(lines)


def test_empty_input_box_is_safe_even_when_history_shows_prompts():
    frame = screen("❯ an old question", "some reply", RULE, "❯ ", RULE, STATUS)
    assert shared_job.input_line_is_idle(frame) is True
    assert shared_job._input_box_state(frame) == ("empty", "")


def test_text_in_the_box_means_a_person_is_mid_sentence():
    frame = screen("history", RULE, "❯ half a sen", RULE, STATUS)
    assert shared_job.input_line_is_idle(frame) is False
    assert shared_job._input_box_state(frame) == ("text", "half a sen")


def test_queued_message_hint_is_chrome_not_typed_text():
    frame = screen(RULE, "❯ Press up to edit queued messages", RULE, STATUS)
    assert shared_job.input_line_is_idle(frame) is True


def test_multiline_input_is_still_text():
    frame = screen(RULE, "❯ line one", "  line two", RULE, STATUS)
    state, typed = shared_job._input_box_state(frame)
    assert state == "text" and "line two" in typed


@pytest.mark.parametrize(
    "frame",
    [
        "",
        screen("Attaching…"),
        screen(RULE, "❯ hi", RULE),  # no status bar yet
        screen("❯ hi", RULE, STATUS),  # only one rule
        screen(RULE, "no prompt here", RULE, STATUS),
    ],
)
def test_an_unpainted_or_odd_frame_is_never_judged_idle(frame):
    assert shared_job.input_line_is_idle(frame) is None


def test_renderer_errors_fail_closed(monkeypatch):
    def boom(frame):
        raise RuntimeError("bad escape sequence")

    monkeypatch.setattr(shared_job, "_screen_lines", boom)
    assert shared_job.input_line_is_idle("anything") is None


def test_screen_helpers():
    assert shared_job._has_prompt("  ❯ hello") is True
    assert shared_job._has_prompt("nothing here") is False
    assert shared_job._is_rule(RULE) and not shared_job._is_rule("──")
    assert shared_job._is_status_bar(STATUS)
    assert not shared_job._is_status_bar("Model: mentioned in prose")
    assert shared_job._plain("\x1b[2mdim\x1b[0m\r") == "dim"


# -------------------------------------------------------------------- inject
class PtyHarness:
    """Stand-ins for pty/fcntl/termios, backed by an ordinary pipe."""

    def __init__(self, monkeypatch, tmp_path):
        read_end, write_end = os.pipe()
        self.read_end, self.write_end = read_end, write_end
        self.slave = os.dup(read_end)
        self.opened = []
        monkeypatch.setattr(shared_job, "PTY_ATTACH_SUPPORTED", True)
        monkeypatch.setattr(shared_job, "pty", SimpleNamespace(openpty=self._openpty))
        monkeypatch.setattr(shared_job, "fcntl", SimpleNamespace(ioctl=lambda *a: None))
        monkeypatch.setattr(shared_job, "termios", SimpleNamespace(TIOCSWINSZ=0))
        monkeypatch.setattr(shared_job, "_read_frame", lambda fd: "")
        monkeypatch.setattr(shared_job.time, "sleep", lambda s: None)
        transcript = tmp_path / "t.jsonl"
        transcript.write_text("", encoding="utf-8")
        monkeypatch.setattr(shared_job, "transcript_for", lambda job: transcript)
        self.transcript = transcript

    def _openpty(self):
        self.opened.append((self.write_end, self.slave))
        return self.write_end, self.slave

    def fds_closed(self):
        for fd in (self.write_end, self.slave):
            try:
                os.fstat(fd)
                return False
            except OSError:
                pass
        return True


class FakeProc:
    def __init__(self):
        self.terminated = False

    def terminate(self):
        self.terminated = True

    def wait(self, timeout=None):
        return 0

    def kill(self):
        pass


def test_attach_failure_returns_none_and_leaks_no_descriptors(monkeypatch, tmp_path):
    harness = PtyHarness(monkeypatch, tmp_path)

    def no_claude(*a, **k):
        raise FileNotFoundError("claude")

    monkeypatch.setattr(shared_job.subprocess, "Popen", no_claude)
    assert shared_job.inject(SharedJob("job", "sid", "/w"), "hello") is None
    assert harness.fds_closed()
    os.close(harness.read_end)


def test_unsupported_platform_and_missing_transcript_do_not_attach(monkeypatch, tmp_path):
    job = SharedJob("job", "sid", "/w")
    monkeypatch.setattr(shared_job, "PTY_ATTACH_SUPPORTED", False)
    assert shared_job.inject(job, "hi") is None
    monkeypatch.setattr(shared_job, "PTY_ATTACH_SUPPORTED", True)
    monkeypatch.setattr(shared_job, "transcript_for", lambda job: None)
    assert shared_job.inject(job, "hi") is None


def test_notice_is_pasted_with_bracketed_paste_then_submitted(monkeypatch, tmp_path):
    harness = PtyHarness(monkeypatch, tmp_path)
    proc = FakeProc()
    monkeypatch.setattr(shared_job.subprocess, "Popen", lambda *a, **k: proc)
    result = shared_job.inject(
        SharedJob("job", "sid", "/w"), "line one\r\nline two", expect_reply=False
    )
    assert result == "" and proc.terminated
    sent = os.read(harness.read_end, 65536)
    assert sent == b"\x1b[200~line one\nline two\x1b[201~\r"
    os.close(harness.read_end)


def test_inline_reply_when_the_turn_finishes_inside_the_window(monkeypatch, tmp_path):
    harness = PtyHarness(monkeypatch, tmp_path)
    monkeypatch.setattr(shared_job.subprocess, "Popen", lambda *a, **k: FakeProc())
    write_transcript(harness.transcript, user("ping"), assistant("pong", "end_turn"))
    assert shared_job.inject(SharedJob("job", "sid", "/w"), "ping") == "pong"
    os.close(harness.read_end)


def test_slow_turn_is_a_pending_delivery_not_a_failure(monkeypatch, tmp_path):
    harness = PtyHarness(monkeypatch, tmp_path)
    monkeypatch.setattr(shared_job.subprocess, "Popen", lambda *a, **k: FakeProc())
    write_transcript(harness.transcript, user("ping"), assistant("working", "tool_use"))
    result = shared_job.inject(SharedJob("job", "sid", "/w"), "ping", sync_window_s=0.0)
    assert result is DELIVERED_PENDING
    os.close(harness.read_end)


def test_notify_reports_whether_it_reached_a_live_job(monkeypatch, tmp_path):
    monkeypatch.setattr(shared_job, "live_job", lambda session_file: None)
    assert shared_job.notify("report", session_file=tmp_path / "pin") is False
    job = SharedJob("job", "sid", "/w")
    monkeypatch.setattr(shared_job, "live_job", lambda session_file: job)
    monkeypatch.setattr(shared_job, "inject", lambda *a, **k: "")
    assert shared_job.notify("report", session_file=tmp_path / "pin") is True
    monkeypatch.setattr(shared_job, "inject", lambda *a, **k: None)
    assert shared_job.notify("report", session_file=tmp_path / "pin") is False
