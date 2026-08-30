import asyncio
from queue import Queue
from types import SimpleNamespace

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

    assert decisions == [("request-1", "deny")]


def test_permission_prompt_offers_three_choices(monkeypatch):
    handler = TelegramHandler.__new__(TelegramHandler)
    handler.on_permission_response = lambda request_id, decision: None
    sent = []

    class FakeBot:
        async def send_message(self, **kwargs):
            sent.append(kwargs)

    handler.bot = FakeBot()

    async def deliver(label, operation, attempts=4, quiet=False):
        await operation()
        return True

    monkeypatch.setattr(handler, "_telegram_call", deliver)
    asyncio.run(handler._ask_permission(42, "Allow?", "request-1"))

    buttons = [
        button
        for row in sent[0]["reply_markup"].inline_keyboard
        for button in row
    ]
    assert [button.text for button in buttons] == [
        "✅ Allow once",
        "⛔ Deny",
        "⚡ Always allow (this run)",
    ]
    assert buttons[-1].callback_data == "perm:request-1:always"


def test_always_callback_is_forwarded_and_explained():
    decisions = []
    edits = []
    handler = TelegramHandler.__new__(TelegramHandler)
    handler.owner_chat_id = 42
    handler.on_permission_response = (
        lambda request_id, decision: decisions.append((request_id, decision))
    )

    class FakeQuery:
        data = "perm:request-1:always"
        message = SimpleNamespace(chat_id=42, text="Permission request")

        async def answer(self):
            return None

        async def edit_message_text(self, text):
            edits.append(text)

    update = SimpleNamespace(callback_query=FakeQuery())
    asyncio.run(handler._handle_callback(update, None))

    assert decisions == [("request-1", "always")]
    assert "until Overlord restarts" in edits[0]


def test_model_choice_buttons_return_selected_label(monkeypatch):
    answers = []
    sent = []
    edits = []
    handler = TelegramHandler.__new__(TelegramHandler)
    handler.owner_chat_id = 42
    handler.on_choice_response = (
        lambda request_id, answer: answers.append((request_id, answer))
    )
    handler._choice_for_chat = {}
    handler._choice_options = {}

    class FakeBot:
        async def send_message(self, **kwargs):
            sent.append(kwargs)

    handler.bot = FakeBot()

    async def deliver(label, operation, attempts=4, quiet=False):
        await operation()
        return True

    monkeypatch.setattr(handler, "_telegram_call", deliver)

    async def scenario():
        await handler._ask_choice(
            42,
            "Which approach?",
            "choice-1",
            [("Fast", "Less validation"), ("Safe", "More validation")],
        )

        class FakeQuery:
            data = "choice:choice-1:1"
            message = SimpleNamespace(chat_id=42, text="Which approach?")

            async def answer(self):
                return None

            async def edit_message_text(self, text):
                edits.append(text)

        await handler._handle_callback(
            SimpleNamespace(callback_query=FakeQuery()), None
        )

    asyncio.run(scenario())

    buttons = sent[0]["reply_markup"].inline_keyboard
    assert buttons[0][0].text == "Fast"
    assert buttons[-1][0].text == "✍️ Type another answer"
    assert answers == [("choice-1", "Safe")]
    assert "Selected: Safe" in edits[0]


def test_typed_message_answers_pending_model_question():
    answers = []
    handler = TelegramHandler.__new__(TelegramHandler)
    handler.owner_chat_id = 42
    handler.inbound_queue = Queue()
    handler.on_choice_response = (
        lambda request_id, answer: answers.append((request_id, answer))
    )
    handler._choice_for_chat = {42: "choice-1"}
    handler._choice_options = {"choice-1": ["A", "B"]}
    update = SimpleNamespace(
        message=SimpleNamespace(chat_id=42, text="Something else")
    )

    asyncio.run(handler._handle_message(update, None))

    assert answers == [("choice-1", "Something else")]
    assert handler.inbound_queue.empty()


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
