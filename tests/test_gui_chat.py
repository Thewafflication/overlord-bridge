import asyncio
import json
import os
from pathlib import Path

import pytest

import bridge
from modules.chat_requests import append_request, read_requests, RequestReader
from modules.chat_mirror import ChatMirror, ROLE_OWNER, ROLE_OVERLORD, SOURCE_GUI, SOURCE_TELEGRAM
from modules.telegram_handler import TelegramHandler
from tests.test_bridge_support import make_bridge
from tools import overlord_console as console_module


def test_queue_receipts_survive_restart_and_detect_replacement_or_regrowth(tmp_path):
    path = tmp_path / 'requests.jsonl'
    append_request(path, 'first')
    append_request(path, 'second')
    reader = RequestReader(path)
    records, _ = reader.read()
    reader.acknowledge(records[0][1])
    restarted = RequestReader(path)
    records, end = restarted.read()
    assert [text for text, _ in records] == ['second']
    restarted.acknowledge(end)
    assert RequestReader(path).read()[0] == []
    replacement = tmp_path / 'replacement'
    append_request(replacement, 'replacement message longer than the previous queue contents ' * 3)
    replacement.replace(path)
    assert RequestReader(path).read()[0][0][0].startswith('replacement message')
    reader = RequestReader(path)
    records, end = reader.read()
    reader.acknowledge(end)
    path.write_text(json.dumps({'text': 'regrown different content ' * 20}) + '\n')
    assert reader.read()[0][0][0].startswith('regrown different')


def test_gui_queue_and_telegram_messages_mirror_once(tmp_path):
    async def scenario():
        instance = make_bridge(tmp_path)
        instance._chat_request_path = tmp_path / 'requests.jsonl'
        instance.chat_mirror = ChatMirror(tmp_path / 'mirror.jsonl')
        sent = []
        telegram = TelegramHandler.__new__(TelegramHandler)
        telegram.loop = None
        telegram.on_send = instance._mirror_outbound
        def send(owner, text, *, mirror=True):
            sent.append((text, mirror))
            telegram.send(owner, text, mirror=mirror)
        instance.telegram.send = send
        def start(owner, text):
            send(owner, 'reply:' + text)
            return True
        instance._start_turn = start
        append_request(instance._chat_request_path, 'hello from GUI')
        append_request(instance._chat_request_path, '/help')
        task = asyncio.create_task(instance._chat_request_loop())
        try:
            for _ in range(150):
                if len(list(instance.chat_mirror.iter_all())) >= 4:
                    break
                await asyncio.sleep(0.01)
            await instance._dispatch_inbound(bridge.OWNER, 'hello from Telegram')
        finally:
            instance._shutdown_event.set()
            await task
        records = list(instance.chat_mirror.iter_all())
        assert [(r['text'], r['source']) for r in records if r['role'] == ROLE_OWNER] == [
            ('hello from GUI', SOURCE_GUI), ('/help', SOURCE_GUI), ('hello from Telegram', SOURCE_TELEGRAM)]
        assert len([r for r in records if r['role'] == ROLE_OVERLORD]) == 3
        assert len([text for text, mirror in sent if not mirror]) == 2
        assert len([text for text, _ in sent if text == 'reply:hello from GUI']) == 1
        # Receipt state prevents replay on a new bridge consumer.
        assert RequestReader(instance._chat_request_path).read()[0] == []
    asyncio.run(scenario())


def test_queue_failure_retries_without_skipping_later_messages(tmp_path):
    async def scenario():
        instance = make_bridge(tmp_path)
        instance._chat_request_path = tmp_path / 'requests.jsonl'
        for text in ['one', 'two', 'three']:
            append_request(instance._chat_request_path, text)
        delivered, attempts = [], []
        async def handle(payload):
            text = payload['text']
            attempts.append(text)
            if text == 'two' and attempts.count('two') == 1:
                raise OSError('temporary failure before delivery')
            delivered.append(text)
        instance._handle_gui_chat = handle
        task = asyncio.create_task(instance._chat_request_loop())
        try:
            for _ in range(200):
                if delivered == ['one', 'two', 'three']:
                    break
                await asyncio.sleep(0.01)
        finally:
            instance._shutdown_event.set()
            await task
        assert delivered == ['one', 'two', 'three']
        assert attempts == ['one', 'two', 'two', 'three']
        assert RequestReader(instance._chat_request_path).read()[0] == []
    asyncio.run(scenario())


