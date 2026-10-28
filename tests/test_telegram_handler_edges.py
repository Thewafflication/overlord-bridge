"""Owner gating, command normalization, chunking, and retries in the Telegram layer."""

import asyncio
from queue import Queue
from types import SimpleNamespace

import pytest
from telegram.error import BadRequest, Conflict, NetworkError, RetryAfter, TelegramError

from modules import telegram_handler
from modules.telegram_handler import MAX_MESSAGE_LEN, TelegramHandler, _chunks


def make_handler():
    handler = TelegramHandler.__new__(TelegramHandler)
    handler.owner_chat_id = 42
    handler.inbound_queue = Queue()
    handler.loop = None
    handler._typing_tasks = {}
    handler._choice_for_chat = {}
    handler._choice_options = {}
    handler._permission_live = {}
    handler.on_permission_response = None
    handler.on_choice_response = None
    handler._ensure_choice_state()
    handler.sent = []

    async def send_message(**kwargs):
        handler.sent.append(kwargs)
        return SimpleNamespace(message_id=len(handler.sent))

    handler.bot = SimpleNamespace(send_message=send_message)
    return handler


def update(text, chat_id=42, reply_to=None):
    return SimpleNamespace(
        message=SimpleNamespace(chat_id=chat_id, text=text, reply_to_message=reply_to)
    )


def queued(handler):
    items = []
    while not handler.inbound_queue.empty():
        items.append(handler.inbound_queue.get_nowait())
    return items


def run(coro):
    return asyncio.run(coro)


def menu_query(data, chat_id=42):
    message = SimpleNamespace(chat_id=chat_id, message_id=100, text="", reply_markup=None)
    async def answer():
        pass
    async def edit_message_text(text, reply_markup=None):
        message.text = text
        message.reply_markup = reply_markup
    return SimpleNamespace(data=data, message=message, answer=answer,
                           edit_message_text=edit_message_text)


def test_menu_is_owner_only_and_does_not_start_a_model_turn():
    handler = make_handler()
    run(handler._handle_command(update("/menu", chat_id=666), None))
    assert handler.sent == []
    run(handler._handle_command(update("/start"), None))
    assert handler.sent[0]["reply_markup"].inline_keyboard
    assert queued(handler) == []


def test_menu_actions_are_allowlisted_and_owner_gated():
    handler = make_handler()
    for data, chat in [("menu:status", 666), ("menu:run:new", 42),
                       ("menu:new", 42), ("menu:/arbitrary", 42), ("menu:status", 42)]:
        run(handler._handle_callback(SimpleNamespace(callback_query=menu_query(data, chat)), None))
    assert queued(handler) == [(42, "/status")]


def test_session_button_requires_confirmation_and_cannot_be_replayed():
    handler = make_handler()
    query = menu_query("menu:confirm:new")
    run(handler._handle_callback(SimpleNamespace(callback_query=query), None))
    assert queued(handler) == []
    query.data = "menu:run:new"
    run(handler._handle_callback(SimpleNamespace(callback_query=query), None))
    run(handler._handle_callback(SimpleNamespace(callback_query=query), None))
    assert queued(handler) == [(42, "/new")]


def test_cancel_session_confirmation_invalidates_old_button():
    handler = make_handler()
    query = menu_query("menu:confirm:compact")
    for action in ("confirm:compact", "page:session", "run:compact"):
        query.data = "menu:" + action
        run(handler._handle_callback(SimpleNamespace(callback_query=query), None))
    assert queued(handler) == []


def test_native_command_menu_is_registered_only_for_owner():
    handler = make_handler()
    calls = []
    async def commands(**kwargs):
        calls.append(kwargs)
    handler.bot.set_my_commands = commands
    handler.bot.set_chat_menu_button = commands
    run(handler._register_command_menu())
    assert calls[0]["scope"].chat_id == 42
    assert {c.command for c in calls[0]["commands"]} == set(telegram_handler.COMMANDS)
    assert calls[1]["chat_id"] == 42


