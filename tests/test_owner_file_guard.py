import asyncio
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from modules import owner_file_guard as guard


def git(folder, *args):
    return subprocess.run(["git", "-C", str(folder), *args], check=True,
                          capture_output=True, text=True).stdout


def repository(folder):
    folder.mkdir(exist_ok=True)
    git(folder, "init", "-q")
    git(folder, "config", "user.email", "fixture@example.invalid")
    git(folder, "config", "user.name", "Fixture")
    return folder


def test_inventory_covers_untracked_staged_modified_and_nested_but_not_clean_or_ignored(tmp_path):
    root = repository(tmp_path / "repo")
    for name in ("clean.txt", "modified.txt", "staged.txt", ".gitignore"):
        (root / name).write_text("ignored.bin\n" if name == ".gitignore" else "baseline")
    git(root, "add", ".")
    git(root, "commit", "-qm", "baseline")
    (root / "modified.txt").write_text("owner changes")
    (root / "staged.txt").write_text("staged owner changes")
    git(root, "add", "staged.txt")
    (root / "owned-debug.bin").write_bytes(b"original")
    (root / "ignored.bin").write_bytes(b"ignored generated file")
    nested = repository(root / "nested")
    (nested / "clean.txt").write_text("nested baseline")
    git(nested, "add", ".")
    git(nested, "commit", "-qm", "nested baseline")
    git(root, "add", "nested")
    (nested / "owner.txt").write_text("nested owner")
    paths = asyncio.run(guard._owner_paths(root, lambda p: True))
    assert {p.relative_to(root).as_posix() for p in paths} == {
        "modified.txt", "staged.txt", "owned-debug.bin", "nested/owner.txt"}


def test_loose_project_inventory_respects_denials_and_limits(tmp_path, monkeypatch):
    (tmp_path / "one.txt").write_text("one")
    (tmp_path / "off-limits.txt").write_text("do not open")
    assert asyncio.run(guard._owner_paths(tmp_path, lambda p: p.name != "off-limits.txt")) == [tmp_path / "one.txt"]
    monkeypatch.setattr(guard, "MAX_FILES", 1)
    with pytest.raises(RuntimeError, match="limit"):
        asyncio.run(guard._owner_paths(tmp_path, lambda p: True))


def test_git_inventory_failure_is_not_silently_unprotected(tmp_path, monkeypatch):
    (tmp_path / ".git").mkdir()
    async def failed(*args, **kwargs):
        return "", False, False
    monkeypatch.setattr(guard, "_git", failed)
    with pytest.raises(RuntimeError, match="enumerate"):
        asyncio.run(guard._owner_paths(tmp_path, lambda p: True))


def test_unborn_git_repository_includes_staged_owner_file(tmp_path):
    repository(tmp_path)
    owner = tmp_path / "first.txt"
    owner.write_text("not committed yet")
    git(tmp_path, "add", "first.txt")
    assert asyncio.run(guard._owner_paths(tmp_path, lambda p: True)) == [owner]


def test_unreadable_loose_inventory_fails_closed(tmp_path, monkeypatch):
    def unreadable(*args, **kwargs):
        kwargs["onerror"](PermissionError("cannot enumerate"))
        return []
    monkeypatch.setattr(guard.os, "walk", unreadable)
    with pytest.raises(PermissionError):
        asyncio.run(guard._owner_paths(tmp_path, lambda p: True))


@pytest.mark.skipif(os.name != "nt", reason="Windows mandatory file sharing")
@pytest.mark.parametrize("operation", ["unlink", "rename", "replace", "powershell"])
def test_native_child_cleanup_is_blocked_but_edits_and_new_scratch_work(tmp_path, operation):
    owner = tmp_path / "owned-debug.bin"
    owner.write_bytes(b"owner bytes")
    held = guard.OwnerFileGuard()
    asyncio.run(held.acquire(tmp_path, lambda p: True))
    assert held.count == 1
    try:
        if operation == "powershell":
            shell = shutil.which("powershell.exe")
            if not shell:
                pytest.skip("Windows PowerShell unavailable")
            command = [shell, "-NoProfile", "-Command",
                       "$ErrorActionPreference='Stop'; Remove-Item -LiteralPath '" + str(owner).replace("'", "''") + "' -Force"]
        else:
            code = {"unlink": "p.unlink()", "rename": "p.rename(p.with_name('renamed.bin'))",
                    "replace": "q=p.with_name('replacement.bin');q.write_bytes(b'new');q.replace(p)"}[operation]
            command = [sys.executable, "-c", "from pathlib import Path;p=Path(" + repr(str(owner)) + ");" + code]
        result = subprocess.run(command, capture_output=True, text=True, timeout=20)
        assert result.returncode != 0, result.stdout + result.stderr
        assert owner.read_bytes() == b"owner bytes"
        owner.write_bytes(b"authorized in-place edit")
        scratch = tmp_path / "worker-created.txt"
        scratch.write_text("temporary")
        scratch.unlink()
        assert owner.read_bytes() == b"authorized in-place edit"
    finally:
        held.close()
    assert held.count == 0
    owner.unlink()  # no leaked handle beyond the job boundary


@pytest.mark.skipif(os.name != "nt", reason="Windows mandatory file sharing")
def test_partial_acquisition_failure_releases_already_open_handles(tmp_path, monkeypatch):
    owner = tmp_path / "a.txt"
    owner.write_text("owner")
    async def inventory(*args):
        return [owner, tmp_path / "missing.txt"]
    monkeypatch.setattr(guard, "_owner_paths", inventory)
    held = guard.OwnerFileGuard()
    with pytest.raises(OSError):
        asyncio.run(held.acquire(tmp_path, lambda p: True))
    assert held.count == 0
    owner.unlink()
