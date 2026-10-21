import asyncio
from queue import Queue
from types import SimpleNamespace

import bridge
from modules.telegram_handler import TelegramHandler


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


class BlockingBrain:
    name = "test"
    model = "test-model"
    session_id = "session-1"

    def __init__(self):
        self.queries = []
        self.started = asyncio.Event()
        self.cancelled = asyncio.Event()
        self.status_release = asyncio.Event()
        self.status_calls = []

    async def query(self, text):
        self.queries.append(text)
        if len(self.queries) > 1:
            yield "redirected"
            return
        self.started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            self.cancelled.set()
            raise
        if False:
            yield ""

    async def interrupt_active_turn(self):
        return False

    async def status(self, *, force_refresh: bool = False):
        self.status_calls.append(force_refresh)
        await self.status_release.wait()
        return {"brain": self.name, "model": self.model, "session_id": self.session_id}


def make_bridge(brain):
    instance = bridge.Bridge.__new__(bridge.Bridge)
    instance.brain = brain
    instance.telegram = FakeTelegram()
    instance._brain_lock = asyncio.Lock()
    instance._active_turn_task = None
    instance._status_cache = instance._basic_status()
    instance._pending_handoff = None
    instance.tokens = bridge.TokenLedger()
    instance._status_timeout = 0.05
    instance._conversation_history = bridge.SharedConversationHistory()
    instance._conversation_history.mark_seen(brain.name)
    return instance


def test_status_asks_for_a_fresh_reading_and_falls_back_to_cache_if_it_stalls():
    async def scenario():
        brain = BlockingBrain()
        instance = make_bridge(brain)
        await instance._handle_status(42)
        # A live refresh was attempted, and explicitly asked to bypass caches...
        assert brain.status_calls == [True]
        # ...but a provider that never answers must not hang the command.
        assert "Turn: idle" in instance.telegram.messages[-1][1]
        assert "Model: test-model" in instance.telegram.messages[-1][1]

    asyncio.run(scenario())


def test_stop_cancels_an_active_turn_without_waiting_for_the_inbound_loop():
    async def scenario():
        brain = BlockingBrain()
        instance = make_bridge(brain)
        assert instance._start_turn(42, "long task") is True
        await brain.started.wait()
        await instance._handle_stop(42)
        assert brain.cancelled.is_set()
        assert instance.telegram.messages[-1] == (42, "⏹️ Stopping the active turn…")

    asyncio.run(scenario())


def test_stop_cancels_background_workers_even_when_chat_turn_is_idle():
    async def scenario():
        from modules.brain import PermissionGate
        from tests.test_permission_gate import FakeTelegram as GateTelegram

        instance = make_bridge(BlockingBrain())
        cleaned = asyncio.Event()
        gate = PermissionGate(GateTelegram(), 42, 60)

        async def worker():
            try:
                await gate.request("Write", "worker", ["app.py"])
            finally:
                cleaned.set()

        task = asyncio.create_task(worker())
        instance.workers = SimpleNamespace(_running={"Free-project": task})
        await asyncio.sleep(0)
        assert gate.pending
        await instance._handle_stop(42)
        assert cleaned.is_set()
        assert not gate.pending
        assert task.cancelled()
        assert not instance.workers._running
        assert instance.telegram.messages[-1] == (42, "Workers stopped.")

    asyncio.run(scenario())


def test_stalled_interrupt_and_cleanup_do_not_hang_or_start_replacement(monkeypatch):
    monkeypatch.setattr(bridge, "STOP_INTERRUPT_TIMEOUT", 0.01)
    monkeypatch.setattr(bridge, "STOP_CLEANUP_TIMEOUT", 0.01)
    async def scenario():
        brain = BlockingBrain()
        instance = make_bridge(brain)
        release = asyncio.Event()
        async def interrupt():
            await asyncio.Event().wait()
        brain.interrupt_active_turn = interrupt
        async def cleanup():
            while not release.is_set():
                try:
                    await release.wait()
                except asyncio.CancelledError:
                    continue
        task = asyncio.create_task(cleanup())
        instance._active_turn_task = task
        await asyncio.sleep(0)
        try:
            assert not await asyncio.wait_for(instance._stop_active_turn(), 0.2)
            await instance._handle_steer(42, "/steer replacement")
            await instance._reset_session(42)
            assert not task.done()
            assert brain.queries == []
            assert "cleanup" in instance.telegram.messages[-1][1]
        finally:
            release.set()
            await task
    asyncio.run(scenario())


def test_steer_replaces_the_active_turn_after_cleanup():
    async def scenario():
        brain = BlockingBrain()
        instance = make_bridge(brain)
        instance._start_turn(42, "old guidance")
        await brain.started.wait()
        await instance._handle_steer(42, "/steer new guidance")
        await instance._active_turn_task
        assert brain.cancelled.is_set()
        assert brain.queries == ["old guidance", "new guidance"]
        assert instance.telegram.messages[-2:] == [
            (42, "↪️ Steering the active turn…"),
            (42, "redirected"),
        ]

    asyncio.run(scenario())


def test_steer_requires_guidance():
    async def scenario():
        instance = make_bridge(BlockingBrain())
        await instance._handle_steer(42, "/steer")
        assert instance.telegram.messages[-1] == (42, "Usage: /steer <new guidance>")

    asyncio.run(scenario())


def test_stop_and_steer_commands_are_normalized_for_the_bridge():
    handler = TelegramHandler.__new__(TelegramHandler)
    handler.owner_chat_id = 42
    handler.inbound_queue = Queue()

    async def deliver(text):
        update = SimpleNamespace(message=SimpleNamespace(chat_id=42, text=text))
        await handler._handle_command(update, None)

    asyncio.run(deliver("/stop@overlord_bot"))
    asyncio.run(deliver("/steer@overlord_bot focus on tests"))

    assert handler.inbound_queue.get_nowait() == (42, "/stop")
    assert handler.inbound_queue.get_nowait() == (42, "/steer focus on tests")
