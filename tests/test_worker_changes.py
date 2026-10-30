import asyncio
import json
import subprocess
from pathlib import Path

from modules import worker_changes, workers


def git(folder, *args):
    return subprocess.check_output(["git", "-C", str(folder), *args], text=True).strip()


def repo(tmp_path):
    folder = tmp_path / "project"
    folder.mkdir()
    git(folder, "init")
    git(folder, "config", "user.name", "Review fixture")
    git(folder, "config", "user.email", "fixture@example.invalid")
    return folder


def allowed(folder):
    return lambda path: workers._local_agent_path_denial(path, folder, write=False) is None


def test_review_observes_committed_test_deletion_and_untracked_placeholder(tmp_path):
    p = repo(tmp_path)
    (p / "test_queue.py").write_text("def test_preserves_job():\n    assert False\n")
    (p / "owner.txt").write_text("owner original")
    git(p, "add", "."); git(p, "commit", "-m", "Seed real coverage")
    (p / "owner.txt").write_text("owner pending")
    initial = asyncio.run(worker_changes.baseline(p, allowed(p)))
    (p / "test_queue.py").unlink()
    (p / "test_queue_checks.py").write_text("# remaining tests omitted for brevity\n")
    git(p, "add", "test_queue.py"); git(p, "commit", "-m", "Remove alleged duplicate")
    result = asyncio.run(worker_changes.evidence(p, initial, allowed(p)))
    files = {row["path"]: row for row in result["files"]}
    assert "-def test_preserves_job" in files["test_queue.py"]["content"]
    assert "deleted file mode" in files["test_queue.py"]["content"]
    assert files["test_queue_checks.py"]["untracked"]
    assert "omitted for brevity" in files["test_queue_checks.py"]["content"]
    assert result["preexisting_paths"] == ["owner.txt"]
    assert initial["head"] != result["current_head"]
    assert not result["partial"]


def test_review_filters_secrets_before_git_content_and_marks_partial(tmp_path, monkeypatch):
    p = repo(tmp_path)
    (p / "safe.py").write_text("answer = 0")
    (p / ".env").write_text("SYNTHETIC_SECRET=fixture-before")
    git(p, "add", "."); git(p, "commit", "-m", "Seed")
    initial = asyncio.run(worker_changes.baseline(p, allowed(p)))
    (p / ".env").write_text("SYNTHETIC_SECRET=fixture-after")
    (p / "safe.py").write_text("answer = 42")
    (p / "ignored.log").write_text("SYNTHETIC_PRIVATE_LOG")
    commands = []
    original = worker_changes._git
    async def capture(folder, *args, **kwargs):
        commands.append(args)
        assert ".env" not in args and "ignored.log" not in args
        return await original(folder, *args, **kwargs)
    monkeypatch.setattr(worker_changes, "_git", capture)
    result = asyncio.run(worker_changes.evidence(p, initial, allowed(p)))
    assert result["partial"] and "fixture-after" not in json.dumps(result)
    assert "SYNTHETIC_PRIVATE_LOG" not in json.dumps(result)
    assert [f["path"] for f in result["files"]] == ["safe.py"]


def test_review_limits_large_diffs_and_does_not_change_checkout(tmp_path):
    p = repo(tmp_path)
    (p / "large.py").write_text("before\n")
    git(p, "add", "."); git(p, "commit", "-m", "Seed")
    initial = asyncio.run(worker_changes.baseline(p, allowed(p)))
    text = "after\n" * 10000
    (p / "large.py").write_text(text)
    result = asyncio.run(worker_changes.evidence(p, initial, allowed(p)))
    assert result["partial"] and result["files"][0]["truncated"]
    assert len(result["files"][0]["content"]) <= 8000
    assert (p / "large.py").read_text() == text


def test_non_git_worker_is_explicitly_unavailable(tmp_path):
    result = asyncio.run(worker_changes.baseline(tmp_path, lambda p: True))
    assert result["available"] is False
    assert asyncio.run(worker_changes.evidence(tmp_path, result, lambda p: True)) == result
