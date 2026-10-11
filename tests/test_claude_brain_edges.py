"""ClaudeBrain turn handling, permission mapping, session pin, and usage helpers."""

import asyncio
import json
import os
import time
from types import SimpleNamespace

import pytest
from claude_agent_sdk import (
    AssistantMessage,
    PermissionResultAllow,
    PermissionResultDeny,
    ResultMessage,
    TextBlock,
)

from modules import claude_brain
from modules.brain import PermissionGate
from modules.claude_brain import ClaudeBrain, _accumulate, _countable_model


class Telegram:
    def __init__(self):
        self.messages = []
        self.prompts = []

    def send(self, owner, text):
        self.messages.append(text)

    def ask_permission(self, owner, text, request_id):
        self.prompts.append(request_id)

    def cancel_permission(self, owner, request_id):
        pass


def make_brain(tmp_path, *, gate=None, **kwargs):
    return ClaudeBrain(
        gate=gate or PermissionGate(Telegram(), 42, 1),
        cwd=str(tmp_path), model="opus", session_file=tmp_path / ".session.claude", **kwargs,
    )


def result(session="sess", *, error=False, text="done", usage=None, subtype="success"):
    return ResultMessage(
        subtype=subtype, duration_ms=1, duration_api_ms=1, is_error=error, num_turns=1,
        session_id=session, result=text, usage=usage, total_cost_usd=0.01 if usage else None,
    )


def assistant(*texts, model="claude-opus-test", usage=None):
    message = AssistantMessage(content=[TextBlock(text=t) for t in texts], model=model)
    if usage is not None:
        message.usage = usage
    return message


class ScriptedClient:
    def __init__(self, messages, *, fail_after=None):
        self.messages = messages
        self.fail_after = fail_after
        self.queries = []
        self.disconnected = False

    async def query(self, text):
        self.queries.append(text)

    async def receive_response(self):
        for index, message in enumerate(self.messages):
            if self.fail_after is not None and index == self.fail_after:
                raise RuntimeError("stream died")
            yield message

    async def disconnect(self):
        self.disconnected = True


def use_client(brain, monkeypatch, client):
    async def open_client(resume):
        brain.opened_with = resume
        return client

    monkeypatch.setattr(brain, "_open", open_client)
    monkeypatch.setattr(claude_brain.shared_job, "live_job", lambda pin: None)


async def collect(brain, text="hi"):
    return [chunk async for chunk in brain.query(text)]


# ------------------------------------------------------------- turn handling
def test_turn_relays_text_blocks_and_records_usage_and_the_new_pin(tmp_path, monkeypatch):
    brain = make_brain(tmp_path)
    usage = {"input_tokens": 10, "output_tokens": 5}
    client = ScriptedClient(
        [assistant("first", "  ", "second"), result("new-sess", usage=usage)]
    )
    use_client(brain, monkeypatch, client)
    chunks = asyncio.run(collect(brain))
    assert chunks == ["first", "second"]  # blank blocks are not relayed
    assert client.queries == ["hi"] and client.disconnected
    assert brain.last_turn_usage == usage and brain.last_turn_cost_usd == 0.01
    assert brain.last_turn_outcome == "ok" and brain._active_model == "claude-opus-test"
    assert (tmp_path / ".session.claude").read_text(encoding="utf-8") == "new-sess"
    assert brain.session_id == "new-sess"


def test_result_text_is_used_only_when_no_text_block_was_streamed(tmp_path, monkeypatch):
    brain = make_brain(tmp_path)
    use_client(brain, monkeypatch, ScriptedClient([result(text="from result")]))
    assert asyncio.run(collect(brain)) == ["from result"]
    use_client(brain, monkeypatch, ScriptedClient([assistant("streamed"), result(text="dup")]))
    assert asyncio.run(collect(brain)) == ["streamed"]


