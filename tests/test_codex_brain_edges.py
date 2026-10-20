"""Codex turn streaming, runtime knobs, instruction loading, and WebSocket framing."""

import asyncio
import os

import pytest

from modules import codex_brain
from modules.brain import PermissionGate
from modules.codex_brain import (
    CodexBrain,
    CodexError,
    UnixWebSocketTransport,
    _codex_usage_from_rate_limits,
    _find_rate_limits,
    _safe_worker_report_event_id,
)


class Gate(PermissionGate):
    def __init__(self):
        super().__init__(telegram=None, owner=42, timeout=5)


def make_brain(tmp_path, **kwargs):
    brain = CodexBrain(
        gate=Gate(), cwd=str(tmp_path), model=kwargs.pop("model", "gpt-x"),
        session_file=tmp_path / "session", developer_instructions="", **kwargs,
    )
    brain._thread_id = "thread"
    return brain


async def drain(generator):
    return [chunk async for chunk in generator]


# ----------------------------------------------------------------- turn streaming
def test_turn_streams_final_text_and_books_the_last_block(tmp_path, monkeypatch):
    async def scenario():
        brain = make_brain(tmp_path)

        async def request(method, params):
            if method == "turn/start":
                assert params["model"] == "gpt-x"  # override stale resumed-session defaults
                for note in (
                    ("item/agentMessage/delta", {"itemId": "a", "delta": "Hel"}),
                    ("item/agentMessage/delta", {"itemId": "a", "delta": "lo"}),
                    ("item/completed", {"item": {"type": "agentMessage", "id": "a"}}),
                    ("item/completed", {"item": {"type": "agentMessage", "id": "b",
                                                 "text": "authoritative"}}),
                    ("thread/tokenUsage/updated", {"tokenUsage": {
                        "total": {"totalTokens": 30, "inputTokens": 20},
                        "last": {"totalTokens": 12, "inputTokens": 8, "outputTokens": 4}}}),
                    ("turn/completed", {"turn": {"id": "t1", "status": "completed"}}),
                ):
                    brain._handle_notification(*note)
                return {"turn": {"id": "t1"}}
            return {}

        monkeypatch.setattr(brain, "_request", request)
        monkeypatch.setattr(brain, "_maybe_refresh", lambda: asyncio.sleep(0))
        chunks = await drain(brain.query("hi"))
        assert chunks == ["Hello", "authoritative"]
        assert brain.last_turn_usage == {"totalTokens": 12, "inputTokens": 8, "outputTokens": 4}
        assert brain.last_turn_outcome == "ok"
        assert brain._turn_queue is None

    asyncio.run(scenario())


def test_failed_turn_surfaces_the_server_message_and_marks_the_outcome(tmp_path, monkeypatch):
    async def scenario():
        brain = make_brain(tmp_path)

        async def request(method, params):
            brain._handle_notification("error", {"error": {"message": "rate limited"}})
            brain._handle_notification(
                "turn/completed", {"turn": {"id": "t", "status": {"type": "failed"}}}
            )
            return {"turn": {"id": "t"}}

        monkeypatch.setattr(brain, "_request", request)
        monkeypatch.setattr(brain, "_maybe_refresh", lambda: asyncio.sleep(0))
        chunks = await drain(brain.query("hi"))
        assert chunks == ["⚠️ rate limited"]
        assert brain.last_turn_outcome == "error"

    asyncio.run(scenario())


def test_cumulative_totals_are_differenced_when_no_last_block_arrives(tmp_path, monkeypatch):
    async def scenario():
        brain = make_brain(tmp_path)
        brain._token_usage_total = {"totalTokens": 100, "inputTokens": 60, "outputTokens": 40}

        async def request(method, params):
            brain._handle_notification("thread/tokenUsage/updated", {"tokenUsage": {
                "total": {"totalTokens": 150, "inputTokens": 90, "outputTokens": 60}}})
            brain._handle_notification("turn/completed", {"turn": {"id": "t", "status": "completed"}})
            return {"turn": {"id": "t"}}

        monkeypatch.setattr(brain, "_request", request)
        monkeypatch.setattr(brain, "_maybe_refresh", lambda: asyncio.sleep(0))
        await drain(brain.query("hi"))
        assert brain.last_turn_usage["total_tokens"] == 50
        assert brain.last_turn_usage["input_tokens"] == 30

    asyncio.run(scenario())


