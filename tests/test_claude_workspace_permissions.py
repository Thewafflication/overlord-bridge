import asyncio
from pathlib import Path
from types import SimpleNamespace

from claude_agent_sdk import PermissionResultAllow, PermissionResultDeny

from modules.brain import PermissionGate
from modules.claude_brain import ClaudeBrain


class FakeGate:
    def __init__(self):
        self.requests = []

    offlimits_match = staticmethod(PermissionGate.offlimits_match)

    async def request(self, title, detail, candidates):
        self.requests.append((title, detail, candidates))
        return False


def make_brain(tmp_path: Path, gate: FakeGate) -> ClaudeBrain:
    return ClaudeBrain(
        gate=gate,
        cwd=str(tmp_path),
        model="test",
        session_file=tmp_path / ".session.claude",
        auto_approve_edits=True,
    )


def test_claude_auto_approves_edits_inside_workspace(tmp_path):
    gate = FakeGate()
    brain = make_brain(tmp_path, gate)

    result = asyncio.run(
        brain.can_use_tool(
            "Write",
            {"file_path": str(tmp_path / "src" / "app.py")},
            SimpleNamespace(),
        )
    )

    assert isinstance(result, PermissionResultAllow)
    assert gate.requests == []


def test_claude_still_prompts_for_edit_outside_workspace(tmp_path):
    gate = FakeGate()
    brain = make_brain(tmp_path, gate)

    result = asyncio.run(
        brain.can_use_tool(
            "Write",
            {"file_path": str(tmp_path.parent / "outside.txt")},
            SimpleNamespace(),
        )
    )

    assert isinstance(result, PermissionResultDeny)
    assert len(gate.requests) == 1


def test_windows_style_offlimits_path_is_detected():
    match = PermissionGate.offlimits_match(
        [r"C:\Users\owner\.ssh\id_ed25519"]
    )
    assert match == "/.ssh"
