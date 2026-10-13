import asyncio

from modules import host_context
from modules.host_context import host_instructions
from tests.test_free_brain import make, reply, ask


def test_windows_instructions_distinguish_owner_and_worker_shell(monkeypatch):
    monkeypatch.setattr(host_context.sys, "platform", "win32")
    text = host_instructions()
    assert "Windows" in text and "PowerShell" in text
    assert ".sh" in text and "Do not assume WSL" in text
    assert "cmd.exe" not in text
    assert "cmd.exe" in host_instructions(worker_shell=True)


def test_non_windows_host_is_reported_without_windows_assumptions(monkeypatch):
    monkeypatch.setattr(host_context.sys, "platform", "linux")
    assert "linux" in host_instructions()
    assert "PowerShell" not in host_instructions()


def test_free_chat_receives_current_host_even_with_stale_linux_history(tmp_path, monkeypatch):
    monkeypatch.setattr(host_context.sys, "platform", "win32")
    brain = make(tmp_path, monkeypatch, [reply("Use the PowerShell launcher")])
    brain._history = [{"role": "user", "content": "How do I launch?"},
                      {"role": "assistant", "content": "Run ./launch.sh"}]
    asyncio.run(ask(brain, "What should I run?"))
    prompt = brain.calls[0][1]["messages"][0]["content"]
    assert "Host environment: Windows" in prompt
    assert "earlier conversation" in prompt
