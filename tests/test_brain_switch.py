import asyncio
from types import SimpleNamespace

import bridge
from modules.conversation_history import SharedConversationHistory


class FakeTelegram:
    def __init__(self):
        self.messages = []
        self.activity = []

    def send(self, chat_id, text):
        self.messages.append((chat_id, text))

    def begin_typing(self, chat_id):
        self.activity.append(("begin", chat_id))

    def end_typing(self, chat_id):
        self.activity.append(("end", chat_id))


class FakeTray:
    def __init__(self):
        self.brains = []

    def set_brain(self, brain_name):
        self.brains.append(brain_name)


class FakeBrain:
    def __init__(self, name, events, connect_error=None):
        self.name = name
        self.events = events
        self.connect_error = connect_error
        self.queries = []

    async def connect(self):
        self.events.append(f"connect:{self.name}")
        if self.connect_error:
            raise self.connect_error

    async def disconnect(self):
        self.events.append(f"disconnect:{self.name}")

    async def query(self, text):
        self.queries.append(text)
        yield "Done."


def make_bridge(active_brain):
    instance = bridge.Bridge.__new__(bridge.Bridge)
    instance.brain = active_brain
    instance.brain_name = active_brain.name
    instance.gate = SimpleNamespace()
    instance.telegram = FakeTelegram()
    instance._brain_lock = asyncio.Lock()
    instance._conversation_history = SharedConversationHistory()
    instance._conversation_history.mark_seen(active_brain.name)
    instance._pending_handoff = None
    instance.tray = FakeTray()
    return instance


def test_brain_switch_connects_replacement_before_disconnect_and_persists(
    monkeypatch, tmp_path
):
    events = []
    old = FakeBrain("claude", events)
    replacement = FakeBrain("codex", events)
    instance = make_bridge(old)
    persisted = []

    monkeypatch.setattr(bridge, "build_brain", lambda gate, name: replacement)
    monkeypatch.setattr(bridge, "session_file_for", lambda name: tmp_path / name)
    monkeypatch.setattr(
        bridge,
        "set_env_value",
        lambda path, key, value: persisted.append((key, value)),
    )

    asyncio.run(instance._handle_brain(42, "/brain codex"))

    assert instance.brain is replacement
    assert instance.brain_name == "codex"
    assert events == ["connect:codex", "disconnect:claude"]
    assert persisted == [("OVERLORD_BRAIN", "codex")]
    assert instance.tray.brains == ["codex"]
    assert "Switched to codex" in instance.telegram.messages[-1][1]


def test_failed_brain_switch_keeps_current_brain(monkeypatch, tmp_path):
    events = []
    old = FakeBrain("claude", events)
    replacement = FakeBrain("codex", events, RuntimeError("not authenticated"))
    instance = make_bridge(old)
    persisted = []

    monkeypatch.setattr(bridge, "build_brain", lambda gate, name: replacement)
    monkeypatch.setattr(bridge, "session_file_for", lambda name: tmp_path / name)
    monkeypatch.setattr(
        bridge,
        "set_env_value",
        lambda path, key, value: persisted.append((key, value)),
    )

    asyncio.run(instance._handle_brain(42, "/brain codex"))

    assert instance.brain is old
    assert instance.brain_name == "claude"
    assert events == ["connect:codex", "disconnect:codex"]
    assert persisted == []
    assert "still using claude" in instance.telegram.messages[-1][1]


def test_switch_queues_only_context_the_target_has_not_seen(monkeypatch, tmp_path):
    events = []
    old = FakeBrain("claude", events)
    replacement = FakeBrain("codex", events)
    instance = make_bridge(old)
    instance._conversation_history.append_exchange("Fix it", "I fixed it.")
    instance._conversation_history.mark_seen("claude")

    monkeypatch.setattr(bridge, "build_brain", lambda gate, name: replacement)
    monkeypatch.setattr(bridge, "session_file_for", lambda name: tmp_path / name)
    monkeypatch.setattr(bridge, "set_env_value", lambda path, key, value: None)

    asyncio.run(instance._handle_brain(42, "/brain codex"))

    assert instance._pending_handoff is not None
    assert "User: Fix it" in instance._pending_handoff.text
    assert "Assistant: I fixed it." in instance._pending_handoff.text
    assert "recent messages will be handed over" in instance.telegram.messages[-1][1]


def test_first_turn_after_switch_receives_handoff_once():
    events = []
    brain = FakeBrain("codex", events)
    instance = make_bridge(brain)
    instance._conversation_history.append_exchange("Earlier task", "Earlier result")
    instance._pending_handoff = instance._conversation_history.handoff_for("codex")

    asyncio.run(instance._handle_turn(42, "What next?"))
    asyncio.run(instance._handle_turn(42, "And now?"))

    assert "BEGIN PRIOR CONVERSATION" in brain.queries[0]
    assert "Earlier result" in brain.queries[0]
    assert brain.queries[0].endswith("What next?")
    assert brain.queries[1] == "And now?"
    assert instance._pending_handoff is None
    assert instance.telegram.activity == [
        ("begin", 42),
        ("end", 42),
        ("begin", 42),
        ("end", 42),
    ]