def test_error_results_are_surfaced_and_marked(tmp_path, monkeypatch):
    brain = make_brain(tmp_path)
    use_client(brain, monkeypatch, ScriptedClient(
        [result(error=True, text="Claude usage limit reached", usage={"output_tokens": 3})]
    ))
    assert asyncio.run(collect(brain)) == ["⚠️ Claude usage limit reached"]
    assert brain.last_turn_outcome == "error"
    assert brain.last_turn_usage == {"output_tokens": 3}
    use_client(brain, monkeypatch, ScriptedClient([result(error=True, text="")]))
    assert asyncio.run(collect(brain)) == ["⚠️ The Overlord hit an error."]


def test_a_turn_that_dies_midstream_keeps_the_partial_tally_and_disconnects(tmp_path, monkeypatch):
    brain = make_brain(tmp_path)
    client = ScriptedClient(
        [assistant("part", usage={"input_tokens": 7, "output_tokens": 2}),
         assistant("more", usage={"input_tokens": 3, "output_tokens": 1}),
         result()],
        fail_after=2,
    )
    use_client(brain, monkeypatch, client)
    with pytest.raises(RuntimeError, match="stream died"):
        asyncio.run(collect(brain))
    assert client.disconnected
    assert brain.last_turn_usage == {"input_tokens": 10, "output_tokens": 3}


def test_usage_from_the_final_result_replaces_the_running_tally(tmp_path, monkeypatch):
    brain = make_brain(tmp_path)
    use_client(brain, monkeypatch, ScriptedClient([
        assistant("x", usage={"input_tokens": 1}), result(usage={"input_tokens": 99}),
    ]))
    asyncio.run(collect(brain))
    assert brain.last_turn_usage == {"input_tokens": 99}


def test_each_turn_starts_with_clean_accounting(tmp_path, monkeypatch):
    brain = make_brain(tmp_path)
    brain.last_turn_usage = {"input_tokens": 500}
    brain.last_turn_cost_usd = 9.0
    brain.last_turn_outcome = "error"
    use_client(brain, monkeypatch, ScriptedClient([result(text="ok")]))
    asyncio.run(collect(brain))
    assert brain.last_turn_usage is None and brain.last_turn_cost_usd is None
    assert brain.last_turn_outcome == "ok"


def test_the_pin_is_reread_every_turn_so_terminal_sessions_are_picked_up(tmp_path, monkeypatch):
    brain = make_brain(tmp_path)
    use_client(brain, monkeypatch, ScriptedClient([result("a", text="1")]))
    (tmp_path / ".session.claude").write_text("from-terminal\n", encoding="utf-8")
    asyncio.run(collect(brain))
    assert brain.opened_with == "from-terminal"


def test_sdk_slash_commands_are_remembered_from_the_init_message(tmp_path, monkeypatch):
    from claude_agent_sdk import SystemMessage

    brain = make_brain(tmp_path)
    init = SystemMessage(subtype="init", data={"slash_commands": ["compact", 7, "clear"]})
    boundary = SystemMessage(subtype="compact_boundary", data={})
    use_client(brain, monkeypatch, ScriptedClient([init, boundary, result(text="x")]))
    asyncio.run(collect(brain))
    assert brain._available_commands == {"compact", "clear"}
    assert brain.compaction_status == "completed"


# ------------------------------------------------------------ session pin
def test_connect_adopts_the_saved_pin_or_an_explicit_one(tmp_path):
    brain = make_brain(tmp_path)
    asyncio.run(brain.connect())
    assert brain.session_id is None
    (tmp_path / ".session.claude").write_text("  saved-id \n", encoding="utf-8")
    asyncio.run(brain.connect())
    assert brain.session_id == "saved-id"
    asyncio.run(brain.connect(resume="explicit"))
    assert brain.session_id == "explicit"