def test_rejected_turn_start_does_not_leave_a_phantom_turn_behind(tmp_path, monkeypatch):
    async def scenario():
        brain = make_brain(tmp_path)

        async def request(method, params):
            if method == "turn/start":
                raise CodexError("usage limit reached", code=429)
            return {}

        monkeypatch.setattr(brain, "_request", request)
        monkeypatch.setattr(brain, "_maybe_refresh", lambda: asyncio.sleep(0))
        with pytest.raises(CodexError):
            await drain(brain.query("hi"))
        # A stale queue here would make compaction refuse with "active operation".
        assert brain._turn_queue is None

    asyncio.run(scenario())


def test_query_requires_a_connected_thread(tmp_path):
    async def scenario():
        brain = make_brain(tmp_path)
        brain._thread_id = None
        with pytest.raises(RuntimeError, match="before connect"):
            await drain(brain.query("hi"))

    asyncio.run(scenario())


# ---------------------------------------------------------------- runtime knobs
def test_effort_the_server_ignores_is_not_kept_on_the_brain(tmp_path, monkeypatch):
    async def scenario():
        brain = make_brain(tmp_path, effort="low")

        async def restart(what):
            brain._effort_unsupported = True  # what _start_thread does on a rejection
            return None

        monkeypatch.setattr(brain, "_restart_thread_in_place", restart)
        message = await brain.set_effort("high")
        assert "nothing was changed" in message
        assert brain.effort == "low"

    asyncio.run(scenario())


def test_effort_levels_are_validated_and_can_be_cleared(tmp_path, monkeypatch):
    async def scenario():
        brain = make_brain(tmp_path)
        monkeypatch.setattr(brain, "_restart_thread_in_place", lambda what: asyncio.sleep(0))
        assert "Unknown effort" in await brain.set_effort("ludicrous")
        assert brain.effort is None
        assert await brain.set_effort("HIGH") is None
        assert brain.effort == "high"
        assert await brain.set_effort("default") is None
        assert brain.effort is None

    asyncio.run(scenario())


def test_model_and_effort_roll_back_when_codex_refuses_the_restart(tmp_path, monkeypatch):
    async def scenario():
        brain = make_brain(tmp_path, model="gpt-x", effort="low")

        async def restart(what):
            return f"Codex refused the new {what}"

        monkeypatch.setattr(brain, "_restart_thread_in_place", restart)
        assert "refused" in await brain.set_model("gpt-y")
        assert brain.model == "gpt-x"
        assert "refused" in await brain.set_effort("high")
        assert brain.effort == "low"
        assert "Give a model name" in await brain.set_model("   ")

    asyncio.run(scenario())


def test_restart_failure_is_reported_not_raised(tmp_path, monkeypatch):
    async def scenario():
        brain = make_brain(tmp_path)

        async def broken(resume, *, fallback_to_fresh=True):
            raise CodexError("boom")

        monkeypatch.setattr(brain, "_start_thread", broken)
        assert "boom" in await brain._restart_thread_in_place("model")
        brain._thread_id = None
        assert await brain._restart_thread_in_place("model") is None

    asyncio.run(scenario())


# ------------------------------------------------------------------ interruption
def test_interrupt_needs_a_known_turn_and_clears_it_on_success(tmp_path, monkeypatch):
    async def scenario():
        brain = make_brain(tmp_path)
        assert await brain.interrupt_active_turn() is False
        brain._active_turn_id = "turn-1"
        sent = []

        async def request(method, params):
            sent.append((method, params))
            return {}

        monkeypatch.setattr(brain, "_request", request)
        assert await brain.interrupt_active_turn() is True
        assert sent == [("turn/interrupt", {"threadId": "thread", "turnId": "turn-1"})]
        assert brain._active_turn_id is None

    asyncio.run(scenario())


