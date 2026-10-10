import asyncio
import json

import pytest

from modules.brain import PermissionGate
from modules.permission_audit import PermissionAudit
from test_scoped_permissions import Telegram, approve


def test_gate_records_hashed_actions_and_revocations_without_arguments(tmp_path):
    path = tmp_path / "audit.jsonl"
    audit = PermissionAudit(path, root=tmp_path)
    gate = PermissionGate(Telegram(), 42, 1, audit=audit)
    async def scenario():
        context = {"input": {"secret": "SECRET_ARGUMENT_VALUE"}}
        assert await approve(gate, context)
        assert await gate.request("Write", "app.py", ["app.py"], context=context)
        assert not await gate.request("Read", "key", ["/.ssh/key"])
        gate.revoke_grants()
    asyncio.run(scenario())
    raw = path.read_text(encoding="utf-8")
    records = [json.loads(line) for line in raw.splitlines()]
    assert "SECRET_ARGUMENT_VALUE" not in raw and "app.py" not in raw
    assert [row["source"] for row in records] == ["operator_session", "exact_session_grant", "off_limits", "revoke_all"]
    assert records[0]["action"] == records[1]["action"]
    assert all(row["actor"] == 42 for row in records)
    assert "healthy" in gate.format_grants()


@pytest.mark.parametrize("mode", ["configured", "session", "once"])
def test_audit_failure_cannot_allow_or_create_a_grant(mode):
    class FailedAudit:
        def record(self, **kwargs):
            raise OSError("storage full")
    gate = PermissionGate(Telegram(), 42, 1, auto_approve=mode == "configured", audit=FailedAudit())
    async def scenario():
        if mode == "configured":
            assert not await gate.request("Write", "file", ["file"])
        else:
            assert not await approve(gate, {}, "session" if mode == "session" else "allow")
        assert not gate.grants
        assert "unavailable" in gate.format_grants()
    asyncio.run(scenario())


def test_audit_storage_rotates_and_stays_bounded(tmp_path):
    path = tmp_path / "audit.jsonl"
    audit = PermissionAudit(path, root=tmp_path, max_bytes=1024)
    for _ in range(30):
        assert audit.record(action="a" * 64, allowed=True, source="operator_once", actor=42)
    previous = path.with_name(path.name + ".previous")
    assert previous.exists()
    assert path.stat().st_size <= 1024 and previous.stat().st_size <= 1024
    assert not audit.record(action="a" * 2000, allowed=True, source="operator_once", actor=42)


def test_audit_cannot_write_outside_its_workspace(tmp_path):
    audit = PermissionAudit(tmp_path / "outside/audit.jsonl", root=tmp_path / "inside")
    assert not audit.record(action="a", allowed=True, source="operator_once", actor=42)
    assert not (tmp_path / "outside").exists()
