"""REQ-OVL-004: native questions resolve once and expire cleanly."""

import asyncio
from queue import Queue
from types import SimpleNamespace

import pytest
from claude_agent_sdk import PermissionResultAllow

from modules.brain import PermissionGate
from modules.claude_brain import ClaudeBrain
from modules.codex_brain import CodexBrain
from modules.telegram_handler import TelegramHandler


def handler_for_test():
    handler = TelegramHandler.__new__(TelegramHandler)
    handler.owner_chat_id = 42
    handler.inbound_queue = Queue()
    handler._choice_for_chat = {}
    handler._choice_options = {}
    handler._ensure_choice_state()
    handler.sent = []

    async def send_message(**kwargs):
        handler.sent.append(kwargs)
        return SimpleNamespace(message_id=len(handler.sent))

    handler.bot = SimpleNamespace(send_message=send_message)
    return handler


def update(text, reply_to=None, owner=42):
    return SimpleNamespace(message=SimpleNamespace(
        chat_id=owner, text=text, reply_to_message=reply_to,
    ))


@pytest.mark.parametrize("text", [
    "/status@bot all", "/tokens 20", "/quote some text", "/model sonnet",
    "/effort high", "/brain codex",
])
def test_commands_preserve_arguments(text):
    handler = handler_for_test()
    asyncio.run(handler._handle_command(update(text), None))
    expected = text.replace("@bot", "")
    assert handler.inbound_queue.get_nowait() == (42, expected)


def test_unrelated_message_does_not_answer_pending_question():
    handler = handler_for_test()
    answers = []
    handler.on_choice_response = lambda *args: answers.append(args)

    async def scenario():
        await handler._ask_choice(42, "Which?", "q1", [("A", "")])
        await handler._handle_message(update("new guidance"), None)

    asyncio.run(scenario())
    assert answers == []
    assert handler._choice_for_chat == {42: "q1"}
    assert handler.inbound_queue.get_nowait() == (42, "new guidance")


@pytest.mark.parametrize("path", ["command", "reply", "typing"])
@pytest.mark.parametrize("brain_name", ["claude", "codex"])
def test_native_question_round_trip_is_exactly_once(path, brain_name, tmp_path):
    async def scenario():
        handler = handler_for_test()
        handler.loop = asyncio.get_running_loop()
        gate = PermissionGate(handler, owner=42, timeout=2)
        handler.on_choice_response = gate.on_choice_response
        options = [{"label": "A", "description": "First"}]
        if brain_name == "claude":
            brain = ClaudeBrain(
                gate=gate, cwd=str(tmp_path), model="test",
                session_file=tmp_path / "session",
            )
            pending = asyncio.create_task(brain._answer_user_questions({
                "questions": [{"question": "Which?", "options": options}],
            }))
        else:
            brain = CodexBrain(
                gate=gate, cwd=str(tmp_path), model="test",
                session_file=tmp_path / "session",
            )
            pending = asyncio.create_task(brain._request_user_input({
                "questions": [{
                    "id": "native-q", "question": "Which?", "options": options,
                }],
            }))
        for _ in range(20):
            if handler._choice_messages:
                break
            await asyncio.sleep(0)
        question_id = handler._choice_for_chat[42]
        if path == "command":
            await handler._handle_command(
                update(f"/reply {question_id} custom"), None
            )
        else:
            if path == "typing":
                handler._choice_typing.add(question_id)
                reply_to = None
            else:
                reply_to = SimpleNamespace(
                    message_id=handler._choice_messages[question_id]
                )
            await handler._handle_message(update("custom", reply_to), None)
        result = await pending
        if brain_name == "claude":
            assert isinstance(result, PermissionResultAllow)
            assert result.updated_input["answers"] == {"Which?": "custom"}
        else:
            assert result == {"answers": {"native-q": {"answers": ["custom"]}}}
        await handler._handle_command(
            update(f"/reply {question_id} stale"), None
        )
        assert "expired" in handler.sent[-1]["text"]
        assert gate.choice_pending == {}
        assert handler._choice_for_chat == {}

    asyncio.run(scenario())


def test_negative_button_index_is_rejected():
    handler = handler_for_test()
    answers = []
    handler.on_choice_response = lambda *args: answers.append(args)

    async def scenario():
        await handler._ask_choice(42, "Which?", "q1", [("A", "")])
        query = SimpleNamespace(message=SimpleNamespace(text="Which?"))
        await handler._handle_choice_callback(query, 42, "q1", "-1")

    asyncio.run(scenario())
    assert not answers
    assert handler._choice_for_chat == {42: "q1"}


def test_cancel_command_returns_no_answer_and_clears_typing():
    handler = handler_for_test()
    answers = []
    handler.on_choice_response = lambda *args: answers.append(args)

    async def scenario():
        await handler._ask_choice(42, "Which?", "q1", [("A", "")])
        handler._choice_typing.add("q1")
        await handler._handle_command(update("/cancelquestion q1"), None)
        await handler._handle_message(update("later message"), None)

    asyncio.run(scenario())
    assert answers == [("q1", "")]
    assert not handler._choice_typing
    assert handler.inbound_queue.get_nowait() == (42, "later message")


@pytest.mark.parametrize("kind", ["permission", "question"])
def test_cancelled_gate_ignores_late_responses(kind):
    async def scenario():
        handler = handler_for_test()
        handler.loop = asyncio.get_running_loop()
        gate = PermissionGate(handler, 42, 2)
        if kind == "permission":
            pending = asyncio.create_task(gate.request("Read", "file", ["file"]))
            registry = gate.pending
            callback = gate.on_permission_response
            response = "always"
        else:
            pending = asyncio.create_task(gate.choose("Which?", []))
            registry = gate.choice_pending
            callback = gate.on_choice_response
            response = "custom"
        await asyncio.sleep(0)
        request_id = next(iter(registry))
        pending.cancel()
        callback(request_id, response)
        with pytest.raises(asyncio.CancelledError):
            await pending
        await asyncio.sleep(0)
        assert registry == {}
        assert gate.auto_approve is False

    asyncio.run(scenario())
