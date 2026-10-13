import asyncio

import pytest

from modules.brain import PermissionGate
from modules.safe_commands import is_safe_command
from modules import safe_commands
from tests.test_permission_gate import FakeTelegram
from types import SimpleNamespace

from bridge import Bridge


@pytest.mark.parametrize("command", [
    "git status", "git diff --stat", "git log -n 5 --oneline", "git branch --show-current",
    "git ls-files", "make", "make -j4 test", "make --jobs 2 build", "mingw32-make check",
    "python -m pytest tests/test_example.py -q", "pytest -q", "npm run build",
    "cmake --build build --config Release", "ctest --output-on-failure",
    ["git", "status"], ["powershell.exe", "-NoProfile", "-Command", "git status"],
    ["cmd.exe", "/c", "make test"], ["bash", "-lc", "git status"],
])
def test_routine_commands_are_allowed(tmp_path, command):
    assert is_safe_command(command, str(tmp_path))


@pytest.mark.parametrize("command", [
    "git push", "git reset --hard", "git clean -fd", "git checkout main", "git config --list",
    "git -c alias.status=push status", "git -C elsewhere status", "git diff --output=file",
    "git log --exec=evil", "make install", "make clean", "make deploy", "make -f other.mk",
    "make --eval=evil", "make SHELL=evil", "make 123", "make -C elsewhere",
    "git status && git push", "git status; del file", "git status | evil", "git status > file",
    "git status\nmake install", "git status $(evil)", "git status `evil`", "git status %EVIL%",
    "git show ../outside", "git show C:/outside", "git show /outside", "git show .env",
    "python -c evil", "python -m pytest --override-ini=evil", "npm install", "npm run deploy",
    ["powershell.exe", "-EncodedCommand", "abc"], ["powershell.exe", "-Command", "git status; evil"],
    ["C:/fake/powershell.exe", "-Command", "git status"], ["C:/fake/git.exe", "status"],
])
def test_unknown_and_dangerous_commands_require_approval(tmp_path, command):
    assert not is_safe_command(command, str(tmp_path))


def test_cwd_cannot_escape_workspace(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    assert not is_safe_command("git status", str(root), str(tmp_path))
    assert not is_safe_command("git status", "")


def test_gate_defaults_to_safe_policy_and_still_blocks_offlimits(tmp_path):
    async def scenario():
        telegram = FakeTelegram()
        gate = PermissionGate(telegram, 42, 1)
        context = {"workspace": str(tmp_path), "request": {"command": "make test"}}
        assert await gate.request("Free worker: run command", "make test", ["make test"], context=context)
        assert not telegram.prompts
        context["request"]["command"] = "git show .ssh/key"
        assert not await gate.request("Free worker: run command", "key", [".ssh/key"], context=context)
        assert not telegram.prompts
        gate.safe_commands = False
        context["request"]["command"] = "make test"
        waiting = asyncio.create_task(gate.request("Free worker: run command", "make test", ["make test"], context=context))
        await asyncio.sleep(0)
        gate.on_permission_response(telegram.prompts[-1][2], False)
        assert not await waiting
    asyncio.run(scenario())


def test_safe_policy_audit_failure_denies(tmp_path):
    class Audit:
        def record(self, **kwargs):
            assert kwargs["source"] == "safe_command_policy"
            return False
    gate = PermissionGate(FakeTelegram(), 42, 1, audit=Audit())
    assert not asyncio.run(gate.request("Bash", "git status", ["git status"], context={
        "workspace": str(tmp_path), "input": {"command": "git status"}}))


def test_owner_can_toggle_policy():
    telegram = FakeTelegram()
    gate = PermissionGate(telegram, 42, 1)
    bridge = SimpleNamespace(gate=gate, telegram=telegram)
    Bridge._handle_permissions(bridge, 42, "/permissions safe off")
    assert not gate.safe_commands
    assert "off" in gate.format_grants()
    Bridge._handle_permissions(bridge, 42, "/permissions safe on")
    assert gate.safe_commands


def test_windows_native_shell_path_is_inspected(tmp_path, monkeypatch):
    monkeypatch.setattr(safe_commands.sys, "platform", "win32")
    monkeypatch.setenv("SystemRoot", "C:/Windows")
    command = ["C:/Windows/System32/WindowsPowerShell/v1.0/powershell.exe",
               "-NoLogo", "-NoProfile", "-Command", "git status"]
    assert is_safe_command(command, str(tmp_path))
    command[-1] = "git status; git push"
    assert not is_safe_command(command, str(tmp_path))