def test_pending_question_button_does_not_become_conversation_input():
    handler = make_handler()
    run(handler._handle_callback(SimpleNamespace(callback_query=menu_query("menu:questions")), None))
    assert handler.sent[0]["text"] == "No question is pending."
    assert queued(handler) == []


# ------------------------------------------------------------- owner gating
def test_plain_messages_from_strangers_are_dropped_and_the_owner_is_queued():
    handler = make_handler()
    run(handler._handle_message(update("let me in", chat_id=666), None))
    run(handler._handle_message(update("hello"), None))
    assert queued(handler) == [(42, "hello")]


def test_commands_from_strangers_are_dropped():
    handler = make_handler()
    run(handler._handle_command(update("/stop", chat_id=666), None))
    run(handler._handle_command(update("/reply abc yes", chat_id=666), None))
    assert queued(handler) == [] and handler.sent == []


def test_updates_without_a_message_are_ignored():
    handler = make_handler()
    run(handler._handle_message(SimpleNamespace(message=None), None))
    run(handler._handle_command(SimpleNamespace(message=None), None))
    run(handler._handle_callback(SimpleNamespace(callback_query=None), None))
    assert queued(handler) == []


# ------------------------------------------------------------ normalization
@pytest.mark.parametrize(
    "text, expected",
    [
        ("/NEW", "/new"),
        ("/new@OverlordBot now please", "/new"),
        ("/help me", "/help"),
        ("/stop everything", "/stop"),
        ("/steer  go left  ", "/steer go left"),
        ("/status", "/status"),
        ("/Status@bot ALL", "/status ALL"),
        ("/context", "/context"),
    ],
)
def test_commands_are_lowercased_and_only_some_keep_arguments(text, expected):
    handler = make_handler()
    run(handler._handle_command(update(text), None))
    assert queued(handler) == [(42, expected)]


def test_unknown_or_empty_commands_are_ignored():
    handler = make_handler()
    for text in ("/format_disk now", "", "   "):
        run(handler._handle_command(update(text), None))
    assert queued(handler) == []


def test_command_list_matches_what_the_bridge_dispatches():
    import bridge

    for command in ("new", "help", "status", "stop", "steer", "brain", "tokens", "quote",
                    "model", "effort", "permissions", "context", "compact"):
        assert command in telegram_handler.COMMANDS
        assert f"/{command}" in bridge.HELP_TEXT


# ------------------------------------------------------------------ chunking
@pytest.mark.parametrize(
    "length, pieces",
    [(0, 0), (1, 1), (MAX_MESSAGE_LEN, 1), (MAX_MESSAGE_LEN + 1, 2), (MAX_MESSAGE_LEN * 3, 3)],
)
def test_text_is_split_at_the_telegram_limit(length, pieces):
    text = "x" * length
    chunks = list(_chunks(text))
    assert len(chunks) == pieces
    assert "".join(chunks) == text
    assert all(len(chunk) <= MAX_MESSAGE_LEN for chunk in chunks)


def test_long_replies_are_delivered_in_order():
    handler = make_handler()
    text = "a" * MAX_MESSAGE_LEN + "b" * 10
    run(handler._send(42, text))
    assert [m["text"] for m in handler.sent] == ["a" * MAX_MESSAGE_LEN, "b" * 10]
    assert all(m["chat_id"] == 42 for m in handler.sent)


def test_sending_before_the_loop_exists_or_with_no_text_is_a_noop():
    handler = make_handler()
    handler.send(42, "hello")  # no loop yet
    handler.send(42, "")
    handler.begin_typing(42)
    handler.end_typing(42)
    handler.ask_permission(42, "?", "r1")
    handler.ask_choice(42, "?", "q1", [("a", "")])
    handler.cancel_permission(42, "r1")
    handler.cancel_choice(42, "q1")
    assert handler.sent == []


# ----------------------------------------------------------- question commands
def test_questions_command_reports_pending_state():
    handler = make_handler()
    run(handler._handle_command(update("/questions"), None))
    assert handler.sent[-1]["text"] == "No question is pending."

    async def scenario():
        await handler._ask_choice(42, "Which?", "q1", [("A", "first"), ("B", "")])
        await handler._handle_command(update("/questions"), None)

    run(scenario())
    text = handler.sent[-1]["text"]
    assert "Pending question: q1" in text and "Which?" in text and "/reply q1 <answer>" in text


