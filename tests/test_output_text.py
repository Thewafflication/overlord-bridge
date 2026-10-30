import asyncio
from types import SimpleNamespace

from modules.output_text import activity_summary, telegram_blocks, expandable_html
from modules.telegram_handler import TelegramHandler
from modules.telegram_handler import _chunks, MAX_MESSAGE_LEN


def test_only_explicit_log_blocks_collapse_and_findings_remain_visible():
    text = "Build failed. Fix the missing header.\n\n```log\nerror <header> & details\n```\nNext step: rebuild."
    blocks = list(telegram_blocks(text))
    assert [collapsed for _, collapsed in blocks] == [False, True, False]
    assert "Fix the missing header" in blocks[0][0]
    assert "Next step" in blocks[-1][0]
    assert "&lt;header&gt; &amp;" in expandable_html(blocks[1][0])
    assert list(telegram_blocks("```python\nprint(1)\n```")) == [("```python\nprint(1)\n```", False)]


def test_telegram_sends_logs_with_native_expandable_format():
    messages = []
    handler = TelegramHandler.__new__(TelegramHandler)
    async def send_message(**kwargs):
        messages.append(kwargs)
    async def call(label, operation):
        await operation()
    handler.bot = SimpleNamespace(send_message=send_message)
    handler._telegram_call = call
    asyncio.run(handler._send(42, "Checks passed.\n```log\nline 1\nline 2\nline 3\nline 4\n```"))
    assert messages[0]["text"].startswith("Checks passed")
    assert messages[1]["parse_mode"] == "HTML"
    assert messages[1]["text"].startswith("<blockquote expandable>")


def test_telegram_code_is_escaped_highlighted_and_independently_balanced():
    import html
    import re
    messages = []
    handler = TelegramHandler.__new__(TelegramHandler)
    async def send_message(**kwargs):
        messages.append(kwargs)
    async def call(label, operation):
        await operation()
    handler.bot = SimpleNamespace(send_message=send_message)
    handler._telegram_call = call
    source = 'print("<tag> & value")\n' * 300
    asyncio.run(handler._send(42, 'Code:\n```python\n' + source + '```\nDone'))
    code_messages = [m for m in messages if m['text'].startswith('<pre>')]
    assert code_messages
    assert all(m['parse_mode'] == 'HTML' and m['text'].endswith('</code></pre>') for m in code_messages)
    assert all(len(m['text'].encode('utf-16-le')) // 2 < 4096 for m in code_messages)
    assert ''.join(html.unescape(re.sub('<[^>]+>', '', m['text'])) for m in code_messages) == source
    assert messages[-1]['text'] == 'Done'


def test_activity_summary_preserves_command_and_failure():
    assert activity_summary("2026 INFO COMMAND worker completed | cwd=C:/repo | make test | exit=0") == "Finished: make test · worker"
    assert "Failed (exit 2): make" in activity_summary("INFO COMMAND worker completed | cwd=C:/repo | make | exit=2")
    assert activity_summary("2026 overlord INFO Connected to Telegram") == "Connected to Telegram"


def test_emoji_chunks_preserve_text_and_fit_telegram_limits():
    text = "😀" * MAX_MESSAGE_LEN
    chunks = list(_chunks(text))
    assert "".join(chunks) == text
    assert all(len(chunk.encode("utf-16-le")) // 2 <= MAX_MESSAGE_LEN for chunk in chunks)


def test_worker_tool_name_normalization_is_limited_to_known_protocol_wrappers():
    from modules.output_text import worker_tool_name
    assert worker_tool_name('functions.edit_file<|channel|>commentary') == 'edit_file'
    assert worker_tool_name('shell<|channel|>analysis') == 'run_command'
    assert worker_tool_name('run_python<|channel|>json') == 'run_python'
    assert worker_tool_name('functions.run_python<|channel|>json') == 'run_python'
    assert worker_tool_name('edit_file<|channel|>unexpected') == 'edit_file<|channel|>unexpected'
    assert worker_tool_name('please edit_file') == 'please edit_file'
    assert worker_tool_name('unknown<|channel|>commentary') == 'unknown'
