"""Settings round-trip, live project permissions, and native shell activity."""
import asyncio
import json
import logging
from pathlib import Path
from types import SimpleNamespace

import pytest

import bridge
from modules.command_activity import log_command
from modules.gui_settings import PROJECT_FOLDERS, PROJECT_ROOTS, decode_paths, encode_paths
from modules.free_work import list_projects, resolve_project
from modules.workers import _under_allowed_root
from modules.codex_brain import CodexBrain
from modules.claude_brain import ClaudeBrain
from modules.brain import PermissionGate
from modules.gui_settings import PERMISSION_LEVEL
from tools.overlord_setup import read_env, save_settings


def test_default_project_roots_can_be_removed_and_stay_removed(tmp_path, monkeypatch):
    from modules.gui_settings import default_project_roots

    home = tmp_path / "home"
    home.mkdir()
    projects, documents = home / "Projects", home / "Documents"
    projects.mkdir()
    documents.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    monkeypatch.setattr(bridge, "_ALLOWED_ROOTS", (projects, documents))
    monkeypatch.setattr(bridge, "CWD", str(home))
    monkeypatch.setattr(bridge, "PROJECTS_ROOT", "")
    monkeypatch.delenv(PROJECT_ROOTS, raising=False)
    assert decode_paths(default_project_roots()) == [projects, documents]
    assert bridge.project_roots() == [projects, documents]

    env = tmp_path / "settings.env"
    for retained in ([str(projects)], []):
        save_settings(env, {PROJECT_ROOTS: encode_paths(retained)})
        saved = read_env(env, (PROJECT_ROOTS,))[PROJECT_ROOTS]
        monkeypatch.setenv(PROJECT_ROOTS, saved)
        assert bridge.project_roots() == [Path(p) for p in retained]


def test_project_paths_round_trip_spaces_unicode_and_duplicates(tmp_path):
    folder = tmp_path / "my project café"
    folder.mkdir()
    env = tmp_path / "settings.env"
    save_settings(env, {PROJECT_FOLDERS: encode_paths([str(folder), str(folder)])})
    values = read_env(env, (PROJECT_FOLDERS,))
    assert decode_paths(values[PROJECT_FOLDERS]) == [folder.resolve()]
    assert resolve_project(folder.name.upper(), [], [folder]) == folder
    assert list_projects([], [folder])[0][1] == folder
    assert _under_allowed_root(str(folder), tuple(decode_paths(values[PROJECT_FOLDERS]))) == folder.resolve()


@pytest.mark.parametrize("value", ['{}', '[3]', '["relative"]', 'broken'])
def test_invalid_project_configuration_is_rejected(value):
    with pytest.raises(ValueError):
        decode_paths(value)


def test_project_paths_reject_missing_root_home_and_offlimits(tmp_path):
    secret = tmp_path / ".ssh"
    secret.mkdir()
    for path in (tmp_path / "gone", secret, Path.home(), Path(tmp_path.anchor)):
        with pytest.raises(ValueError):
            encode_paths([str(path)])


def test_saved_settings_apply_to_running_gate_workers_and_project_discovery(tmp_path, monkeypatch):
    folder = tmp_path / "app"
    folder.mkdir()
    monkeypatch.setattr(bridge, "BASE_DIR", tmp_path)
    monkeypatch.setattr(bridge, "PROJECTS_ROOT", "")
    monkeypatch.setattr(bridge, "AUTO_APPROVE", False)
    monkeypatch.setattr(bridge, "CLAUDE_AUTO_APPROVE_EDITS", False)
    monkeypatch.setattr(bridge, "FREE_WORK_APPROVAL", "all")
    for key in (PROJECT_FOLDERS, PROJECT_ROOTS, PERMISSION_LEVEL, "OVERLORD_AUTO_APPROVE",
                "OVERLORD_CLAUDE_AUTO_APPROVE_EDITS", "OVERLORD_FREE_WORK_APPROVAL"):
        monkeypatch.delenv(key, raising=False)
    save_settings(tmp_path / ".env", {
        PROJECT_FOLDERS: encode_paths([str(folder)]), PROJECT_ROOTS: "[]",
        "OVERLORD_AUTO_APPROVE": "1", "OVERLORD_CLAUDE_AUTO_APPROVE_EDITS": "1",
        "OVERLORD_FREE_WORK_APPROVAL": "commands",
    })
    instance = bridge.Bridge.__new__(bridge.Bridge)
    instance.brain = SimpleNamespace(name="claude")
    instance.gate = PermissionGate(None, 42, 1)
    instance.workers = SimpleNamespace(extra_roots=())
    instance.free_work = SimpleNamespace(approval="all")
    instance._status_by_brain = {}
    instance.telegram = SimpleNamespace(send=lambda *args: None)
    instance._write_console_status = lambda: None
    instance._basic_status_for = lambda name: {}
    asyncio.run(instance._reload_env())
    assert instance.gate.auto_approve is True
    assert instance.brain.auto_approve_edits is True
    assert folder.resolve() in instance.workers.extra_roots
    assert instance.free_work.approval == "commands"
    save_settings(tmp_path / ".env", {PERMISSION_LEVEL: "ask", "OVERLORD_AUTO_APPROVE": "1"})
    asyncio.run(instance._reload_env())
    assert instance.gate.permission_level == "ask" and not instance.gate.auto_approve
    save_settings(tmp_path / ".env", {PERMISSION_LEVEL: "safe"})
    asyncio.run(instance._reload_env())
    assert instance.gate.permission_level == "safe" and instance.gate.safe_commands
    save_settings(tmp_path / ".env", {PROJECT_FOLDERS: "[]", "OVERLORD_AUTO_APPROVE": "0"})
    asyncio.run(instance._reload_env())
    assert folder.resolve() not in instance.workers.extra_roots
    assert instance.gate.auto_approve is False