def test_pin_is_only_rewritten_when_the_session_changes(tmp_path):
    brain = make_brain(tmp_path)
    brain._save_session("one")
    pin = tmp_path / ".session.claude"
    pin.write_text("tampered", encoding="utf-8")
    brain._save_session("one")  # unchanged: no write
    assert pin.read_text(encoding="utf-8") == "tampered"
    brain._save_session("")
    brain._save_session("two")
    assert pin.read_text(encoding="utf-8") == "two"


def test_reset_forgets_the_pin_and_the_context_snapshot(tmp_path):
    brain = make_brain(tmp_path)
    brain._save_session("one")
    brain.context_snapshot = {"used": 1}
    asyncio.run(brain.reset())
    assert brain.session_id is None and brain.context_snapshot is None
    assert not (tmp_path / ".session.claude").exists()
    asyncio.run(brain.reset())  # idempotent


def test_a_dead_resume_falls_back_to_a_fresh_session_and_drops_the_pin(tmp_path, monkeypatch):
    brain = make_brain(tmp_path)
    brain._save_session("stale")
    attempts = []

    class Client:
        def __init__(self, options):
            attempts.append(options.resume)

        async def connect(self):
            if attempts[-1] is not None:
                raise RuntimeError("No conversation found")

    monkeypatch.setattr(claude_brain, "ClaudeSDKClient", Client)
    client = asyncio.run(brain._open("stale"))
    assert attempts == ["stale", None] and isinstance(client, Client)
    assert brain.session_id is None and not (tmp_path / ".session.claude").exists()


def test_an_outage_does_not_destroy_the_pin_of_a_healthy_session(tmp_path, monkeypatch):
    brain = make_brain(tmp_path)
    brain._save_session("healthy")

    class Client:
        def __init__(self, options):
            pass

        async def connect(self):
            raise RuntimeError("claude CLI unavailable")  # resume AND fresh both fail

    monkeypatch.setattr(claude_brain, "ClaudeSDKClient", Client)
    with pytest.raises(RuntimeError, match="unavailable"):
        asyncio.run(brain._open("healthy"))
    assert (tmp_path / ".session.claude").read_text(encoding="utf-8") == "healthy"
    assert brain.session_id == "healthy"


def test_a_failed_fresh_connect_is_not_swallowed(tmp_path, monkeypatch):
    class Client:
        def __init__(self, options):
            pass

        async def connect(self):
            raise RuntimeError("claude is not installed")

    monkeypatch.setattr(claude_brain, "ClaudeSDKClient", Client)
    with pytest.raises(RuntimeError, match="not installed"):
        asyncio.run(make_brain(tmp_path)._open(None))


# ------------------------------------------------------------- permissions
def test_tools_are_denied_while_a_compaction_runs(tmp_path):
    brain = make_brain(tmp_path)
    brain._compaction_active = True
    decision = asyncio.run(brain.can_use_tool("Bash", {"command": "ls"}, SimpleNamespace()))
    assert isinstance(decision, PermissionResultDeny) and "compaction" in decision.message


def test_secret_paths_are_denied_without_ever_asking_the_phone(tmp_path):
    telegram = Telegram()
    brain = make_brain(tmp_path, gate=PermissionGate(telegram, 42, 1))
    decision = asyncio.run(
        brain.can_use_tool("Read", {"file_path": "~/.ssh/id_ed25519"}, SimpleNamespace())
    )
    assert isinstance(decision, PermissionResultDeny)
    assert telegram.prompts == [] and "Auto-denied" in telegram.messages[-1]


def test_operator_decisions_map_to_sdk_results(tmp_path):
    async def scenario(decision):
        telegram = Telegram()
        brain = make_brain(tmp_path, gate=PermissionGate(telegram, 42, 1))
        task = asyncio.create_task(
            brain.can_use_tool("Bash", {"command": "make"}, SimpleNamespace(title="Run make"))
        )
        await asyncio.sleep(0)
        assert "Run make" in brain.gate.pending or telegram.prompts
        brain.gate.on_permission_response(telegram.prompts[-1], decision)
        return await task

    assert isinstance(asyncio.run(scenario("allow")), PermissionResultAllow)
    assert isinstance(asyncio.run(scenario("deny")), PermissionResultDeny)


