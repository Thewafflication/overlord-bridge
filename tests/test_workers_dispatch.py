"""Dispatch intake, worker argv, and report redaction in modules/workers.py."""

import json
import os
import time

import pytest

from modules import workers
from modules.workers import WorkerManager, _bounded_tail, _sanitize_text


def make_manager(tmp_path, **kwargs):
    sent = []
    manager = WorkerManager(
        send=lambda chat_id, text: sent.append((chat_id, text)),
        owner=42,
        dispatch_dir=tmp_path / "dispatch",
        **kwargs,
    )
    return manager, sent


# ------------------------------------------------------------------ redaction
@pytest.mark.parametrize(
    "text, secret",
    [
        ("Authorization: Bearer abc123SECRET", "abc123SECRET"),
        ("authorization=Bearer abc123SECRET", "abc123SECRET"),
        ("OPENAI_API_KEY=sk-live-123", "sk-live-123"),
        ("export GITHUB_TOKEN=ghp_abc", "ghp_abc"),
        ('{"api_key": "sk-abc"}', "sk-abc"),
        ("password: hunter2", "hunter2"),
        ("db.password = 'two words'", "two words"),
        ("https://x.example/cb?token=abc123&next=/home", "abc123"),
        ("Basic dXNlcjpwYXNz", "dXNlcjpwYXNz"),
        ("secret=a,b;c", "a,b;c"),
    ],
)
def test_secrets_never_survive_redaction(text, secret):
    assert secret not in _sanitize_text(text)


def test_redaction_leaves_ordinary_text_and_token_counters_alone():
    text = "max_tokens=4096 and a tokenizer that ran fine; no secrets here"
    assert _sanitize_text(text) == text


def test_redaction_keeps_the_surrounding_context_readable():
    out = _sanitize_text("calling api with API_KEY=abc next=/home")
    assert "API_KEY=<redacted>" in out
    assert "calling api with" in out
    assert "next=/home" in out


def test_redaction_is_idempotent():
    once = _sanitize_text("password=hunter2 Authorization: Bearer tok.en")
    assert _sanitize_text(once) == once


def test_bounded_tail_redacts_before_measuring():
    tail, truncated = _bounded_tail("password=hunter2 " + "x" * 50, 1000)
    assert "hunter2" not in tail
    assert truncated is False


# ------------------------------------------------------------------ worker argv
def test_markdown_bullet_task_is_not_parsed_as_a_flag_for_claude(tmp_path):
    manager, _ = make_manager(tmp_path)
    argv = manager._build_worker_argv(
        "claude", "- fix the bug\n- add tests", "sid", None, False, None,
        None, None, False,
    )
    prompt = argv[argv.index("-p") + 1]
    assert not prompt.startswith("-")
    assert prompt.strip() == "- fix the bug\n- add tests"


def test_markdown_bullet_task_is_not_parsed_as_a_flag_for_codex(tmp_path):
    manager, _ = make_manager(tmp_path)
    argv = manager._build_worker_argv(
        "codex", "--help me", "sid", None, False, None, None, None, False,
    )
    assert not argv[-1].startswith("-")
    assert argv[-2] == "--skip-git-repo-check"


def test_ordinary_task_is_passed_through_unchanged(tmp_path):
    manager, _ = make_manager(tmp_path)
    argv = manager._build_worker_argv(
        "claude", "refactor module", "sid", None, False, None, None, None, False,
    )
    assert argv[argv.index("-p") + 1] == "refactor module"


def test_claude_argv_resumes_or_pins_a_session(tmp_path):
    manager, _ = make_manager(tmp_path, claude_model="sonnet")
    fresh = manager._build_worker_argv(
        "claude", "t", "new-sid", None, False, None, None, None, False
    )
    assert fresh[fresh.index("--session-id") + 1] == "new-sid"
    assert "--resume" not in fresh
    resumed = manager._build_worker_argv(
        "claude", "t", "ignored", "old-sid", True, "opus", None, None, False
    )
    assert resumed[resumed.index("--resume") + 1] == "old-sid"
    assert resumed[resumed.index("--model") + 1] == "opus"
    assert resumed[-2:] == ["--permission-mode", "bypassPermissions"]


def test_codex_argv_orders_global_flags_before_exec(tmp_path):
    manager, _ = make_manager(tmp_path, codex_bin="codex", codex_model="gpt-x")
    argv = manager._build_worker_argv(
        "codex", "task", "sid", "thread-1", True, None,
        "never", "workspace-write", False,
    )
    assert argv[:5] == ["codex", "--ask-for-approval", "never", "--sandbox", "workspace-write"]
    assert argv[argv.index("exec") + 1:argv.index("exec") + 3] == ["resume", "thread-1"]
    assert argv[argv.index("--model") + 1] == "gpt-x"


