import asyncio

import pytest
from claude_agent_sdk import ResultMessage

from modules.claude_brain import ClaudeBrain


@pytest.fixture(autouse=True)
def opt_in(monkeypatch):
    monkeypatch.setenv("OVERLORD_CLAUDE_CONTEXT_SNAPSHOTS", "1")


def test_default_does_not_call_potentially_billable_control(tmp_path, monkeypatch):
    monkeypatch.delenv("OVERLORD_CLAUDE_CONTEXT_SNAPSHOTS", raising=False)
    brain = ClaudeBrain(gate=object(), cwd=str(tmp_path), model="test",
                        session_file=tmp_path / "session")
    calls = []
    class Client:
        async def get_context_usage(self):
            calls.append(True)
            return {"totalTokens": 1, "maxTokens": 10}
    asyncio.run(brain._capture_context(Client()))
    assert calls == []
    assert brain.context_snapshot is None


@pytest.mark.parametrize("used,maximum", [(False, 100), ("80", 100), (-1, 100),
    (80, 0), (float("inf"), 100), (80, None)])
def test_invalid_context_control_data_is_unknown(tmp_path, used, maximum):
    brain = ClaudeBrain(gate=object(), cwd=str(tmp_path), model="test",
                        session_file=tmp_path / "session")
    class Client:
        async def get_context_usage(self):
            return {"totalTokens": used, "maxTokens": maximum}
    asyncio.run(brain._capture_context(Client()))
    assert brain.context_snapshot is None


def test_claude_reads_context_after_success_without_an_extra_model_turn(tmp_path, monkeypatch):
    brain = ClaudeBrain(gate=object(), cwd=str(tmp_path), model="test",
                        session_file=tmp_path / "session")
    monkeypatch.setattr("modules.shared_job.live_job", lambda pin: None)
    class Client:
        def __init__(self):
            self.queries = []
            self.disconnected = False
        async def query(self, text):
            self.queries.append(text)
        async def receive_response(self):
            yield ResultMessage(subtype="success", duration_ms=1, duration_api_ms=1,
                is_error=False, num_turns=1, session_id="original",
                usage={"input_tokens": 12}, result="Answer")
        async def get_context_usage(self):
            return {"totalTokens": 800, "maxTokens": 1000, "percentage": 80}
        async def disconnect(self):
            self.disconnected = True
    client = Client()
    async def open_client(resume):
        return client
    monkeypatch.setattr(brain, "_open", open_client)
    async def scenario():
        assert [chunk async for chunk in brain.query("Task")] == ["Answer"]
        assert client.queries == ["Task"]
        assert client.disconnected
        assert brain.context_snapshot["percentage"] == 80
        assert brain.context_snapshot["session_id"] == "original"
        await brain.set_model("different")
        assert brain.context_snapshot is None
    asyncio.run(scenario())


def test_older_sdk_context_control_is_optional(tmp_path):
    brain = ClaudeBrain(gate=object(), cwd=str(tmp_path), model="test",
                        session_file=tmp_path / "session")
    asyncio.run(brain._capture_context(object()))
    assert brain.context_snapshot is None
