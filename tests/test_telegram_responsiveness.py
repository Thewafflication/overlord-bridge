import asyncio

from telegram.error import NetworkError

from modules.telegram_handler import TelegramHandler


def test_transient_telegram_call_is_retried(monkeypatch):
    handler = TelegramHandler.__new__(TelegramHandler)
    attempts = []

    async def operation():
        attempts.append(1)
        if len(attempts) < 3:
            raise NetworkError("temporary TLS failure")
        return object()

    async def no_sleep(delay):
        return None

    monkeypatch.setattr(asyncio, "sleep", no_sleep)
    delivered = asyncio.run(handler._telegram_call("test", operation))

    assert delivered is True
    assert len(attempts) == 3


def test_undeliverable_permission_prompt_is_denied(monkeypatch):
    decisions = []
    handler = TelegramHandler.__new__(TelegramHandler)
    handler.on_permission_response = (
        lambda request_id, allowed: decisions.append((request_id, allowed))
    )
    handler.bot = object()

    async def never_delivered(label, operation, attempts=4, quiet=False):
        return False

    monkeypatch.setattr(handler, "_telegram_call", never_delivered)
    asyncio.run(handler._ask_permission(42, "Allow?", "request-1"))

    assert decisions == [("request-1", False)]


def test_telegram_thread_initialization_retries_before_polling(monkeypatch):
    handler = TelegramHandler.__new__(TelegramHandler)
    handler.loop = None
    handler._ready = __import__("threading").Event()
    calls = []

    class FakeUpdater:
        async def start_polling(self, bootstrap_retries, error_callback):
            calls.append(("poll", bootstrap_retries, error_callback))

    class FakeApplication:
        updater = FakeUpdater()

        async def initialize(self):
            calls.append("initialize")

        async def start(self):
            calls.append("start")

    handler.application = FakeApplication()

    async def successful_retry(label, operation, attempts=4, quiet=False):
        calls.append((label, attempts))
        await operation()
        return True

    monkeypatch.setattr(handler, "_telegram_call", successful_retry)
    started = asyncio.run(handler._initialize_application())

    assert started is True
    assert ("Telegram initialization", 6) in calls
    polling = next(call for call in calls if isinstance(call, tuple) and call[0] == "poll")
    assert polling[1] == 5
    assert polling[2] == handler._polling_error
