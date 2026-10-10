import asyncio

from modules.brain import PermissionGate
from modules.codex_brain import CodexBrain, R_EXEC_APPROVAL, R_TOOL_USER_INPUT
from test_scoped_permissions import Telegram


def make_brain(tmp_path):
    gate = PermissionGate(Telegram(), 42, 30)
    brain = CodexBrain(gate=gate, cwd=str(tmp_path), model="test", session_file=tmp_path / "session")
    brain._thread_id = "thread"
    brain._active_turn_id = "turn"
    return brain, gate


def test_owner_wait_does_not_block_rpc_replies_and_turn_cancellation(tmp_path, monkeypatch):
    async def scenario():
        brain, gate = make_brain(tmp_path)
        replies = []
        async def respond(request_id, result):
            replies.append((request_id, result))
        monkeypatch.setattr(brain, "_respond", respond)
        await brain._dispatch({"id": 10, "method": R_EXEC_APPROVAL,
            "params": {"threadId": "thread", "turnId": "turn", "command": "inspect"}})
        await asyncio.sleep(0)
        assert gate.pending
        rpc = asyncio.get_running_loop().create_future()
        brain._pending[20] = rpc
        await brain._dispatch({"id": 20, "result": {"interrupted": True}})
        assert rpc.result() == {"interrupted": True}
        await brain._dispatch({"method": "turn/completed", "params": {
            "threadId": "thread", "turn": {"id": "turn", "status": "interrupted"}}})
        await asyncio.gather(*list(brain._server_requests), return_exceptions=True)
        assert gate.pending == {}
        assert replies == [(10, {"decision": "cancel"})]
    asyncio.run(scenario())


def test_interactive_requests_are_ordered_and_foreign_threads_are_denied(tmp_path, monkeypatch):
    async def scenario():
        brain, gate = make_brain(tmp_path)
        replies = []
        async def respond(request_id, result):
            replies.append((request_id, result))
        monkeypatch.setattr(brain, "_respond", respond)
        for request_id in (1, 2):
            await brain._dispatch({"id": request_id, "method": R_EXEC_APPROVAL,
                "params": {"threadId": "thread", "turnId": "turn", "command": f"inspect {request_id}"}})
        await asyncio.sleep(0)
        assert len(gate.telegram.prompts) == 1
        gate.on_permission_response(gate.telegram.prompts[0], "deny")
        for _ in range(10):
            await asyncio.sleep(0)
            if len(gate.telegram.prompts) == 2:
                break
        assert len(gate.telegram.prompts) == 2
        gate.on_permission_response(gate.telegram.prompts[1], "deny")
        await asyncio.gather(*list(brain._server_requests))
        assert [request_id for request_id, result in replies] == [1, 2]
        await brain._handle_server_request({"id": 3, "method": R_TOOL_USER_INPUT,
            "params": {"threadId": "foreign", "questions": []}})
        assert replies[-1] == (3, {"answers": {}})
        assert len(gate.telegram.prompts) == 2
    asyncio.run(scenario())
