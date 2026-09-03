"""Each brain's per-turn usage reporting and its runtime model/effort knobs."""

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from claude_agent_sdk import (  # noqa: E402
    AssistantMessage,
    ResultMessage,
    TextBlock,
)

from modules import shared_job  # noqa: E402
from modules.claude_brain import ClaudeBrain, _countable_model  # noqa: E402
from modules.token_meter import normalize_usage  # noqa: E402


CLAUDE_TURN_USAGE = {
    "input_tokens": 1240,
    "output_tokens": 830,
    "cache_read_input_tokens": 12400,
}


class ReportingClient:
    """A fake ClaudeSDKClient whose turn closes with real usage numbers."""

    def __init__(self, usage=CLAUDE_TURN_USAGE, cost=0.031):
        self.usage = usage
        self.cost = cost

    async def query(self, text):
        self.queried_text = text

    async def receive_response(self):
        yield AssistantMessage(content=[TextBlock(text="hi")], model="claude-opus-4-1")
        yield ResultMessage(
            subtype="success",
            duration_ms=1,
            duration_api_ms=1,
            is_error=False,
            num_turns=1,
            session_id="session-9",
            result="hi",
            usage=self.usage,
            total_cost_usd=self.cost,
        )

    async def disconnect(self):
        return None


def make_brain(tmp_path, **kwargs):
    return ClaudeBrain(
        gate=None,
        cwd=str(tmp_path),
        model="opus",
        session_file=tmp_path / ".session.claude",
        **kwargs,
    )


def run_turn(brain, monkeypatch, client):
    monkeypatch.setattr("modules.shared_job.live_job", lambda _pin: None)

    async def fake_open(_resume):
        return client

    monkeypatch.setattr(brain, "_open", fake_open)

    async def drain():
        return [chunk async for chunk in brain.query("do the thing")]

    return asyncio.run(drain())


def test_claude_records_the_turns_usage_and_cost(tmp_path, monkeypatch):
    brain = make_brain(tmp_path)
    assert run_turn(brain, monkeypatch, ReportingClient()) == ["hi"]
    assert brain.last_turn_usage == CLAUDE_TURN_USAGE
    assert brain.last_turn_cost_usd == 0.031
    usage = normalize_usage(brain.last_turn_usage, cost_usd=brain.last_turn_cost_usd)
    assert usage.billed_input == 1240
    assert usage.output_tokens == 830


def test_a_turn_reporting_no_usage_leaves_nothing_stale_behind(tmp_path, monkeypatch):
    brain = make_brain(tmp_path)
    run_turn(brain, monkeypatch, ReportingClient())
    assert brain.last_turn_usage is not None
    # The next turn reports nothing; the previous turn's numbers must not
    # linger to be booked a second time.
    run_turn(brain, monkeypatch, ReportingClient(usage=None, cost=None))
    assert brain.last_turn_usage is None


def test_effort_reaches_the_sdk_options_only_when_set(tmp_path):
    assert make_brain(tmp_path)._build_options(None).effort is None
    brain = make_brain(tmp_path, effort="high")
    assert brain._build_options(None).effort == "high"


def test_set_effort_validates_and_clears(tmp_path):
    brain = make_brain(tmp_path)
    assert asyncio.run(brain.set_effort("nonsense")) is not None
    assert brain.effort is None
    assert asyncio.run(brain.set_effort("xhigh")) is None
    assert brain.effort == "xhigh"
    assert asyncio.run(brain.set_effort("default")) is None
    assert brain.effort is None


def test_set_model_applies_to_the_next_turn_without_reconnecting(tmp_path):
    brain = make_brain(tmp_path)
    assert asyncio.run(brain.set_model("sonnet")) is None
    assert brain._build_options(None).model == "sonnet"
    assert asyncio.run(brain.set_model("  ")) is not None


def test_counting_falls_back_to_an_estimate_without_credentials(tmp_path, monkeypatch):
    brain = make_brain(tmp_path)

    async def no_token():
        return None

    monkeypatch.setattr("modules.claude_brain._claude_access_token", no_token)
    count, source = asyncio.run(brain.count_input_tokens("word " * 100))
    assert source == "estimate"
    assert count > 50
    assert asyncio.run(brain.count_input_tokens("   ")) == (0, "exact")


def test_the_countable_model_prefers_a_resolved_id_over_an_alias(monkeypatch):
    monkeypatch.setenv("OVERLORD_COUNT_TOKENS_MODEL", "")
    assert _countable_model("claude-opus-4-1-20250805", "opus") == (
        "claude-opus-4-1-20250805"
    )
    assert _countable_model("", "opus").startswith("claude-opus")
    assert _countable_model("", "").startswith("claude-")
    monkeypatch.setenv("OVERLORD_COUNT_TOKENS_MODEL", "pinned-model")
    assert _countable_model("", "opus") == "pinned-model"


# --------------------------------------------------------------------- codex
def make_codex_brain(tmp_path):
    import modules.codex_brain as cb

    brain = cb.CodexBrain.__new__(cb.CodexBrain)
    brain._last_turn_token_usage = None
    brain._token_usage_total = None
    brain._prev_token_usage_total = None
    return brain


def test_codex_prefers_its_own_per_turn_block(tmp_path):
    brain = make_codex_brain(tmp_path)
    brain._last_turn_token_usage = {"inputTokens": 900, "outputTokens": 610}
    brain._token_usage_total = {"inputTokens": 9000, "outputTokens": 6100}
    assert brain._resolve_turn_usage() == {"inputTokens": 900, "outputTokens": 610}


def test_codex_differences_running_totals_when_no_per_turn_block_arrives(tmp_path):
    brain = make_codex_brain(tmp_path)
    brain._prev_token_usage_total = {"inputTokens": 400, "outputTokens": 210}
    brain._token_usage_total = {"inputTokens": 900, "outputTokens": 610}
    delta = brain._resolve_turn_usage()
    assert delta["input_tokens"] == 500
    assert delta["output_tokens"] == 400


def test_codex_reports_nothing_when_the_turn_moved_no_tokens(tmp_path):
    brain = make_codex_brain(tmp_path)
    brain._prev_token_usage_total = {"inputTokens": 900}
    brain._token_usage_total = {"inputTokens": 900}
    assert brain._resolve_turn_usage() is None


def test_codex_drops_the_effort_parameter_when_the_app_server_rejects_it(tmp_path):
    import modules.codex_brain as cb

    brain = cb.CodexBrain.__new__(cb.CodexBrain)
    brain.cwd = str(tmp_path)
    brain.approval_policy = "on-request"
    brain.sandbox = "read-only"
    brain.developer_instructions = ""
    brain.model = "gpt-5-codex"
    brain.effort = "high"
    brain._effort_unsupported = False
    brain.session_file = tmp_path / ".session.codex"
    seen = []

    async def fake_request(method, params):
        seen.append(dict(params))
        if "effort" in params:
            raise cb.CodexError("unknown field `effort`")
        return {"thread": {"id": "t1"}, "model": "gpt-5-codex"}

    brain._request = fake_request
    brain._save_thread_id = lambda thread_id: setattr(brain, "_thread_id", thread_id)

    asyncio.run(brain._start_thread(None))

    # Tried once with effort, retried without it, and remembered not to re-ask.
    assert "effort" in seen[0] and "effort" not in seen[1]
    assert brain._effort_unsupported is True
    assert brain._thread_id == "t1"
