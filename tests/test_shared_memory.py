import asyncio
import json
from concurrent.futures import ThreadPoolExecutor

import pytest

from modules.shared_memory import SharedMemory
from test_free_brain import make, reply


def test_memory_survives_new_instances_and_supports_updates_and_forgetting(tmp_path):
    path = tmp_path / "memory.json"
    memory = SharedMemory(path)
    entry_id = memory.remember("preference", "Keep replies concise")
    resumed = SharedMemory(path)
    assert "Keep replies concise" in resumed.context()
    assert resumed.remember("preference", "Explain detail when asked", entry_id) == entry_id
    assert "Keep replies concise" not in memory.context()
    memory.forget(entry_id)
    assert resumed.entries() == []


def test_concurrent_engine_writes_do_not_lose_entries(tmp_path):
    path = tmp_path / "memory.json"
    def write(index):
        return SharedMemory(path).remember("project", f"Decision {index}")
    with ThreadPoolExecutor(max_workers=3) as pool:
        ids = list(pool.map(write, range(12)))
    assert len(set(ids)) == len(SharedMemory(path).entries()) == 12


def test_corrupt_memory_is_not_silently_overwritten(tmp_path):
    path = tmp_path / "memory.json"
    path.write_text("broken", encoding="utf-8")
    memory = SharedMemory(path)
    with pytest.raises(ValueError):
        memory.remember("project", "Do not destroy the old notes")
    assert path.read_text() == "broken"
    assert "could not be loaded" in memory.turn_context()


def test_worker_results_are_labelled_and_latest_report_replaces_prior_report(tmp_path):
    memory = SharedMemory(tmp_path / "memory.json")
    report = {"name": "Worker1", "folder": "project", "status": "finished", "result_tail": "First claim"}
    memory.remember_worker(report)
    memory.remember_worker({**report, "result_tail": "New claim"})
    assert len(memory.entries()) == 1
    assert "Worker-reported result: New claim" in memory.context()
    assert "First claim" not in memory.context()


def test_context_is_bounded_and_preferences_are_retained(tmp_path):
    memory = SharedMemory(tmp_path / "memory.json")
    memory.remember("preference", "Owner preference")
    for index in range(12):
        memory.remember("project", f"Project {index}: " + "x" * 1900)
    context = memory.context()
    assert "Owner preference" in context
    assert "older entries omitted" in context
    assert len(context) < 16_500
    assert len(memory.entries()) == 13


def test_free_mode_can_remember_without_project_tools(tmp_path, monkeypatch):
    memory = SharedMemory(tmp_path / "memory.json")
    response = reply("")
    response[2]["choices"][0]["message"]["tool_calls"] = [{"id": "memory1", "type": "function", "function": {
        "name": "shared_memory", "arguments": json.dumps({
            "action": "remember", "category": "preference", "text": "Use concise replies",
        })}}]
    brain = make(tmp_path, monkeypatch, [response], developer_instructions="Canonical instruction marker")
    async def ask():
        return [part async for part in brain.query("Remember my reply preference", shared_memory=memory)]
    assert "Remembered for all three engines" in asyncio.run(ask())[0]
    assert memory.entries()[0]["text"] == "Use concise replies"
    assert "Canonical instruction marker" in brain.calls[0][1]["messages"][0]["content"]


def test_native_helper_can_read_the_same_store(tmp_path):
    import subprocess
    import sys
    from modules import shared_memory
    path = tmp_path / "memory.json"
    memory = SharedMemory(path)
    entry_id = memory.remember("project", "Next: verify release artifact")
    result = subprocess.run([sys.executable, shared_memory.__file__, "--store", str(path), "list"],
                            capture_output=True, text=True, check=True)
    assert json.loads(result.stdout)[0]["id"] == entry_id


@pytest.mark.parametrize("engine", ["claude", "codex"])
def test_bridge_supplies_current_memory_to_each_native_engine(tmp_path, engine):
    from test_brain_switch import FakeBrain
    from test_bridge_support import make_bridge
    brain = FakeBrain(engine, [])
    instance = make_bridge(tmp_path, brain)
    instance.shared_memory = SharedMemory(tmp_path / "memory.json")
    entry_id = instance.shared_memory.remember("preference", "Old preference")
    asyncio.run(instance._handle_turn(42, "What do you know?"))
    assert "Old preference" in brain.queries[-1]
    instance.shared_memory.remember("preference", "Updated preference", entry_id)
    asyncio.run(instance._handle_turn(42, "And now?"))
    assert "Updated preference" in brain.queries[-1]
    assert "Old preference" not in brain.queries[-1]


def test_worker_report_is_available_to_other_engines_even_when_native_injection_is_disabled(tmp_path, monkeypatch):
    import bridge
    from test_bridge_support import make_bridge, REPORT
    instance = make_bridge(tmp_path)
    instance.shared_memory = SharedMemory(tmp_path / "memory.json")
    for flag in ("WORKER_REPORT_TO_THREAD", "WORKER_REPORT_VISIBLE_TURN", "WORKER_REPORT_CLI_FEED", "WORKER_REPORT_TERMINAL_INJECT"):
        monkeypatch.setattr(bridge, flag, False)
    asyncio.run(instance._handle_worker_report(REPORT))
    assert "all green" in SharedMemory(instance.shared_memory.path).context()


def test_free_snapshot_is_current_and_not_duplicated_into_saved_history(tmp_path, monkeypatch):
    memory = SharedMemory(tmp_path / "memory.json")
    entry_id = memory.remember("preference", "First preference")
    brain = make(tmp_path, monkeypatch, [reply("OK"), reply("OK")])
    async def ask():
        return [part async for part in brain.query("Hello", shared_memory=memory)]
    asyncio.run(ask())
    memory.remember("preference", "New preference", entry_id)
    asyncio.run(ask())
    messages = brain.calls[-1][1]["messages"]
    assert "New preference" in messages[-1]["content"]
    assert "New preference" not in messages[0]["content"]  # notes are context, not system instructions
    assert "First preference" not in str(messages)
    assert "preference" not in str(brain._history)