def test_reply_and_cancel_commands_validate_the_question_id():
    handler = make_handler()
    answers = []
    handler.on_choice_response = lambda *args: answers.append(args)

    async def scenario():
        await handler._ask_choice(42, "Which?", "q1", [("A", "")])
        await handler._handle_command(update("/reply"), None)
        await handler._handle_command(update("/reply wrong yes"), None)
        await handler._handle_command(update("/reply q1"), None)
        await handler._handle_command(update("/reply q1    "), None)
        assert answers == []
        await handler._handle_command(update("/reply q1 option B, please"), None)
        assert answers == [("q1", "option B, please")]
        assert handler.sent[-1]["text"] == "Answer submitted."
        assert handler._choice_for_chat == {}
        await handler._handle_command(update("/cancelquestion q1"), None)
        assert handler.sent[-1]["text"] == "Question ID is missing or expired. Use /questions."

    run(scenario())


def test_cancelling_a_question_answers_with_nothing():
    handler = make_handler()
    answers = []
    handler.on_choice_response = lambda *args: answers.append(args)

    async def scenario():
        await handler._ask_choice(42, "Which?", "q1", [("A", "")])
        await handler._handle_command(update("/cancelquestion q1"), None)

    run(scenario())
    assert answers == [("q1", "")]
    assert handler.sent[-1]["text"] == "Question cancelled."


def test_a_new_question_supersedes_the_previous_one():
    handler = make_handler()
    answers = []
    handler.on_choice_response = lambda *args: answers.append(args)

    async def scenario():
        await handler._ask_choice(42, "First?", "q1", [("A", "")])
        await handler._ask_choice(42, "Second?", "q2", [("B", "")])

    run(scenario())
    assert answers == [("q1", "")]
    assert handler._choice_for_chat == {42: "q2"}
    assert "q1" not in handler._choice_options


def test_undeliverable_question_is_answered_empty_instead_of_hanging(monkeypatch):
    handler = make_handler()
    answers = []
    handler.on_choice_response = lambda *args: answers.append(args)

    async def broken(**kwargs):
        raise BadRequest("chat not found")

    handler.bot = SimpleNamespace(send_message=broken)
    run(handler._ask_choice(42, "Which?", "q1", [("A", "")]))
    assert answers == [("q1", "")]


# --------------------------------------------------------------- callbacks
class Query:
    def __init__(self, data, chat_id=42, text="prompt"):
        self.data = data
        self.message = SimpleNamespace(chat_id=chat_id, text=text)
        self.edits = []
        self.answered = False

    async def answer(self):
        self.answered = True

    async def edit_message_text(self, text):
        self.edits.append(text)


def press(handler, data, **kwargs):
    query = Query(data, **kwargs)
    run(handler._handle_callback(SimpleNamespace(callback_query=query), None))
    return query


@pytest.mark.parametrize("data", ["", "perm", "perm:r1", "other:r1:allow", "perm:r1:launch", None])
def test_malformed_or_unknown_callbacks_do_nothing(data):
    handler = make_handler()
    decisions = []
    handler.on_permission_response = lambda *args: decisions.append(args)
    handler._permission_live["r1"] = 42
    query = press(handler, data)
    assert decisions == [] and query.edits == [] and query.answered
    assert handler._permission_live == {"r1": 42}


def test_permission_buttons_from_other_chats_or_dead_requests_are_ignored():
    handler = make_handler()
    decisions = []
    handler.on_permission_response = lambda *args: decisions.append(args)
    handler._permission_live["r1"] = 42
    press(handler, "perm:r1:allow", chat_id=666)
    press(handler, "perm:ghost:allow")
    assert decisions == []
    press(handler, "perm:r1:allow")
    press(handler, "perm:r1:allow")  # a second tap on the same prompt
    assert decisions == [("r1", "allow")]


