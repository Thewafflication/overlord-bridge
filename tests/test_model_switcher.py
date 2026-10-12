"""/model and /effort show the current values and offer buttons to switch."""

import asyncio
from types import SimpleNamespace

import pytest

import bridge
from modules.claude_brain import ClaudeBrain
from modules.codex_brain import CodexBrain
from modules.conversation_history import SharedConversationHistory
from test_bridge_dispatch import FakeTelegram


class Gate:
    def __init__(self, *answers):
        self.answers = list(answers)
        self.prompts = []

    async def choose(self, prompt, options):
        self.prompts.append((prompt, list(options)))
        answer = self.answers.pop(0) if self.answers else None
        if isinstance(answer, asyncio.Future):
            return await answer
        return answer


class Brain:
    name = "claude"
    supports_effort = True
    session_id = "s"

    def __init__(self, model="opus", effort=None, options=None, efforts=None):
        self.model, self.effort = model, effort
        self._options = options if options is not None else [
            ("opus", "most capable"), ("sonnet", "balanced"), ("haiku", "fastest")]
        self._efforts = efforts if efforts is not None else [
            ("default", "engine default"), ("low", ""), ("high", "")]
        self.calls = []

    async def model_options(self):
        if isinstance(self._options, Exception):
            raise self._options
        return self._options

    async def effort_options(self):
        return self._efforts

    async def set_model(self, value):
        self.calls.append(("model", value))
        self.model = value

    async def set_effort(self, value):
        self.calls.append(("effort", value))
        self.effort = None if value == "default" else value

    async def status(self, *, force_refresh=False):
        return {"brain": self.name, "model": self.model, "session_id": "s"}


def make_bridge(brain, gate):
    instance = bridge.Bridge.__new__(bridge.Bridge)
    instance.brain, instance.brain_name = brain, brain.name
    instance.telegram = FakeTelegram()
    instance.gate = gate
    instance._brain_lock = asyncio.Lock()
    instance._status_cache, instance._status_by_brain = {}, {}
    instance._console_status_file = None
    instance._conversation_history = SharedConversationHistory()
    return instance


@pytest.fixture(autouse=True)
def no_env_writes(monkeypatch):
    saved = []
    monkeypatch.setattr(bridge, "set_env_value", lambda path, key, value: saved.append((key, value)))
    monkeypatch.setattr(bridge.Bridge, "_remember_engine_setting", staticmethod(lambda *a: None))
    yield saved
    for name in ("OVERLORD_MODEL", "OVERLORD_EFFORT", "OVERLORD_FREE_MODEL", "OVERLORD_CODEX_MODEL"):
        bridge.os.environ.pop(name, None)


async def settle(instance):
    task = instance._switcher_task
    if task is not None:
        await task
    await asyncio.sleep(0)


def run(coro):
    return asyncio.run(coro)


def test_model_command_shows_model_and_effort_then_offers_buttons(no_env_writes):
    async def scenario():
        brain, gate = Brain(effort="high"), Gate("sonnet")
        instance = make_bridge(brain, gate)
        await instance._handle_model(42, "/model")
        header = instance.telegram.messages[0][1]
        assert "Model [claude]: opus" in header and "Effort: high" in header
        assert "pick below" in header
        await settle(instance)
        prompt, options = gate.prompts[0]
        assert "Switch model for claude (now opus)" in prompt
        assert options[0] == ("opus", "● current — most capable")  # current first, marked
        assert [v for v, _ in options] == ["opus", "sonnet", "haiku", "⚙ Change effort…"]
        assert options[-1][1] == "now high"
        assert brain.calls == [("model", "sonnet")] and brain.model == "sonnet"
        assert ("OVERLORD_MODEL", "sonnet") in no_env_writes
        assert "→ sonnet" in instance.telegram.messages[-1][1]

    run(scenario())


def test_picking_the_current_value_changes_nothing():
    async def scenario():
        brain, gate = Brain(), Gate("opus")
        instance = make_bridge(brain, gate)
        await instance._handle_model(42, "/model")
        await settle(instance)
        assert brain.calls == [] and instance.telegram.messages[-1][1] == "Already using opus."

    run(scenario())


def test_an_unanswered_prompt_leaves_everything_alone():
    async def scenario():
        brain, gate = Brain(), Gate(None)
        instance = make_bridge(brain, gate)
        await instance._handle_model(42, "/model")
        await settle(instance)
        assert brain.calls == [] and len(instance.telegram.messages) == 1

    run(scenario())


def test_the_model_prompt_can_hop_to_effort_and_back_applies_the_choice(no_env_writes):
    async def scenario():
        brain = Brain(effort=None)
        gate = Gate("⚙ Change effort…", "high")
        instance = make_bridge(brain, gate)
        await instance._handle_model(42, "/model")
        await settle(instance)
        assert [p[0] for p in gate.prompts] == [
            "Switch model for claude (now opus):", "Switch effort for claude (now default):"]
        effort_options = gate.prompts[1][1]
        assert effort_options[0] == ("default", "● current — engine default")
        assert effort_options[-1][0] == "⚙ Change model…"
        assert brain.calls == [("effort", "high")] and ("OVERLORD_EFFORT", "high") in no_env_writes

    run(scenario())


