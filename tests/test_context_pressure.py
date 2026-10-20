import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from modules.context_pressure import ContextPolicy, snapshot_for
from test_free_brain import make, reply


def snapshot(used=80, maximum=100):
    return {"used": used, "maximum": maximum, "session_id": "s", "model": "m",
            "observed_at": datetime.now(timezone.utc).isoformat()}


def test_stale_or_mismatched_readings_cannot_trigger_policy():
    brain = SimpleNamespace(session_id="s", model="m", context_snapshot=snapshot())
    assert snapshot_for(brain)["percentage"] == 80
    brain.context_snapshot["observed_at"] = (datetime.now(timezone.utc) - timedelta(minutes=11)).isoformat()
    assert snapshot_for(brain) is None
    brain.context_snapshot = snapshot()
    brain.context_snapshot["session_id"] = "old"
    assert snapshot_for(brain) is None
    brain.context_snapshot = snapshot(used=True)
    assert snapshot_for(brain) is None


def test_threshold_alerts_and_attempts_are_deduplicated_and_rearm_after_pressure_drops():
    policy = ContextPolicy(75, 85, True)
    brain = SimpleNamespace(name="codex", session_id="s", model="m")
    assert policy.action(brain, {"percentage": 74}) is None
    assert policy.action(brain, {"percentage": 75}) == "warn"
    assert policy.action(brain, {"percentage": 80}) is None
    assert policy.action(brain, {"percentage": 85}) == "compact"
    assert policy.action(brain, {"percentage": 95}) is None
    assert policy.action(brain, {"percentage": 60}) is None
    assert policy.action(brain, {"percentage": 85}) == "compact"


def test_warn_only_mode_never_compacts():
    policy = ContextPolicy(75, 85, False)
    brain = SimpleNamespace(name="claude", session_id="s", model="m")
    assert policy.action(brain, {"percentage": 90}) == "warn"
    assert policy.action(brain, {"percentage": 99}) is None


def test_codex_context_uses_last_observation_not_cumulative_billing(tmp_path):
    from test_codex_brain_edges import make_brain
    brain = make_brain(tmp_path)
    brain._handle_notification("thread/tokenUsage/updated", {"threadId": "thread", "tokenUsage": {
        "total": {"totalTokens": 900000}, "last": {"totalTokens": 800}, "modelContextWindow": 1000,
    }})
    assert snapshot_for(brain)["used"] == 800
    assert snapshot_for(brain)["percentage"] == 80
    brain._handle_notification("item/completed", {"threadId": "thread", "item": {"type": "contextCompaction"}})
    assert snapshot_for(brain) is None


def test_automatic_compaction_runs_after_reply_and_checkpoints_first(tmp_path):
    from test_bridge_support import make_bridge
    from test_brain_switch import FakeBrain
    brain = FakeBrain("codex", [])
    brain.model, brain.session_id = "m", "s"
    brain.context_snapshot = snapshot(90)
    instance = make_bridge(tmp_path, brain)
    instance.context_policy = ContextPolicy(75, 85, True)
    calls = []
    async def compact():
        assert instance._conversation_history.path.exists()
        assert any(text == "Done." for _, text in instance.telegram.messages)
        calls.append(True)
    brain.compact = compact
    asyncio.run(instance._handle_turn(42, "Work"))
    assert calls == [True]
    asyncio.run(instance._manage_context(42))
    assert calls == [True]


def test_pending_approval_defers_compaction_without_consuming_the_attempt(tmp_path):
    from test_bridge_support import make_bridge
    instance = make_bridge(tmp_path)
    instance.brain.context_snapshot = {**snapshot(90), "session_id": "sess", "model": "opus"}
    instance.context_policy = ContextPolicy(75, 85, True)
    instance.gate.pending["request"] = object()
    asyncio.run(instance._manage_context(42))
    assert instance.telegram.messages == []
    instance.gate.pending.clear()
    asyncio.run(instance._manage_context(42))
    assert ("compact", None) in instance.brain.events


def test_free_compaction_preserves_latest_exchange_and_backup(tmp_path, monkeypatch):
    brain = make(tmp_path, monkeypatch, [reply("Owner wants concise replies. Project fix remains unverified.")])
    brain._history = [{"role": role, "content": f"{i}: " + "content " * 100}
                      for i in range(4) for role in ("user", "assistant")]
    original = list(brain._history)
    brain._save_history()
    assert asyncio.run(brain.compact()) is None
    assert brain._history[-2:] == original[-2:]
    assert brain._load_history() == brain._history
    assert brain.session_file.with_suffix(".precompact").exists()
    assert len(brain._history) == 4
    assert "tools" not in brain.calls[0][1]


def test_free_unhelpful_summary_preserves_original_history(tmp_path, monkeypatch):
    brain = make(tmp_path, monkeypatch, [reply("too long " * 1000)])
    brain._history = [{"role": role, "content": "old " * 50}
                      for _ in range(3) for role in ("user", "assistant")]
    original = list(brain._history)
    assert "did not reduce" in asyncio.run(brain.compact())
    assert brain._history == original
