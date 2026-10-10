"""Native compaction must confirm completion and retain session identity."""

import asyncio
from types import SimpleNamespace

import pytest
from claude_agent_sdk import ResultMessage, SystemMessage

from modules.claude_brain import ClaudeBrain
from modules.codex_brain import CodexBrain, CodexError
from modules import codex_brain


def codex(tmp_path, monkeypatch):
    brain = CodexBrain(
        gate=object(), cwd=str(tmp_path), model="test",
        session_file=tmp_path / "session",
    )
    brain._thread_id = "thread-1"
    monkeypatch.setattr(brain, "_record_mtime", lambda: None)
    return brain


def completed(brain, thread="thread-1"):
    brain._handle_notification("item/completed", {
        "threadId": thread, "item": {"type": "contextCompaction", "id": "c1"},
    })
    brain._handle_notification("turn/completed", {
        "threadId": thread, "turn": {"id": "t1", "status": "completed"},
    })


def test_codex_acknowledgement_is_not_completion(tmp_path, monkeypatch):
    async def scenario():
        brain = codex(tmp_path, monkeypatch)
        calls = []

        async def request(method, params):
            calls.append((method, params))
            return {}

        monkeypatch.setattr(brain, "_request", request)
        task = asyncio.create_task(brain.compact(timeout=1))
        await asyncio.sleep(0)
        assert not task.done()
        completed(brain, "other-thread")
        assert not task.done()
        brain._handle_notification("item/completed", {
            "threadId": "thread-1", "item": {"type": "contextCompaction"},
        })
        assert not task.done()
        completed(brain)
        assert await task is None
        assert brain.session_id == "thread-1"
        assert not brain._compaction_active
        assert calls == [("thread/compact/start", {"threadId": "thread-1"})]
    asyncio.run(scenario())


def test_codex_timeout_blocks_new_work_until_completion(tmp_path, monkeypatch):
    async def scenario():
        brain = codex(tmp_path, monkeypatch)

        async def request(method, params):
            return {}

        monkeypatch.setattr(brain, "_request", request)
        error = await brain.compact(timeout=0.001)
        assert "unknown" in error
        assert brain.compaction_status == "uncertain"
        with pytest.raises(RuntimeError, match="not settled"):
            await anext(brain.query("next"))
        completed(brain)
        assert brain.compaction_status == "completed"
        assert not brain._compaction_active
    asyncio.run(scenario())


def test_compaction_stream_close_wakes_waiter_without_claiming_completion(tmp_path, monkeypatch):
    async def scenario():
        brain = codex(tmp_path, monkeypatch)
        async def request(*args):
            return {}
        class Output:
            async def readline(self):
                return b""
        monkeypatch.setattr(brain, "_request", request)
        brain._proc = SimpleNamespace(stdout=Output())
        task = asyncio.create_task(brain.compact(timeout=30))
        await asyncio.sleep(0)
        await brain._read_loop()
        assert "unknown" in await asyncio.wait_for(task, timeout=0.1)
        assert brain.compaction_status == "uncertain"
        assert brain._compaction_active
        assert brain.session_id == "thread-1"
    asyncio.run(scenario())


def test_compaction_cancellation_cannot_hang_on_interrupt(tmp_path, monkeypatch):
    monkeypatch.setattr(codex_brain, "CONTROL_REQUEST_TIMEOUT", 0.01)
    async def scenario():
        brain = codex(tmp_path, monkeypatch)
        async def request(method, params):
            if method == "turn/interrupt":
                await asyncio.Event().wait()
            brain._active_turn_id = "compact-turn"
            return {}
        monkeypatch.setattr(brain, "_request", request)
        task = asyncio.create_task(brain.compact())
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, timeout=0.1)
        assert brain.compaction_status == "uncertain"
        assert brain._compaction_active
        assert brain._active_turn_id == "compact-turn"
    asyncio.run(scenario())


def test_codex_unsupported_method_keeps_existing_thread(tmp_path, monkeypatch):
    async def scenario():
        brain = codex(tmp_path, monkeypatch)

        async def unsupported(method, params):
            raise CodexError("method not found", code=-32601)

        monkeypatch.setattr(brain, "_request", unsupported)
        assert "method not found" in await brain.compact()
        assert brain.session_id == "thread-1"
        assert not brain._compaction_active
    asyncio.run(scenario())


def test_codex_failed_turn_does_not_report_success(tmp_path, monkeypatch):
    async def scenario():
        brain = codex(tmp_path, monkeypatch)

        async def request(method, params):
            brain._handle_notification("turn/completed", {
                "threadId": "thread-1", "turn": {
                    "id": "t1", "status": "failed",
                    "error": {"message": "quota exhausted"},
                },
            })
            return {}

        monkeypatch.setattr(brain, "_request", request)
        assert await brain.compact() == "quota exhausted"
        assert brain.compaction_status == "failed"
    asyncio.run(scenario())


@pytest.mark.parametrize("boundary,advertised", [
    (False, True), (True, True), (False, False),
])
def test_claude_requires_boundary_and_discovers_command(
    tmp_path, monkeypatch, boundary, advertised
):
    brain = ClaudeBrain(
        gate=object(), cwd=str(tmp_path), model="test",
        session_file=tmp_path / "session",
    )
    brain._session_id = "session-1"
    monkeypatch.setattr("modules.shared_job.live_job", lambda pin: None)

    class Client:
        def __init__(self):
            self.queries = []
            self.disconnected = False

        async def get_server_info(self):
            return {"commands": [{"name": "compact"}] if advertised else []}

        async def query(self, text):
            self.queries.append(text)

        async def receive_response(self):
            if boundary:
                yield SystemMessage(subtype="compact_boundary", data={})
            yield ResultMessage(
                subtype="success", duration_ms=1, duration_api_ms=1,
                is_error=False, num_turns=1, session_id="session-1",
                usage={"input_tokens": 25, "output_tokens": 10},
            )

        async def disconnect(self):
            self.disconnected = True

    client = Client()

    async def open_client(resume):
        assert resume == "session-1"
        return client

    monkeypatch.setattr(brain, "_open", open_client)
    result = asyncio.run(brain.compact())
    assert (result is None) == boundary
    assert brain.session_id == "session-1"
    if advertised:
        assert brain.last_turn_usage["input_tokens"] == 25
        assert client.queries == ["/compact"]
    else:
        assert brain.last_turn_usage is None
        assert not client.queries
    assert client.disconnected
