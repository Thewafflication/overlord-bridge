"""REQ-OVL-003: exact grants cannot broaden or survive cancellation."""

import asyncio
from pathlib import Path

import pytest

from modules.brain import PermissionGate
from modules.codex_brain import CodexBrain, R_EXEC_APPROVAL


class Telegram:
    def __init__(self):
        self.prompts = []
        self.cancelled = []
        self.messages = []

    def ask_permission(self, owner, text, request_id):
        self.prompts.append(request_id)

    def send(self, owner, text):
        self.messages.append(text)

    def cancel_permission(self, owner, request_id):
        self.cancelled.append(request_id)


async def approve(gate, context, decision="session"):
    task = asyncio.create_task(
        gate.request("Write", "app.py", ["app.py"], context=context)
    )
    await asyncio.sleep(0)
    gate.on_permission_response(gate.telegram.prompts[-1], decision)
    return await task


@pytest.mark.parametrize("exact", [False, True])
def test_revocation_invalidates_pending_and_queued_grants(exact):
    async def scenario():
        gate = PermissionGate(Telegram(), 42, 1)
        task = asyncio.create_task(gate.request("Write", "app.py", ["app.py"]))
        await asyncio.sleep(0)
        request_id = gate.telegram.prompts[-1]
        grant_id = gate._permission_scopes[request_id]["id"]
        # Queue an owner response, then revoke before the brain loop sees it.
        gate.on_permission_response(request_id, "session")
        gate.revoke_grants(grant_id if exact else None)
        assert not await task
        gate.on_permission_response(request_id, "session")
        await asyncio.sleep(0)
        assert not gate.grants
        assert not gate.pending
        assert request_id in gate.telegram.cancelled
    asyncio.run(scenario())


@pytest.mark.parametrize("changed", [
    {"workspace": "other", "input": {"content": "original"}},
    {"workspace": "same", "input": {"content": "changed"}},
])
def test_changed_workspace_or_arguments_requires_new_permission(changed):
    async def scenario():
        telegram = Telegram()
        gate = PermissionGate(telegram, 42, 1)
        original = {"workspace": "same", "input": {"content": "original"}}
        assert await approve(gate, original)
        assert await gate.request("Write", "app.py", ["app.py"], context=original)
        assert len(telegram.prompts) == 1
        assert not await approve(gate, changed, "deny")
        assert len(telegram.prompts) == 2
        assert len(gate.grants) == 1
    asyncio.run(scenario())


def test_grant_can_be_inspected_and_revoked():
    async def scenario():
        gate = PermissionGate(Telegram(), 42, 1)
        assert await approve(gate, {})
        grant_id = next(iter(gate.grants))
        assert grant_id in gate.format_grants()
        assert gate.revoke_grants(grant_id) == 1
        assert gate.revoke_grants(grant_id) == 0
        assert not await approve(gate, {}, "deny")
    asyncio.run(scenario())


def test_old_global_button_is_not_an_approval():
    async def scenario():
        gate = PermissionGate(Telegram(), 42, 1)
        assert not await approve(gate, {}, "always")
        assert not gate.grants
        assert not gate.auto_approve
    asyncio.run(scenario())


def test_cancelled_permission_cleans_up_buttons_and_cannot_grant():
    async def scenario():
        gate = PermissionGate(Telegram(), 42, 1)
        task = asyncio.create_task(gate.request("Write", "app.py", ["app.py"]))
        await asyncio.sleep(0)
        request_id = gate.telegram.prompts[-1]
        task.cancel()
        gate.on_permission_response(request_id, "session")
        with pytest.raises(asyncio.CancelledError):
            await task
        await asyncio.sleep(0)
        assert gate.pending == {}
        assert gate._permission_scopes == {}
        assert gate.grants == {}
        assert gate.telegram.cancelled == [request_id]
    asyncio.run(scenario())


def test_resolved_offlimits_target_is_denied_even_in_legacy_mode(
    monkeypatch, tmp_path
):
    original_resolve = Path.resolve
    target = tmp_path / "link"

    def resolve(path, *args, **kwargs):
        if path == target:
            return tmp_path / ".ssh" / "private"
        return original_resolve(path, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", resolve)
    gate = PermissionGate(Telegram(), 42, 1, auto_approve=True)
    allowed = asyncio.run(gate.request(
        "Read", "link", ["link"],
        context={"workspace": str(tmp_path), "paths": ["link"]},
    ))
    assert not allowed
    assert not gate.telegram.prompts


def test_revoke_all_disables_legacy_mode():
    gate = PermissionGate(Telegram(), 42, 1, auto_approve=True)
    assert "Legacy" in gate.format_grants()
    assert gate.revoke_grants() == 1
    assert not gate.auto_approve


def test_codex_command_argument_paths_are_screened(tmp_path):
    gate = PermissionGate(Telegram(), 42, 1, auto_approve=True)
    brain = CodexBrain(
        gate=gate, cwd=str(tmp_path), model="test",
        session_file=tmp_path / "session",
    )
    assert not asyncio.run(brain._approve(R_EXEC_APPROVAL, {
        "command": ["cat", "C:/Users/owner/.ssh/private"],
        "cwd": str(tmp_path),
    }))


def test_codex_ephemeral_ids_do_not_invalidate_exact_grant(tmp_path):
    async def scenario():
        gate = PermissionGate(Telegram(), 42, 1)
        gate.safe_commands = False
        brain = CodexBrain(
            gate=gate, cwd=str(tmp_path), model="test",
            session_file=tmp_path / "session",
        )
        params = {
            "command": "git status", "cwd": str(tmp_path),
            "threadId": "thread-1", "turnId": "turn-1", "itemId": "item-1",
        }
        task = asyncio.create_task(brain._approve(R_EXEC_APPROVAL, params))
        await asyncio.sleep(0)
        gate.on_permission_response(gate.telegram.prompts[-1], "session")
        assert await task
        assert await brain._approve(R_EXEC_APPROVAL, {
            **params, "turnId": "turn-2", "itemId": "item-2",
        })
        assert len(gate.telegram.prompts) == 1
    asyncio.run(scenario())