def test_codex_native_command_events_are_logged_without_an_approval_request(tmp_path, caplog):
    brain = CodexBrain(gate=None, cwd=str(tmp_path), model="", session_file=tmp_path / "pin")
    caplog.set_level(logging.INFO, logger="overlord.commands")
    for event, item in [("item/started", {"command": "echo hello"}),
                        ("item/completed", {"command": "echo hello", "exitCode": 0})]:
        brain._handle_notification(event, {"item": {"type": "commandExecution", **item}})
    assert "started" in caplog.text and "echo hello" in caplog.text and "exit=0" in caplog.text


def test_claude_options_log_shell_calls_even_when_native_permissions_allow_them(tmp_path, caplog):
    brain = ClaudeBrain(gate=None, cwd=str(tmp_path), model="opus", session_file=tmp_path / "pin")
    caplog.set_level(logging.INFO, logger="overlord.commands")
    options = brain._build_options(None)
    for event in ("PreToolUse", "PostToolUse", "PostToolUseFailure"):
        hook = options.hooks[event][0].hooks[0]
        assert asyncio.run(hook({"hook_event_name": event, "tool_name": "Bash",
                                  "tool_input": {"command": "echo hello"}}, "id", {})) == {}
    assert "requested" in caplog.text and "completed" in caplog.text and "failed" in caplog.text


def test_command_activity_redacts_loaded_keys_and_cannot_forge_log_lines(monkeypatch, caplog):
    monkeypatch.setenv("EXAMPLE_API_KEY", "secret-value-long")
    caplog.set_level(logging.INFO, logger="overlord.commands")
    log_command("test", "started", "echo secret-value-long\npretend success", "workspace")
    assert "secret-value-long" not in caplog.text and "[redacted]" in caplog.text
    assert "\\npretend success" in caplog.text


def test_shared_claude_turn_logs_command_and_result_once(tmp_path, caplog):
    from modules.shared_job import _reply_status
    transcript = tmp_path / "session.jsonl"
    records = [
        {"type": "user", "message": {"content": "my current task"}},
        {"type": "assistant", "cwd": str(tmp_path), "message": {"content": [
            {"type": "tool_use", "name": "Bash", "id": "shell-1", "input": {"command": "echo hello"}}]}},
        {"type": "user", "message": {"content": [
            {"type": "tool_result", "tool_use_id": "shell-1", "content": "hello"}]}},
    ]
    transcript.write_text("\n".join(json.dumps(rec) for rec in records), encoding="utf-8")
    caplog.set_level(logging.INFO, logger="overlord.commands")
    _reply_status(transcript, "my current task")
    _reply_status(transcript, "my current task")
    assert len(caplog.records) == 2
    assert "requested" in caplog.text and "completed" in caplog.text


def test_setup_window_saves_projects_and_permissions_without_touching_saved_keys(tmp_path):
    from tools.overlord_setup import SetupWindow
    import tkinter as tk

    env = tmp_path / "settings.env"
    save_settings(env, {"OVERLORD_WORKER_NVIDIA_API_KEY": "nvapi-" + "x" * 30})
    try:
        window = SetupWindow(env, tmp_path / "command.json")
    except tk.TclError:
        pytest.skip("No graphical display")
    try:
        window.root.withdraw()
        from modules.gui_settings import default_project_roots
        assert list(window.project_roots.get(0, "end")) == json.loads(default_project_roots())
        window.project_roots.delete(0, "end")
        folder = tmp_path / "app"
        folder.mkdir()
        window.project_folders.insert("end", str(folder))
        window.permission_level.set("full")
        window.work_approval.set("commands")
        window.gemini.insert(0, "synthetic-gemini-key")
        window.use_gemini.set(True)
        window.save()
        values = read_env(env, (PROJECT_FOLDERS, PERMISSION_LEVEL, "OVERLORD_AUTO_APPROVE", "OVERLORD_FREE_WORK_APPROVAL",
                                "OVERLORD_WORKER_NVIDIA_API_KEY"))
        assert decode_paths(values[PROJECT_FOLDERS]) == [folder.resolve()]
        assert read_env(env, (PROJECT_ROOTS,))[PROJECT_ROOTS] == "[]"
        assert values["OVERLORD_AUTO_APPROVE"] == "1"
        assert values[PERMISSION_LEVEL] == "full"
        assert values["OVERLORD_FREE_WORK_APPROVAL"] == "commands"
        assert values["OVERLORD_WORKER_NVIDIA_API_KEY"] == "nvapi-" + "x" * 30
        gemini = read_env(env, ("OVERLORD_FREE_GEMINI_API_KEY", "OVERLORD_FREE_GEMINI_ENABLED"))
        assert gemini == {"OVERLORD_FREE_GEMINI_API_KEY": "synthetic-gemini-key", "OVERLORD_FREE_GEMINI_ENABLED": "1"}
        assert json.loads((tmp_path / "command.json").read_text())["action"] == "reload_env"
    finally:
        window.root.destroy()