def test_codex_bypass_flag_replaces_approval_and_sandbox_flags(tmp_path):
    manager, _ = make_manager(tmp_path)
    argv = manager._build_worker_argv(
        "codex", "task", "sid", None, False, None, "never", "read-only", True,
    )
    assert "--dangerously-bypass-approvals-and-sandbox" in argv
    assert "--ask-for-approval" not in argv and "--sandbox" not in argv


# ------------------------------------------------------------ dispatch intake
def collect_accepts(manager, monkeypatch):
    accepted = []
    monkeypatch.setattr(manager, "_accept", accepted.append)
    return accepted


def test_valid_dispatch_file_is_accepted_once_and_consumed(tmp_path, monkeypatch):
    manager, sent = make_manager(tmp_path)
    accepted = collect_accepts(manager, monkeypatch)
    path = manager.dispatch_dir / "a.json"
    path.write_text(json.dumps({"name": "W", "task": "go"}), encoding="utf-8")
    manager._scan_dispatch_once()
    manager._scan_dispatch_once()
    assert accepted == [{"name": "W", "task": "go"}]
    assert not path.exists()
    assert sent == []


def test_dispatch_file_is_read_as_utf8_even_with_a_bom(tmp_path, monkeypatch):
    manager, _ = make_manager(tmp_path)
    accepted = collect_accepts(manager, monkeypatch)
    payload = json.dumps({"name": "W", "task": "naïve café — ✓"}, ensure_ascii=False)
    (manager.dispatch_dir / "u.json").write_bytes(b"\xef\xbb\xbf" + payload.encode("utf-8"))
    manager._scan_dispatch_once()
    assert accepted == [{"name": "W", "task": "naïve café — ✓"}]


def test_half_written_dispatch_file_is_left_for_the_next_scan(tmp_path, monkeypatch):
    manager, sent = make_manager(tmp_path)
    accepted = collect_accepts(manager, monkeypatch)
    path = manager.dispatch_dir / "partial.json"
    path.write_text('{"name": "W", "task": "go', encoding="utf-8")
    manager._scan_dispatch_once()
    assert path.exists() and accepted == [] and sent == []
    # The producer finishes its write; the same file is now accepted.
    path.write_text('{"name": "W", "task": "go"}', encoding="utf-8")
    manager._scan_dispatch_once()
    assert accepted == [{"name": "W", "task": "go"}]
    assert not path.exists()


def test_stale_invalid_dispatch_file_is_removed_and_reported(tmp_path, monkeypatch):
    manager, sent = make_manager(tmp_path)
    accepted = collect_accepts(manager, monkeypatch)
    path = manager.dispatch_dir / "broken.json"
    path.write_text("{not json", encoding="utf-8")
    old = time.time() - workers.DISPATCH_PARTIAL_WRITE_GRACE - 5
    os.utime(path, (old, old))
    manager._scan_dispatch_once()
    assert not path.exists() and accepted == []
    assert len(sent) == 1 and sent[0][0] == 42
    assert "broken.json" in sent[0][1] and "not run" in sent[0][1]


def test_non_object_json_is_reported_instead_of_vanishing(tmp_path, monkeypatch):
    manager, sent = make_manager(tmp_path)
    accepted = collect_accepts(manager, monkeypatch)
    path = manager.dispatch_dir / "list.json"
    path.write_text("[1, 2]", encoding="utf-8")
    manager._scan_dispatch_once()
    assert not path.exists() and accepted == []
    assert "JSON object" in sent[0][1]


def test_accept_failure_is_reported_to_the_owner(tmp_path, monkeypatch):
    manager, sent = make_manager(tmp_path)

    def explode(data):
        raise RuntimeError("boom")

    monkeypatch.setattr(manager, "_accept", explode)
    (manager.dispatch_dir / "x.json").write_text('{"name": "W"}', encoding="utf-8")
    manager._scan_dispatch_once()
    assert "boom" in sent[0][1]


def test_undecodable_dispatch_file_is_not_retried_forever(tmp_path, monkeypatch):
    manager, sent = make_manager(tmp_path)
    collect_accepts(manager, monkeypatch)
    path = manager.dispatch_dir / "bytes.json"
    path.write_bytes(b"\xff\xfe\x00garbage")
    old = time.time() - workers.DISPATCH_PARTIAL_WRITE_GRACE - 5
    os.utime(path, (old, old))
    manager._scan_dispatch_once()
    assert not path.exists()
    assert sent and "not run" in sent[0][1]