def test_detail_prefers_the_command_then_the_first_path_and_adds_the_title():
    detail = ClaudeBrain._format_detail
    assert detail("Bash", {"command": "ls -la"}, SimpleNamespace()) == "ls -la"
    assert detail("Edit", {"file_path": "a.py", "path": "b.py"}, SimpleNamespace()) == "a.py"
    assert detail("Edit", {"path": "b.py"}, SimpleNamespace(title="Edit b")) == "Edit b\n\nb.py"
    assert detail("Tool", {}, SimpleNamespace(display_name="Custom")) == "Custom"
    assert detail("Tool", {"command": 5}, SimpleNamespace()) == ""


def test_auto_approved_edits_stay_inside_the_workspace(tmp_path):
    brain = make_brain(tmp_path, auto_approve_edits=True)
    inside = brain._is_safe_workspace_edit
    assert inside("Write", ["src/app.py"]) is True
    assert inside("Write", [str(tmp_path / "src" / "app.py")]) is True
    assert inside("Write", ["../outside.py"]) is False
    assert inside("Write", [str(tmp_path.parent / "outside.py")]) is False
    assert inside("Write", [".ssh/authorized_keys"]) is False
    assert inside("Write", ["notes/id_rsa"]) is False
    assert inside("Bash", ["src/app.py"]) is False  # only the edit tools qualify
    assert inside("Write", []) is False
    assert inside("Write", ["ok.py", "../bad.py"]) is False  # every path must qualify


def test_auto_approval_is_off_by_default(tmp_path):
    telegram = Telegram()
    brain = make_brain(tmp_path, gate=PermissionGate(telegram, 42, 0.05))
    decision = asyncio.run(brain.can_use_tool("Write", {"file_path": "a.py"}, SimpleNamespace()))
    assert isinstance(decision, PermissionResultDeny) and telegram.prompts


# ---------------------------------------------------------------- questions
@pytest.mark.parametrize(
    "tool_input",
    [
        {},
        {"questions": []},
        {"questions": "nope"},
        {"questions": [{"question": " "}]},
        {"questions": [{"question": "A"}, {"question": "A"}]},
        {"questions": [{"question": f"Q{n}"} for n in range(5)]},
        {"questions": ["not a dict"]},
    ],
)
def test_malformed_question_sets_are_denied_without_prompting(tmp_path, tool_input):
    telegram = Telegram()
    telegram.ask_choice = lambda *a: telegram.prompts.append(a)
    brain = make_brain(tmp_path, gate=PermissionGate(telegram, 42, 1))
    decision = asyncio.run(brain.can_use_tool("AskUserQuestion", tool_input, SimpleNamespace()))
    assert isinstance(decision, PermissionResultDeny)
    assert telegram.prompts == []


# ------------------------------------------------------------------ helpers
def test_model_ids_are_chosen_override_first_then_full_ids_then_aliases(monkeypatch):
    monkeypatch.delenv("OVERLORD_COUNT_TOKENS_MODEL", raising=False)
    assert _countable_model("claude-custom-1", "opus") == "claude-custom-1"
    assert _countable_model("opus") == claude_brain.COUNT_TOKENS_ALIASES["opus"]
    assert _countable_model("Haiku") == claude_brain.COUNT_TOKENS_ALIASES["haiku"]
    assert _countable_model("", None) == claude_brain.COUNT_TOKENS_ALIASES["sonnet"]
    monkeypatch.setenv("OVERLORD_COUNT_TOKENS_MODEL", "  pinned  ")
    assert _countable_model("claude-custom-1") == "pinned"


def test_running_tally_ignores_negative_and_non_integer_counters():
    running = {"input_tokens": 5}
    _accumulate(running, {"input_tokens": 3, "output_tokens": 2, "bad": -1, "worse": "x", "flag": 1.5})
    assert running == {"input_tokens": 8, "output_tokens": 2}