def test_failed_edit_does_not_lose_the_permission_decision():
    handler = make_handler()
    decisions = []
    handler.on_permission_response = lambda *args: decisions.append(args)
    handler._permission_live["r1"] = 42

    class Failing(Query):
        async def edit_message_text(self, text):
            raise BadRequest("message is not modified")

    query = Failing("perm:r1:deny")
    run(handler._handle_callback(SimpleNamespace(callback_query=query), None))
    assert decisions == [("r1", "deny")]


def test_choice_buttons_select_options_and_reject_bad_indexes():
    handler = make_handler()
    answers = []
    handler.on_choice_response = lambda *args: answers.append(args)

    async def ask():
        await handler._ask_choice(42, "Which?", "q1", [("Alpha", ""), ("Beta", "")])

    run(ask())
    for bad in ("choice:q1:9", "choice:q1:-1", "choice:q1:x", "choice:other:0"):
        press(handler, bad)
    assert answers == []
    query = press(handler, "choice:q1:1")
    assert answers == [("q1", "Beta")]
    assert query.edits[-1].endswith("✅ Selected: Beta")


def test_type_another_answer_then_free_text_resolves_the_question():
    handler = make_handler()
    answers = []
    handler.on_choice_response = lambda *args: answers.append(args)
    run(handler._ask_choice(42, "Which?", "q1", [("Alpha", "")]))
    press(handler, "choice:q1:other")
    run(handler._handle_message(update("   "), None))  # blank text is not an answer
    assert answers == [] and queued(handler) == []
    run(handler._handle_message(update("my own idea"), None))
    assert answers == [("q1", "my own idea")]
    assert queued(handler) == []  # consumed as the answer, not forwarded as a prompt


def test_replying_to_the_question_message_answers_it_but_other_replies_do_not():
    handler = make_handler()
    answers = []
    handler.on_choice_response = lambda *args: answers.append(args)
    run(handler._ask_choice(42, "Which?", "q1", [("Alpha", "")]))
    prompt_id = handler._choice_messages["q1"]
    run(handler._handle_message(update("elsewhere", reply_to=SimpleNamespace(message_id=999)), None))
    assert answers == [] and queued(handler) == [(42, "elsewhere")]
    run(handler._handle_message(update("here", reply_to=SimpleNamespace(message_id=prompt_id)), None))
    assert answers == [("q1", "here")]


# ----------------------------------------------------------------- retries
def retry(handler, errors, *, attempts=4):
    calls, delays = [], []

    async def operation():
        calls.append(1)
        if errors:
            raise errors.pop(0)

    async def fake_sleep(delay):
        delays.append(delay)

    real_sleep = asyncio.sleep
    asyncio.sleep = fake_sleep
    try:
        result = run(handler._telegram_call("t", operation, attempts=attempts))
    finally:
        asyncio.sleep = real_sleep
    return result, len(calls), delays


def test_network_errors_back_off_exponentially_up_to_a_cap():
    result, calls, delays = retry(
        make_handler(), [NetworkError("x")] * 5, attempts=6
    )
    assert result is True and calls == 6
    assert delays == [0.5, 1.0, 2.0, 4.0, 4.0]


@pytest.mark.filterwarnings("ignore::telegram.warnings.PTBDeprecationWarning")
def test_rate_limits_wait_the_requested_time():
    result, calls, delays = retry(make_handler(), [RetryAfter(7)])
    assert result is True and calls == 2
    assert delays == [7.0]


def test_permanent_errors_are_not_retried():
    for error in (BadRequest("chat not found"), TelegramError("nope"), ValueError("bug")):
        result, calls, delays = retry(make_handler(), [error])
        assert (result, calls, delays) == (False, 1, [])


def test_giving_up_after_the_last_attempt_reports_failure_without_sleeping_again():
    result, calls, delays = retry(make_handler(), [NetworkError("x")] * 9, attempts=3)
    assert result is False and calls == 3 and len(delays) == 2


