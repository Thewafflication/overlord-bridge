import asyncio
import json
import pytest
from queue import Queue

from modules.console_transport import ConsoleTransport
from modules.brain import PermissionGate


def make(tmp_path):
    messages, permissions, answers = [], [], []
    transport = ConsoleTransport(tmp_path / 'prompts.json', Queue(), 0,
                                 lambda *args: messages.append(args),
                                 lambda *args: permissions.append(args),
                                 lambda *args: answers.append(args))
    return transport, messages, permissions, answers


def test_local_chat_and_prompt_answers_need_no_telegram(tmp_path):
    transport, messages, permissions, answers = make(tmp_path)
    transport.start()
    assert transport.wait_ready()
    transport.send(0, 'hello')
    assert messages == [(0, 'hello')]
    transport.ask_permission(0, 'run a command?', 'approval')
    assert not transport.respond('approval', 'forged')
    assert transport.respond('approval', 'allow')
    assert not transport.respond('approval', 'allow')
    assert permissions == [('approval', 'allow')]
    transport.ask_choice(0, 'Which project?', 'question', [('A', 'first')])
    assert transport.respond('question', 'my own answer')
    assert answers == [('question', 'my own answer')]
    transport.begin_typing(0)
    assert json.loads(transport.path.read_text())['typing']
    transport.end_typing(0)
    transport.stop()
    assert json.loads(transport.path.read_text())['requests'] == {}


def test_local_option_picker_is_exact_expiring_and_does_not_cancel_questions(tmp_path):
    transport, *_ = make(tmp_path)
    transport.ask_choice(0, 'Question', 'q', [])
    transport.send_command_options(0, 'Models', [('A', '/model a')])
    command_id = next(key for key in transport.requests if key != 'q')
    assert not transport.respond(command_id, '/model forged')
    assert transport.respond(command_id, '/model a')
    assert transport.inbound.get_nowait() == (0, '/model a')
    assert 'q' in transport.requests
    transport.send_command_options(0, 'Models', [('B', '/model b')])
    command_id = next(key for key in transport.requests if key != 'q')
    transport.requests[command_id]['expires'] = 0
    assert not transport.respond(command_id, '/model b')


def test_permission_gate_and_questions_resolve_through_console(tmp_path):
    async def scenario():
        gate = PermissionGate(telegram=None, owner=0, timeout=1)
        transport = ConsoleTransport(tmp_path / 'prompts.json', Queue(), 0, lambda *a: None,
                                     gate.on_permission_response, gate.on_choice_response)
        gate.telegram = transport
        task = asyncio.create_task(gate.choose('Choose', [('yes', '')]))
        await asyncio.sleep(0)
        request_id = next(iter(transport.requests))
        transport.respond(request_id, 'yes')
        assert await task == 'yes'
        assert transport.requests == {}
    asyncio.run(scenario())


def test_bridge_imports_without_telegram_credentials(tmp_path):
    import os, subprocess, sys
    environment = dict(os.environ, OVERLORD_TELEGRAM_ENABLED="0", TELEGRAM_BOT_TOKEN="", OWNER_CHAT_ID="")
    result = subprocess.run([sys.executable, "-c", "import bridge; assert not bridge.TELEGRAM_ENABLED; assert bridge.OWNER == 0"],
                            env=environment, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("decision, expected", [("deny", False), ("allow", True), ("session", True)])
def test_real_permission_gate_accepts_local_decisions_and_cleans_request(tmp_path, decision, expected):
    async def scenario():
        gate = PermissionGate(telegram=None, owner=0, timeout=1, permission_level="ask")
        transport = ConsoleTransport(tmp_path / 'prompts.json', Queue(), 0, lambda *a: None,
                                     gate.on_permission_response, gate.on_choice_response)
        gate.telegram = transport
        task = asyncio.create_task(gate.request('Run command', 'a project command', []))
        await asyncio.sleep(0)
        request_id = next(iter(transport.requests))
        assert transport.respond(request_id, decision)
        assert await task is expected
        assert transport.requests == {}
    asyncio.run(scenario())


def test_telegram_can_fail_without_losing_local_conversation(tmp_path):
    from types import SimpleNamespace
    transport, messages, *_ = make(tmp_path)
    stopped=[]
    transport.backend=SimpleNamespace(stop=lambda:stopped.append(True))
    transport.disable_backend()
    transport.send(0,'local answer')
    assert stopped == [True] and messages == [(0,'local answer')]
    assert json.loads(transport.path.read_text())['telegram_enabled'] is False
