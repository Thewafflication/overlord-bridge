"""Routing of owner messages on the bridge's main loop."""

import asyncio
from types import SimpleNamespace

import bridge
from modules.conversation_history import SharedConversationHistory


class FakeTelegram:
    def __init__(self):
        self.messages = []

    def send(self, chat_id, text):
        self.messages.append((chat_id, text))

    def begin_typing(self, chat_id):
        pass

    def end_typing(self, chat_id):
        pass


class FakeBrain:
    name = "claude"
    model = "opus"
    effort = None
    supports_effort = True
    session_id = "s"

    def __init__(self):
        self.queries = []
        self.set_model_calls = []
        self.compactions = 0
        self.started = asyncio.Event()

    async def query(self, text):
        self.queries.append(text)
        self.started.set()
        await asyncio.Event().wait()
        yield ""

    async def interrupt_active_turn(self):
        return False

    async def set_model(self, model):
        self.set_model_calls.append(model)
        self.model = model

    async def compact(self, *, timeout=120):
        self.compactions += 1

    async def connect(self):
        pass

    async def disconnect(self):
        pass

    async def status(self, *, force_refresh=False):
        return {"brain": self.name, "model": self.model, "session_id": self.session_id}


def make_bridge(brain=None):
    instance = bridge.Bridge.__new__(bridge.Bridge)
    instance.brain = brain or FakeBrain()
    instance.brain_name = instance.brain.name
    instance.telegram = FakeTelegram()
    instance.gate = SimpleNamespace(pending={}, choice_pending={})
    instance._brain_lock = asyncio.Lock()
    instance._pending_handoff = None
    instance._status_timeout = 0.05
    instance.tokens = bridge.TokenLedger()
    instance._status_cache = {}
    instance._conversation_history = SharedConversationHistory()
    instance._conversation_history.mark_seen(instance.brain.name)
    instance.tray = SimpleNamespace(set_brain=lambda name: None)
    return instance


def run(coro):
    return asyncio.run(coro)


def test_context_and_compact_with_trailing_text_are_commands_not_prompts(tmp_path):
    # The Telegram layer forwards "/context now" verbatim; it must never reach the model.
    async def scenario():
        instance = make_bridge()
        instance._conversation_history = SharedConversationHistory(
            path=tmp_path / "conversation.json"
        )
        instance._status_cache = {"tokens": {"modelContextWindow": 1000}}
        await instance._dispatch_inbound(42, "/context please")
        assert "Retained conversation" in instance.telegram.messages[-1][1]
        await instance._dispatch_inbound(42, "/compact now")
        await instance._active_turn_task
        assert instance.brain.compactions == 1
        assert instance.brain.queries == []

    run(scenario())


def test_help_new_and_stop_dispatch_to_their_handlers(monkeypatch):
    async def scenario():
        instance = make_bridge()
        await instance._dispatch_inbound(42, "/help")
        assert instance.telegram.messages[-1][1] == bridge.HELP_TEXT
        await instance._dispatch_inbound(42, "/stop")
        assert instance.telegram.messages[-1][1] == "Nothing is running."

    run(scenario())


def test_plain_text_and_unknown_slash_text_start_a_turn():
    async def scenario():
        instance = make_bridge()
        await instance._dispatch_inbound(42, "/stopwatch please")
        await asyncio.wait_for(instance.brain.started.wait(), 1)
        assert instance.brain.queries == ["/stopwatch please"]
        instance._active_turn_task.cancel()
        try:
            await instance._active_turn_task
        except asyncio.CancelledError:
            pass

    run(scenario())


def test_blank_message_is_ignored():
    async def scenario():
        instance = make_bridge()
        await instance._dispatch_inbound(42, "   \n")
        assert instance.telegram.messages == []
        assert instance.brain.queries == []

    run(scenario())


def test_a_failing_handler_reports_and_does_not_unwind_the_main_loop(monkeypatch):
    async def scenario():
        instance = make_bridge()

        def explode(chat_id, text):
            raise RuntimeError("tokens exploded")

        monkeypatch.setattr(instance, "_handle_tokens", explode)
        await instance._dispatch_inbound(42, "/tokens 5")
        assert "tokens exploded" in instance.telegram.messages[-1][1]
        # The very next message is still served.
        await instance._dispatch_inbound(42, "/help")
        assert instance.telegram.messages[-1][1] == bridge.HELP_TEXT

    run(scenario())


