import os
from pathlib import Path

from modules import codex_discovery


def test_explicit_codex_path_is_preserved(tmp_path):
    executable = tmp_path / "codex.exe"
    executable.write_bytes(b"")

    assert codex_discovery.resolve_codex_binary(str(executable)) == str(
        executable.resolve()
    )


def test_windows_discovers_newest_codex_desktop_binary(monkeypatch, tmp_path):
    older = tmp_path / "OpenAI" / "Codex" / "bin" / "old" / "codex.exe"
    newer = tmp_path / "OpenAI" / "Codex" / "bin" / "new" / "codex.exe"
    older.parent.mkdir(parents=True)
    newer.parent.mkdir(parents=True)
    older.write_bytes(b"")
    newer.write_bytes(b"")
    os.utime(older, (1, 1))
    os.utime(newer, (2, 2))
    monkeypatch.setattr(codex_discovery.sys, "platform", "win32")
    monkeypatch.setattr(codex_discovery.shutil, "which", lambda command: None)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))

    assert codex_discovery.resolve_codex_binary("codex") == str(newer.resolve())


def test_unresolved_name_is_returned_for_actionable_startup_error(monkeypatch):
    monkeypatch.setattr(codex_discovery.shutil, "which", lambda command: None)
    monkeypatch.setattr(codex_discovery.sys, "platform", "linux")

    assert codex_discovery.resolve_codex_binary("custom-codex") == "custom-codex"