def test_failed_interrupt_keeps_the_turn_id(tmp_path, monkeypatch):
    async def scenario():
        brain = make_brain(tmp_path)
        brain._active_turn_id = "turn-1"

        async def request(method, params):
            raise CodexError("gone")

        monkeypatch.setattr(brain, "_request", request)
        assert await brain.interrupt_active_turn() is False
        assert brain._active_turn_id == "turn-1"

    asyncio.run(scenario())


# ---------------------------------------------------------------------- requests
def test_response_for_an_unknown_or_finished_request_is_ignored(tmp_path):
    async def scenario():
        brain = make_brain(tmp_path)
        await brain._dispatch({"id": 99, "result": {}})
        fut = asyncio.get_running_loop().create_future()
        fut.set_result("already")
        brain._pending[5] = fut
        await brain._dispatch({"id": 5, "result": {"late": True}})
        assert fut.result() == "already"

    asyncio.run(scenario())


def test_error_responses_carry_the_rpc_code(tmp_path):
    async def scenario():
        brain = make_brain(tmp_path)
        fut = asyncio.get_running_loop().create_future()
        brain._pending[7] = fut
        await brain._dispatch({"id": 7, "error": {"code": -32601, "message": "no such method"}})
        with pytest.raises(CodexError) as info:
            fut.result()
        assert info.value.code == -32601

    asyncio.run(scenario())


def test_request_fails_fast_once_the_reader_has_stopped(tmp_path):
    async def scenario():
        brain = make_brain(tmp_path)
        done = asyncio.get_running_loop().create_future()
        done.set_result(None)
        brain._reader_task = done
        with pytest.raises(CodexError, match="stream closed"):
            await brain._request("turn/start", {})

    asyncio.run(scenario())


def test_notifications_for_another_thread_are_ignored(tmp_path):
    brain = make_brain(tmp_path)
    brain._turn_queue = asyncio.Queue()
    brain._handle_notification(
        "item/completed",
        {"threadId": "other", "item": {"type": "agentMessage", "id": "x", "text": "stray"}},
    )
    assert brain._turn_queue.empty()


# ---------------------------------------------------------------- misc helpers
def test_developer_instructions_are_read_as_utf8(tmp_path, monkeypatch):
    instructions = tmp_path / "AGENTS.md"
    instructions.write_bytes("Owner — “Ben”\n".encode("utf-8"))
    monkeypatch.setenv(codex_brain.ENV_INSTRUCTIONS_FILE, str(instructions))
    assert codex_brain._load_developer_instructions() == "Owner — “Ben”"


def test_ansi_saved_instructions_still_load_and_missing_ones_degrade_to_empty(tmp_path, monkeypatch):
    ansi = tmp_path / "ansi.md"
    ansi.write_bytes(b"Caf\xe9 rules")  # cp1252, not valid UTF-8
    monkeypatch.setenv(codex_brain.ENV_INSTRUCTIONS_FILE, str(ansi))
    assert codex_brain._load_developer_instructions() == "Café rules"
    monkeypatch.setenv(codex_brain.ENV_INSTRUCTIONS_FILE, str(tmp_path / "missing.md"))
    assert codex_brain._load_developer_instructions() == ""


def test_worker_report_event_ids_are_made_safe_and_bounded():
    assert _safe_worker_report_event_id({}) == "worker-report"
    assert _safe_worker_report_event_id({"event_id": "a b/c:d"}) == "a-b-c-d"
    assert len(_safe_worker_report_event_id({"event_id": "x" * 500})) == 80
    assert _safe_worker_report_event_id({"event_id": ""}) == "worker-report"


