import asyncio
from types import SimpleNamespace

import pytest

from bridge import Bridge
from modules.brain import PermissionGate
from modules.gui_settings import permission_level
from tests.test_permission_gate import FakeTelegram


@pytest.mark.parametrize("level, safe, full", [("ask", False, False), ("safe", True, False), ("full", False, True)])
def test_permission_levels_are_mutually_exclusive(level, safe, full):
    gate = PermissionGate(FakeTelegram(), 42, 1, permission_level=level)
    assert gate.safe_commands is safe
    assert gate.auto_approve is full
    assert f"Permission level: {level}" in gate.format_grants()


def test_defaults_migration_and_invalid_values():
    assert permission_level(None) == "safe"
    assert permission_level(None, legacy_auto=True) == "full"
    assert permission_level("safe", legacy_auto=True) == "safe"
    assert permission_level("invalid", legacy_auto=True) == "ask"


def test_selecting_level_clears_timed_access_and_exact_grants():
    gate = PermissionGate(FakeTelegram(), 42, 1)
    gate.grants["example"] = {}
    assert gate.grant_full_access(10)
    bridge = SimpleNamespace(gate=gate, telegram=gate.telegram)
    Bridge._handle_permissions(bridge, 42, "/permissions level ask")
    assert gate.permission_level == "ask"
    assert not gate.grants
    assert not gate.full_access_remaining()
    Bridge._handle_permissions(bridge, 42, "/permissions level safe")
    assert gate.permission_level == "safe"


def test_ask_level_prompts_for_routine_commands(tmp_path):
    async def scenario():
        gate = PermissionGate(FakeTelegram(), 42, 1, permission_level="ask")
        task = asyncio.create_task(gate.request("Bash", "make", ["make"], context={
            "workspace": str(tmp_path), "input": {"command": "make"}}))
        await asyncio.sleep(0)
        assert gate.telegram.prompts
        gate.on_permission_response(gate.telegram.prompts[-1][2], False)
        assert not await task
    asyncio.run(scenario())