def test_effort_command_leads_with_effort_and_mentions_the_model():
    async def scenario():
        brain, gate = Brain(effort="low"), Gate(None)
        instance = make_bridge(brain, gate)
        await instance._handle_effort(42, "/effort")
        header = instance.telegram.messages[0][1]
        assert "Effort [claude]: low" in header and "Model: opus" in header
        await settle(instance)
        assert gate.prompts[0][0] == "Switch effort for claude (now low):"

    run(scenario())


def test_brains_without_effort_get_a_plain_model_prompt_and_no_effort_menu():
    async def scenario():
        brain = Brain()
        brain.supports_effort = False
        gate = Gate(None)
        instance = make_bridge(brain, gate)
        await instance._handle_effort(42, "/effort")
        assert "no reasoning-effort setting" in instance.telegram.messages[-1][1]
        assert gate.prompts == []
        await instance._handle_model(42, "/model")
        await settle(instance)
        assert all("Change" not in value for value, _ in gate.prompts[0][1])
        assert "Effort:" not in instance.telegram.messages[-1][1]

    run(scenario())


def test_a_failing_or_empty_option_list_just_skips_the_buttons():
    async def scenario():
        for options in (RuntimeError("catalog down"), []):
            gate = Gate("anything")
            instance = make_bridge(Brain(options=options), gate)
            await instance._handle_model(42, "/model")
            await settle(instance)
            assert gate.prompts == []
            assert "Model [claude]: opus" in instance.telegram.messages[0][1]

    run(scenario())


def test_long_catalogs_are_trimmed_but_the_current_model_stays_visible():
    async def scenario():
        names = [(f"model-{n}", "") for n in range(20)]
        brain, gate = Brain(model="model-15", options=names), Gate(None)
        instance = make_bridge(brain, gate)
        await instance._handle_model(42, "/model")
        await settle(instance)
        options = gate.prompts[0][1]
        assert len(options) <= 8 and options[0][0] == "model-15"

    run(scenario())


def test_asking_again_replaces_the_previous_prompt():
    async def scenario():
        waiting = asyncio.get_running_loop().create_future()
        gate = Gate(waiting, None)
        instance = make_bridge(Brain(), gate)
        await instance._handle_model(42, "/model")
        first = instance._switcher_task
        await asyncio.sleep(0)
        await instance._handle_model(42, "/model")
        await settle(instance)
        assert first.cancelled() and len(gate.prompts) == 2

    run(scenario())


def test_a_button_tapped_during_a_turn_is_refused_not_queued():
    async def scenario():
        brain, gate = Brain(), Gate("sonnet")
        instance = make_bridge(brain, gate)
        busy = asyncio.get_running_loop().create_future()
        instance._active_turn_task = asyncio.ensure_future(busy)
        await instance._handle_model(42, "/model")
        await settle(instance)
        assert brain.calls == [] and "turn is active" in instance.telegram.messages[-1][1]
        busy.set_result(None)
        await instance._active_turn_task

    run(scenario())


def test_without_a_prompt_gate_the_text_message_still_works():
    async def scenario():
        instance = make_bridge(Brain(), SimpleNamespace())
        await instance._handle_model(42, "/model")
        assert instance._switcher_task is None
        assert "Model [claude]: opus" in instance.telegram.messages[-1][1]

    run(scenario())


# -------------------------------------------------------------- per-brain lists
def test_claude_offers_aliases_the_configured_model_and_every_effort(tmp_path):
    brain = ClaudeBrain(gate=None, cwd=str(tmp_path), model="claude-opus-test", session_file=tmp_path / "p")
    models = run(brain.model_options())
    assert [m for m, _ in models] == ["opus", "sonnet", "haiku", "claude-opus-test"]
    efforts = [e for e, _ in run(brain.effort_options())]
    assert efforts == ["default", "low", "medium", "high", "xhigh", "max"]


def test_codex_lists_its_native_catalog_and_survives_a_failure(tmp_path, monkeypatch):
    brain = CodexBrain(gate=None, cwd=str(tmp_path), model="custom-model", session_file=tmp_path / "p",
                       developer_instructions="")

    async def catalog():
        return {"gpt-b", "gpt-a"}

    monkeypatch.setattr(brain, "routing_model_ids", catalog)
    assert [m for m, _ in run(brain.model_options())] == ["gpt-a", "gpt-b", "custom-model"]

    async def broken():
        raise RuntimeError("no app-server")

    monkeypatch.setattr(brain, "routing_model_ids", broken)
    assert [m for m, _ in run(brain.model_options())] == ["custom-model"]
    assert [e for e, _ in run(brain.effort_options())] == ["default", "minimal", "low", "medium", "high"]


def test_free_models_are_listed_with_their_availability(tmp_path):
    from modules.free_brain import FreeBrain, ModelSpec, UsageLimiter

    a, b = ModelSpec("nvidia", "m/a"), ModelSpec("nvidia", "m/b")
    limiter = UsageLimiter(None, {})
    limiter.cool_down(b.key, 120)
    brain = FreeBrain(session_file=tmp_path / "p", models=[a, b], keys={"nvidia": "k"}, limiter=limiter)
    options = dict(run(brain.model_options()))
    assert options[a.key] == "ready" and "back in 2m" in options[b.key]
    assert run(brain.effort_options()) == []