def test_rate_limits_are_found_in_nested_payloads():
    payload = {"result": [{"unrelated": 1}, {"deep": {"rateLimits": {"planType": "pro"}}}]}
    assert _find_rate_limits(payload) == {"planType": "pro"}
    assert _find_rate_limits({"rate_limits": "not a dict"}) is None
    assert _find_rate_limits([]) is None


def test_usage_windows_are_classified_by_length_and_expire_after_reset():
    now = 1_000_000.0
    usage = _codex_usage_from_rate_limits(
        {
            "planType": "plus",
            "primary": {"usedPercent": 40, "windowDurationMins": 300, "resetsAt": now + 60},
            "secondary": {"used_percent": 90, "window_minutes": 10080, "resets_at": now - 1},
        },
        now=now,
    )
    assert usage["session"]["used"] == 40.0 and usage["session"]["gas"] == 60
    assert usage["weekly"]["used"] == 0.0 and usage["weekly"]["reset_passed"] is True
    assert usage["plan_type"] == "plus"
    assert _codex_usage_from_rate_limits({"primary": {"windowDurationMins": 7}}, now=now) is None
    assert _codex_usage_from_rate_limits({"primary": "bad"}, now=now) is None


# ---------------------------------------------------------- WebSocket framing
class RecordingWriter:
    def __init__(self):
        self.data = bytearray()
        self.closed = False

    def write(self, data):
        self.data.extend(data)

    async def drain(self):
        pass

    def close(self):
        self.closed = True

    async def wait_closed(self):
        pass


def unmask(frame: bytes):
    """Decode one client frame -> (opcode, payload); clients must always mask."""
    assert frame[0] & 0x80, "FIN must be set"
    assert frame[1] & 0x80, "client frames must be masked"
    length, offset = frame[1] & 0x7F, 2
    if length == 126:
        length, offset = int.from_bytes(frame[2:4], "big"), 4
    elif length == 127:
        length, offset = int.from_bytes(frame[2:10], "big"), 10
    mask = frame[offset:offset + 4]
    body = frame[offset + 4:offset + 4 + length]
    return frame[0] & 0x0F, bytes(b ^ mask[i % 4] for i, b in enumerate(body))


@pytest.mark.parametrize("size", [0, 125, 126, 65535, 65536])
def test_text_frames_use_the_right_length_encoding(size):
    async def scenario():
        writer = RecordingWriter()
        transport = UnixWebSocketTransport(asyncio.StreamReader(), writer)
        await transport.send_text("x" * size)
        opcode, payload = unmask(bytes(writer.data))
        assert opcode == 1 and payload == b"x" * size

    asyncio.run(scenario())


def server_frame(opcode, payload=b"", *, fin=True):
    head = bytes([(0x80 if fin else 0) | opcode])
    if len(payload) <= 125:
        return head + bytes([len(payload)]) + payload
    if len(payload) <= 0xFFFF:
        return head + bytes([126]) + len(payload).to_bytes(2, "big") + payload
    return head + bytes([127]) + len(payload).to_bytes(8, "big") + payload


def test_fragmented_messages_are_reassembled_and_pings_are_answered():
    async def scenario():
        reader, writer = asyncio.StreamReader(), RecordingWriter()
        transport = UnixWebSocketTransport(reader, writer)
        reader.feed_data(server_frame(0x1, b"hel", fin=False))
        reader.feed_data(server_frame(0x9, b"ping!"))
        reader.feed_data(server_frame(0xA, b"unsolicited pong"))
        reader.feed_data(server_frame(0x0, "lo ✓".encode("utf-8")))
        assert await transport.recv_text() == "hello ✓"
        opcode, payload = unmask(bytes(writer.data))
        assert opcode == 0xA and payload == b"ping!"

    asyncio.run(scenario())