def test_polling_errors_are_logged_without_raising(caplog):
    caplog.set_level("DEBUG", logger="overlord.telegram")
    TelegramHandler._polling_error(Conflict("terminated by other getUpdates request"))
    TelegramHandler._polling_error(NetworkError("reset"))
    TelegramHandler._polling_error(TelegramError("odd"))
    text = caplog.text
    assert "another Overlord instance" in text and "retrying" in text and "odd" in text


def test_typing_is_shared_by_overlapping_operations_and_refreshed_after_messages():
    async def scenario():
        handler = make_handler()
        actions = asyncio.Queue()
        async def action(**kwargs):
            await actions.put(kwargs)
        handler.bot.send_chat_action = action
        await handler._begin_typing(42)
        await asyncio.wait_for(actions.get(), timeout=1)
        original = handler._typing_tasks[42]
        await handler._begin_typing(42)
        assert handler._typing_tasks[42] is original
        await handler._end_typing(42)
        assert handler._typing_tasks[42] is original and not original.done()
        await handler._send(42, 'worker progress')
        refreshed = await asyncio.wait_for(actions.get(), timeout=1)
        assert refreshed['chat_id'] == 42
        await handler._end_typing(42)
        await asyncio.sleep(0)
        assert not handler._typing_tasks and not handler._typing_users
        assert not handler._typing_wakeups and original.done()
    run(scenario())


def test_command_arguments_offer_buttons_and_selection_runs_exact_command_once():
    handler = make_handler()
    run(handler._handle_command(update("/brain"), None))
    assert queued(handler) == [(42, "/brain")]
    sent = handler.sent[-1]
    button = sent["reply_markup"].inline_keyboard[2][0]
    assert button.text == "Free models"
    query = menu_query(button.callback_data)
    query.message.message_id = 1
    run(handler._handle_callback(SimpleNamespace(callback_query=query), None))
    run(handler._handle_callback(SimpleNamespace(callback_query=query), None))
    assert queued(handler) == [(42, "/brain free")]


def test_argument_picker_pages_long_unicode_values_and_rejects_stale_foreign_expired():
    handler = make_handler()
    options = [(f"Model {i}", "/model " + "模型" * 50 + str(i)) for i in range(18)]
    run(handler._send_command_options(42, "Models", options))
    picker = handler._command_picker
    markup = handler.sent[-1]["reply_markup"]
    assert all(len(b.callback_data.encode()) <= 64 for row in markup.inline_keyboard for b in row)
    query = menu_query(f"arg:{picker['token']}:page:2")
    query.message.message_id = picker['message_id']
    run(handler._handle_callback(SimpleNamespace(callback_query=query), None))
    assert query.message.reply_markup.inline_keyboard[0][0].text == "Model 14"
    query.data = f"arg:{picker['token']}:pick:17"
    query.message.chat_id = 666
    run(handler._handle_callback(SimpleNamespace(callback_query=query), None))
    assert queued(handler) == []
    query.message.chat_id = 42
    picker['expires'] = 0
    run(handler._handle_callback(SimpleNamespace(callback_query=query), None))
    assert queued(handler) == []
    run(handler._send_command_options(42, "New models", options))
    run(handler._handle_callback(SimpleNamespace(callback_query=query), None))
    assert queued(handler) == []
    current = handler._command_picker
    query.data = f"arg:{current['token']}:pick:17"
    query.message.message_id = current['message_id']
    run(handler._handle_callback(SimpleNamespace(callback_query=query), None))
    assert queued(handler) == [(42, options[17][1])]


def test_command_picker_cancel_and_other_messages_do_not_answer_ai_questions():
    handler = make_handler()
    handler._choice_for_chat[42] = "pending-question"
    run(handler._handle_command(update("/permissions"), None))
    picker=handler._command_picker
    query=menu_query(f"arg:{picker['token']}:cancel:0")
    query.message.message_id=picker['message_id']
    run(handler._handle_callback(SimpleNamespace(callback_query=query), None))
    assert handler._command_picker is None
    assert handler._choice_for_chat[42] == "pending-question"
    assert queued(handler) == [(42,"/permissions")]