def test_model_change_is_refused_instead_of_blocking_while_a_turn_runs():
    async def scenario():
        instance = make_bridge()
        await instance._dispatch_inbound(42, "work on it")
        await asyncio.wait_for(instance.brain.started.wait(), 1)
        # Hold the lock the way a real turn does; the handler must not wait for it.
        assert instance._brain_lock.locked()
        await asyncio.wait_for(instance._dispatch_inbound(42, "/model sonnet"), 0.5)
        assert instance.brain.set_model_calls == []
        assert "turn is active" in instance.telegram.messages[-1][1]
        # /stop is therefore still reachable.
        await asyncio.wait_for(instance._dispatch_inbound(42, "/stop"), 5)
        assert not instance._turn_is_active()

    run(scenario())


def test_model_query_without_a_value_still_works_during_a_turn():
    async def scenario():
        instance = make_bridge()
        await instance._dispatch_inbound(42, "work on it")
        await asyncio.wait_for(instance.brain.started.wait(), 1)
        await asyncio.wait_for(instance._dispatch_inbound(42, "/model"), 0.5)
        assert "Model [claude]: opus" in instance.telegram.messages[-1][1]
        await instance._dispatch_inbound(42, "/stop")

    run(scenario())


def test_brain_switch_is_refused_while_a_turn_runs(monkeypatch):
    async def scenario():
        instance = make_bridge()
        built = []
        monkeypatch.setattr(bridge, "build_brain", lambda gate, name: built.append(name))
        await instance._dispatch_inbound(42, "work on it")
        await asyncio.wait_for(instance.brain.started.wait(), 1)
        await asyncio.wait_for(instance._dispatch_inbound(42, "/brain codex"), 0.5)
        assert built == []
        assert "turn is active" in instance.telegram.messages[-1][1]
        await instance._dispatch_inbound(42, "/stop")

    run(scenario())


def test_brain_construction_failure_keeps_the_current_brain(monkeypatch, tmp_path):
    async def scenario():
        instance = make_bridge()

        def broken(gate, name):
            raise RuntimeError("codex is not installed")

        monkeypatch.setattr(bridge, "build_brain", broken)
        monkeypatch.setattr(bridge, "session_file_for", lambda name: tmp_path / name)
        await instance._dispatch_inbound(42, "/brain codex")
        assert instance.brain.name == "claude"
        assert "still using claude" in instance.telegram.messages[-1][1]
        assert "codex is not installed" in instance.telegram.messages[-1][1]

    run(scenario())


def test_env_loader_reads_utf8_and_a_byte_order_mark(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_bytes("﻿OVL_TEST_FIRST=one\nOVL_TEST_NAME=Zoë — ✓\n".encode("utf-8"))
    monkeypatch.delenv("OVL_TEST_FIRST", raising=False)
    monkeypatch.delenv("OVL_TEST_NAME", raising=False)
    bridge.load_env(env)
    try:
        assert bridge.os.environ["OVL_TEST_FIRST"] == "one"
        assert bridge.os.environ["OVL_TEST_NAME"] == "Zoë — ✓"
    finally:
        bridge.os.environ.pop("OVL_TEST_FIRST", None)
        bridge.os.environ.pop("OVL_TEST_NAME", None)


def test_env_helpers_fall_back_on_malformed_values(monkeypatch):
    monkeypatch.setenv("OVL_INT", "twelve")
    assert bridge.env_int("OVL_INT", 7) == 7
    monkeypatch.setenv("OVL_INT", "12")
    assert bridge.env_int("OVL_INT", 7) == 12
    monkeypatch.setenv("OVL_FIRST_A", "  ")
    monkeypatch.setenv("OVL_FIRST_B", "b")
    assert bridge.env_first(("OVL_FIRST_A", "OVL_FIRST_B")) == "b"
    monkeypatch.setenv("OVL_BOOL", " YES ")
    assert bridge.env_bool("OVL_BOOL") is True
    monkeypatch.setenv("OVL_BOOL", "nope")
    assert bridge.env_bool("OVL_BOOL", True) is False


def test_env_loader_survives_a_hand_edited_ansi_file(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_bytes(b"OVL_TEST_ANSI=caf\xe9\nOVL_TEST_NEXT=ok\n")  # cp1252, not UTF-8
    monkeypatch.delenv("OVL_TEST_ANSI", raising=False)
    monkeypatch.delenv("OVL_TEST_NEXT", raising=False)
    bridge.load_env(env)
    try:
        assert bridge.os.environ["OVL_TEST_ANSI"] == "café"
        assert bridge.os.environ["OVL_TEST_NEXT"] == "ok"
    finally:
        bridge.os.environ.pop("OVL_TEST_ANSI", None)
        bridge.os.environ.pop("OVL_TEST_NEXT", None)
