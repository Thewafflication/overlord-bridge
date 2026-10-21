import asyncio

import pytest

from modules import brain
from modules.brain import PermissionGate
from tests.test_permission_gate import FakeTelegram
from types import SimpleNamespace

from bridge import Bridge


def test_telegram_full_sixty_releases_pending_worker_permission():
    from tests.test_telegram_handler_edges import make_handler, update

    async def scenario():
        telegram = FakeTelegram()
        gate = PermissionGate(telegram, 42, 1)
        waiting = asyncio.create_task(gate.request("Write", "worker", ["app.py"]))
        await asyncio.sleep(0)
        handler = make_handler()
        await handler._handle_command(update("/permissions full 60"), None)
        chat_id, text = handler.inbound_queue.get_nowait()
        Bridge._handle_permissions(SimpleNamespace(gate=gate, telegram=telegram), chat_id, text)
        assert await waiting
        assert 3599 <= gate.full_access_remaining() <= 3600
        assert "Full access enabled for 60 minutes" in telegram.messages[-1][1]
        assert await gate.request("Write", "next-worker", ["next.py"])
        assert not gate.pending

    asyncio.run(scenario())


def test_timed_access_expires_and_respects_offlimits(monkeypatch):
    now = [100.0]
    monkeypatch.setattr(brain.time, "monotonic", lambda: now[0])

    async def scenario():
        telegram = FakeTelegram()
        gate = PermissionGate(telegram, 42, 1, auto_approve=True)
        assert gate.grant_full_access(10)
        assert not gate.auto_approve
        assert gate.full_access_remaining() == 600
        assert await gate.request("Bash", "first", ["git status"])
        assert await gate.request("Write", "different", ["app.py"])
        assert not telegram.prompts
        assert not await gate.request("Read", "secret", [".ssh/config"])
        now[0] = 700.0
        assert gate.full_access_remaining() == 0
        waiting = asyncio.create_task(gate.request("Write", "next", ["next.py"]))
        await asyncio.sleep(0)
        assert len(telegram.prompts) == 1
        gate.on_permission_response(telegram.prompts[-1][2], False)
        assert not await waiting
        assert not PermissionGate(FakeTelegram(), 42, 1).full_access_remaining()

    asyncio.run(scenario())


def test_timed_grant_unblocks_pending_and_revocation_stops_access():
    async def scenario():
        gate = PermissionGate(FakeTelegram(), 42, 1)
        waiting = asyncio.create_task(gate.request("Write", "app", ["app.py"]))
        await asyncio.sleep(0)
        assert gate.grant_full_access(10)
        assert await waiting
        assert not gate.grants
        assert gate.revoke_grants() == 1
        assert not gate.full_access_remaining()
        assert "Timed full access active" not in gate.format_grants()
    asyncio.run(scenario())


@pytest.mark.parametrize("minutes", [0, -1, 1441, True, 0.5])
def test_invalid_duration_cannot_enable_access(minutes):
    gate = PermissionGate(FakeTelegram(), 42, 1)
    with pytest.raises(ValueError):
        gate.grant_full_access(minutes)
    assert not gate.full_access_remaining()


def test_audit_failure_cannot_enable_timed_access():
    class BrokenAudit:
        def record(self, **kwargs):
            return False
    gate = PermissionGate(FakeTelegram(), 42, 1, audit=BrokenAudit())
    assert not gate.grant_full_access(10)
    assert not gate.full_access_remaining()


def test_owner_command_defaults_to_ten_minutes_and_supports_revoke():
    telegram = FakeTelegram()
    gate = PermissionGate(telegram, 42, 1)
    bridge = SimpleNamespace(gate=gate, telegram=telegram)
    Bridge._handle_permissions(bridge, 42, "/permissions full")
    assert 599 <= gate.full_access_remaining() <= 600
    Bridge._handle_permissions(bridge, 42, "/permissions full 5m")
    assert 299 <= gate.full_access_remaining() <= 300
    Bridge._handle_permissions(bridge, 42, "/permissions")
    assert "seconds remaining" in telegram.messages[-1][1]
    Bridge._handle_permissions(bridge, 42, "/permissions revoke all")
    assert not gate.full_access_remaining()
