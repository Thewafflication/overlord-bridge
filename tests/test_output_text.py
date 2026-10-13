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


def test_activity_summary_preserves_command_and_failure():
    assert activity_summary("2026 INFO COMMAND worker completed | cwd=C:/repo | make test | exit=0") == "Finished: make test · worker"
    assert "Failed (exit 2): make" in activity_summary("INFO COMMAND worker completed | cwd=C:/repo | make | exit=2")
    assert activity_summary("2026 overlord INFO Connected to Telegram") == "Connected to Telegram"


def test_emoji_chunks_preserve_text_and_fit_telegram_limits():
    text = "😀" * MAX_MESSAGE_LEN
    chunks = list(_chunks(text))
    assert "".join(chunks) == text
    assert all(len(chunk.encode("utf-16-le")) // 2 <= MAX_MESSAGE_LEN for chunk in chunks)