def test_large_server_frames_and_close_frames():
    async def scenario():
        reader = asyncio.StreamReader()
        transport = UnixWebSocketTransport(reader, RecordingWriter())
        big = "é" * 40000
        reader.feed_data(server_frame(0x1, big.encode("utf-8")))
        reader.feed_data(server_frame(0x8))
        assert await transport.recv_text() == big
        assert await transport.recv_text() is None

    asyncio.run(scenario())


def test_close_sends_a_close_frame_then_closes_the_stream():
    async def scenario():
        writer = RecordingWriter()
        transport = UnixWebSocketTransport(asyncio.StreamReader(), writer)
        await transport.close()
        assert unmask(bytes(writer.data))[0] == 0x8
        assert writer.closed

    asyncio.run(scenario())


def test_control_frame_payloads_are_capped_at_125_bytes():
    async def scenario():
        writer = RecordingWriter()
        transport = UnixWebSocketTransport(asyncio.StreamReader(), writer)
        await transport._send_control(0xA, b"p" * 300)
        _, payload = unmask(bytes(writer.data))
        assert len(payload) == 125

    asyncio.run(scenario())


# ---------------------------------------------------------- thread resume
def test_dead_thread_is_replaced_and_repinned(tmp_path, monkeypatch):
    async def scenario():
        brain = make_brain(tmp_path)
        brain._thread_id = None
        brain.session_file.write_text("dead-thread", encoding="utf-8")
        calls = []

        async def request(method, params):
            calls.append(method)
            if method == "thread/resume":
                raise CodexError("no rollout found for thread")
            return {"thread": {"id": "fresh-thread"}, "model": "gpt-x"}

        monkeypatch.setattr(brain, "_request", request)
        await brain._start_thread("dead-thread")
        assert calls == ["thread/resume", "thread/start"]
        assert brain.session_id == "fresh-thread"
        assert brain.session_file.read_text(encoding="utf-8") == "fresh-thread"

    asyncio.run(scenario())


def test_app_server_outage_does_not_destroy_the_saved_thread_pin(tmp_path, monkeypatch):
    async def scenario():
        brain = make_brain(tmp_path)
        brain._thread_id = None
        brain.session_file.write_text("good-thread", encoding="utf-8")

        async def request(method, params):
            raise CodexError("Codex app-server stream closed.")

        monkeypatch.setattr(brain, "_request", request)
        with pytest.raises(CodexError):
            await brain._start_thread("good-thread")
        assert brain.session_file.read_text(encoding="utf-8") == "good-thread"

    asyncio.run(scenario())


def test_best_effort_reload_never_replaces_the_thread(tmp_path, monkeypatch):
    async def scenario():
        brain = make_brain(tmp_path)
        calls = []

        async def request(method, params):
            calls.append(method)
            raise CodexError("resume refused")

        monkeypatch.setattr(brain, "_request", request)
        with pytest.raises(CodexError):
            await brain._start_thread("thread", fallback_to_fresh=False)
        assert calls == ["thread/resume"]

    asyncio.run(scenario())


def test_effort_is_dropped_for_good_once_the_server_rejects_it(tmp_path, monkeypatch):
    async def scenario():
        brain = make_brain(tmp_path, effort="high")
        seen = []

        async def request(method, params):
            seen.append(dict(params))
            if "effort" in params:
                raise CodexError("unknown field `effort`")
            return {"thread": {"id": "t1"}}

        monkeypatch.setattr(brain, "_request", request)
        await brain._start_thread(None)
        assert [("effort" in p) for p in seen] == [True, False]
        assert brain._effort_unsupported is True
        seen.clear()
        await brain._start_thread(None)
        assert [("effort" in p) for p in seen] == [False]  # not retried on later starts

    asyncio.run(scenario())


def test_a_thread_response_without_an_id_is_an_error(tmp_path, monkeypatch):
    async def scenario():
        brain = make_brain(tmp_path)

        async def request(method, params):
            return {"thread": {}}

        monkeypatch.setattr(brain, "_request", request)
        with pytest.raises(CodexError, match="thread id"):
            await brain._start_thread(None)

    asyncio.run(scenario())