def test_effort_levels_are_validated_and_cleared(tmp_path):
    brain = make_brain(tmp_path)
    assert "Unknown effort" in asyncio.run(brain.set_effort("ludicrous"))
    assert brain.effort is None
    assert asyncio.run(brain.set_effort("HIGH")) is None and brain.effort == "high"
    assert asyncio.run(brain.set_effort("off")) is None and brain.effort is None


def test_an_sdk_without_effort_support_leaves_effort_unset(tmp_path, monkeypatch):
    brain = make_brain(tmp_path)
    monkeypatch.setattr(brain, "_effort_option", lambda: {})
    assert "no reasoning-effort option" in asyncio.run(brain.set_effort("high"))
    assert brain.effort is None


def test_set_model_rejects_blank_names_and_resets_the_snapshot(tmp_path):
    brain = make_brain(tmp_path)
    brain.context_snapshot = {"used": 1}
    assert "Give a model name" in asyncio.run(brain.set_model("  "))
    assert brain.model == "opus" and brain.context_snapshot == {"used": 1}
    assert asyncio.run(brain.set_model("sonnet")) is None
    assert brain.model == "sonnet" and brain._active_model == "sonnet"
    assert brain.context_snapshot is None


def test_token_counting_falls_back_to_a_local_estimate(tmp_path, monkeypatch):
    brain = make_brain(tmp_path)

    async def no_token():
        return None

    monkeypatch.setattr(claude_brain, "_claude_access_token", no_token)
    assert asyncio.run(brain.count_input_tokens("   ")) == (0, "exact")
    count, source = asyncio.run(brain.count_input_tokens("hello world, count me"))
    assert source == "estimate" and count > 0


def test_usage_windows_are_normalized_and_clamped():
    normalize = claude_brain._normalize_claude_usage
    assert normalize(None) is None and normalize({}) is None
    assert normalize({"five_hour": {"utilization": None}}) is None
    usage = normalize({"five_hour": {"utilization": "12.34", "resets_at": "t"},
                       "seven_day": {"utilization": 130}})
    assert usage["session"] == {"used": 12.3, "gas": 87.7, "resets_at": "t"}
    assert usage["weekly"]["gas"] == 0  # over 100% never reports negative gas


def test_fresh_usage_cache_is_used_without_a_network_call(tmp_path, monkeypatch):
    cache = tmp_path / "usage.json"
    cache.write_text(json.dumps({"five_hour": {"utilization": 5}}), encoding="utf-8")
    monkeypatch.setattr(claude_brain, "CLAUDE_USAGE_CACHE", cache)
    monkeypatch.setattr(claude_brain, "CLAUDE_CREDENTIALS", tmp_path / "missing.json")
    payload, stale = asyncio.run(claude_brain._claude_usage_payload())
    assert payload["five_hour"]["utilization"] == 5 and stale is False


def test_old_usage_cache_is_served_stale_when_there_is_no_token(tmp_path, monkeypatch):
    cache = tmp_path / "usage.json"
    cache.write_text(json.dumps({"five_hour": {"utilization": 5}}), encoding="utf-8")
    old = time.time() - 3600
    os.utime(cache, (old, old))
    monkeypatch.setattr(claude_brain, "CLAUDE_USAGE_CACHE", cache)
    monkeypatch.setattr(claude_brain, "CLAUDE_CREDENTIALS", tmp_path / "missing.json")
    payload, stale = asyncio.run(claude_brain._claude_usage_payload())
    assert payload is not None and stale is True
    payload, stale = asyncio.run(claude_brain._claude_usage_payload(max_cache_age=0))
    assert stale is True
    cache.write_text("not json", encoding="utf-8")
    assert asyncio.run(claude_brain._claude_usage_payload()) == (None, False)