def test_internal_typeerror_does_not_execute_console_action_twice(tmp_path):
    async def scenario():
        instance = make_bridge(tmp_path)
        calls = []
        async def action(name, payload=None):
            calls.append(name)
            raise TypeError('inside handler after side effect')
        instance._run_console_action = action
        instance._console_command_file.parent.mkdir(parents=True)
        task = asyncio.create_task(instance._console_command_loop())
        await asyncio.sleep(0.05)
        instance._console_command_file.write_text('{"action":"test"}')
        await asyncio.sleep(0.5)
        instance._shutdown_event.set()
        await task
        assert calls == ['test']
    asyncio.run(scenario())


def test_mirror_byte_offsets_partial_records_and_bounded_rotation(tmp_path):
    path = tmp_path / 'mirror.jsonl'
    first = b'{"text":"caf\xc3\xa9"}\r\n'
    second = b'{"text":"next"}\r\n'
    path.write_bytes(first + second[:-1])
    mirror = ChatMirror(path)
    records, offset = mirror.read_since()
    assert records[0]['text'] == 'café' and offset == len(first)
    with path.open('ab') as stream:
        stream.write(second[-1:])
    assert mirror.read_since(offset)[0] == [{'text': 'next'}]
    bounded = ChatMirror(path, max_bytes=1024)
    for i in range(40):
        bounded.append(ROLE_OWNER, f'message {i} ' + 'x' * 50)
    assert path.stat().st_size <= 1024
    assert list(bounded.iter_all())[-1]['text'].startswith('message 39')


def make_console(tmp_path):
    from unittest.mock import patch
    try:
        root = console_module.tk.Tk()
    except console_module.tk.TclError as exc:
        pytest.skip(f'No graphical display: {exc}')
    try:
        with patch.object(console_module.tk, 'Tk', return_value=root):
            value = console_module.OverlordConsole(tmp_path / 'run' / 'output.txt', tmp_path / 'signal', tmp_path / 'state',
                command_path=tmp_path / 'run' / 'commands.json')
    except Exception:
        root.destroy()
        raise
    value.root.withdraw()
    return value


def test_real_tk_send_retains_failed_input_and_reads_shared_transcript(tmp_path, monkeypatch):
    console = make_console(tmp_path)
    try:
        console.chat_entry.insert(0, 'typed GUI message')
        original = console_module.append_request
        monkeypatch.setattr(console_module, 'append_request', lambda *args: False)
        console.chat_send_button.invoke()
        assert console.chat_entry.get() == 'typed GUI message'
        monkeypatch.setattr(console_module, 'append_request', original)
        console.chat_send_button.invoke()
        assert console.chat_entry.get() == ''
        assert read_requests(console.chat_request_path)[0] == ['typed GUI message']
        mirror = ChatMirror(console.chat_mirror_path)
        mirror.append(ROLE_OWNER, 'typed GUI message', SOURCE_GUI)
        mirror.append(ROLE_OVERLORD, 'assistant reply', SOURCE_TELEGRAM)
        console._read_new_chat()
        text = console.chat_text.get('1.0', 'end')
        assert text.count('typed GUI message') == 1 and '[GUI] You:' in text
        assert '[Telegram] Overlord: assistant reply' in text
        # Replacement/rotation clears obsolete display rather than duplicating history.
        replacement = tmp_path / 'replacement'
        ChatMirror(replacement).append(ROLE_OVERLORD, 'rotated reply')
        replacement.replace(console.chat_mirror_path)
        console._read_new_chat()
        assert 'rotated reply' in console.chat_text.get('1.0', 'end')
        assert 'typed GUI message' not in console.chat_text.get('1.0', 'end')
        monkeypatch.setattr(console_module, 'MAX_WIDGET_LINES', 3)
        for i in range(20):
            mirror.append(ROLE_OVERLORD, f'reply number {i}')
        console._read_new_chat()
        assert len(console.chat_messages) == 3
        text = console.chat_text.get('1.0', 'end')
        assert 'reply number 19' in text and len(text.strip().splitlines()) <= 3
        assert console.chat_request_path.parent == console.chat_mirror_path.parent == console.log_path.parent
    finally:
        console.root.destroy()


def test_failed_receipt_write_pauses_without_redelivering_in_same_process(tmp_path, monkeypatch):
    path = tmp_path / 'queue.jsonl'
    append_request(path, 'first')
    reader = RequestReader(path)
    records, end = reader.read()
    original = Path.replace
    blocked = True
    def replace(source, target):
        if Path(target) == reader.cursor and blocked:
            raise OSError('cursor temporarily unavailable')
        return original(source, target)
    monkeypatch.setattr(Path, 'replace', replace)
    with pytest.raises(OSError):
        reader.acknowledge(end)
    append_request(path, 'second')
    with pytest.raises(OSError):
        reader.read()
    blocked = False
    records, _ = reader.read()
    assert [text for text, _ in records] == ['second']
