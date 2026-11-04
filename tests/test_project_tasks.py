import asyncio
import json
import subprocess
import sys

import pytest

from modules import project_tasks


def test_publication_verification_rejects_dirty_and_unpushed_work(tmp_path):
    repo = tmp_path / "project"
    repo.mkdir()
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)

    def git(*args):
        return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)

    git("init", "-b", "main")
    git("config", "user.email", "fixture@example.invalid")
    git("config", "user.name", "Fixture")
    git("remote", "add", "origin", str(remote))
    source = repo / "source.txt"
    source.write_text("baseline")
    git("add", "source.txt")
    git("commit", "-m", "baseline")
    git("push", "origin", "main")
    task = {"id": "publication", "checks": [{"name": "fixture validation", "tool": "run_python",
            "arguments": {"code": "print('validated')"}}],
            "publication": {"remote": "origin", "branch": "main", "paths": ["source.txt"]}}

    async def execute(tool, arguments):
        result = subprocess.run([sys.executable, "-c", arguments["code"]], cwd=repo,
                                capture_output=True, text=True)
        return {"ok": result.returncode == 0, "exit_code": result.returncode,
                "stdout": result.stdout, "stderr": result.stderr}

    def validate():
        return asyncio.run(project_tasks.validate(task, execute, completion=True))

    source.write_text("changed")
    assert not validate()["passed"]
    git("add", "source.txt")
    git("commit", "-m", "validated repair")
    assert not validate()["passed"]
    git("push", "origin", "main")
    assert validate()["passed"]


def test_queue_completion_cannot_overwrite_owner_changes(tmp_path):
    task = {"id": "repair", "folder": str(tmp_path), "state": "ready", "requirement": "requirement",
            "task": "repair", "checks": [{"name": "check", "tool": "run_python",
                                           "arguments": {"code": "pass"}}]}
    queue = tmp_path / "queue.json"
    queue.write_text(json.dumps({"version": 1, "tasks": [task]}))
    snapshot = project_tasks.load_task(queue, tmp_path)
    changed = dict(task, task="Owner changed scope")
    queue.write_text(json.dumps({"version": 1, "tasks": [changed]}))
    with pytest.raises(ValueError, match="changed"):
        project_tasks.complete_task(queue, snapshot)
    assert json.loads(queue.read_text())["tasks"][0] == changed
    project_tasks.complete_task(queue, changed)
    assert project_tasks.load_task(queue, tmp_path) == {"state": "idle"}
