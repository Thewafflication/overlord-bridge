"""REQ-OVL-005: durable neutral context with bounded, recoverable storage."""

import json
from pathlib import Path

import pytest

from modules.conversation_history import SharedConversationHistory


def history(path):
    return SharedConversationHistory(path=path, workspace="test-workspace")


def test_restart_preserves_seen_markers_and_unseen_exchanges(tmp_path):
    path = tmp_path / "context.json"
    before = history(path)
    before.append_exchange("first", "answer one")
    before.mark_seen("codex")
    before.append_exchange("second", "answer two")
    after = history(path)
    assert after.handoff_for("codex") == before.handoff_for("codex")
    assert "first" not in after.handoff_for("codex").text
    assert "second" in after.handoff_for("codex").text


@pytest.mark.parametrize("damage", ["corrupt", "missing", "schema", "sequence"])
def test_bad_primary_recovers_previous_valid_checkpoint(tmp_path, damage):
    path = tmp_path / "context.json"
    before = history(path)
    before.append_exchange("objective", "remember this")
    before.mark_seen("claude")
    if damage == "missing":
        path.unlink()
    elif damage == "corrupt":
        path.write_text("{bad", encoding="utf-8")
    else:
        data = json.loads(path.read_text(encoding="utf-8"))
        data[damage] = -1
        path.write_text(json.dumps(data), encoding="utf-8")
    after = history(path)
    assert "objective" in after.handoff_for("codex").text
    assert "Recovered" in after.status()


def test_workspace_mismatch_does_not_inject_another_projects_context(tmp_path):
    path = tmp_path / "context.json"
    history(path).append_exchange("private project", "private answer")
    after = SharedConversationHistory(path=path, workspace="different-project")
    assert after.handoff_for("codex") is None
    assert "another workspace" in after.status()


def test_new_cannot_resurrect_previous_conversation_from_backup(tmp_path):
    path = tmp_path / "context.json"
    before = history(path)
    before.append_exchange("old objective", "old answer")
    before.mark_seen("codex")
    before.clear()
    path.write_text("corrupt", encoding="utf-8")
    after = history(path)
    assert after.handoff_for("claude") is None
    assert "Sequence: 0" in after.status()


def test_failed_atomic_replace_leaves_last_valid_primary(monkeypatch, tmp_path):
    path = tmp_path / "context.json"
    before = history(path)
    before.append_exchange("saved", "saved answer")
    import modules.conversation_history as module
    real_replace = module.os.replace

    def fail_primary(source, destination):
        if Path(destination) == path:
            raise OSError("simulated disk failure")
        return real_replace(source, destination)

    monkeypatch.setattr(module.os, "replace", fail_primary)
    before.append_exchange("not committed", "another answer")
    after = history(path)
    assert "saved" in after.handoff_for("codex").text
    assert "not committed" not in after.handoff_for("codex").text
    assert "save failed" in before.status()
    assert not list(tmp_path.glob("*.tmp"))


def test_retention_is_bounded_even_for_large_messages_and_many_small_ones(tmp_path):
    path = tmp_path / "context.json"
    before = SharedConversationHistory(1000, path=path)
    before.append_exchange("x" * 100_000, "y" * 100_000)
    assert sum(len(e.text) for e in before._entries) <= 4000
    for _ in range(300):
        before.append_exchange("x", "y")
    assert len(before._entries) <= 512
    assert SharedConversationHistory(1000, path=path).handoff_for("codex")


def test_unknown_roles_cannot_be_loaded_as_authoritative_instructions(tmp_path):
    path = tmp_path / "context.json"
    history(path).append_exchange("question", "answer")
    data = json.loads(path.read_text(encoding="utf-8"))
    data["entries"][0]["role"] = "System"
    path.write_text(json.dumps(data), encoding="utf-8")
    assert history(path).handoff_for("codex") is None
