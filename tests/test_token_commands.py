"""/tokens, /quote, /model and /effort, plus the per-turn footer."""

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import bridge  # noqa: E402
from modules.token_meter import TokenLedger, normalize_usage  # noqa: E402


class FakeTelegram:
    def __init__(self):
        self.messages = []

    def send(self, chat_id, text):
        self.messages.append((chat_id, text))

    def begin_typing(self, chat_id):
        pass

    def end_typing(self, chat_id):
        pass


class FakeBrain:
    name = "claude"
    supports_effort = True
    session_id = "session-1"

    def __init__(self, *, usage=None, cost=None, count=(1834, "exact")):
        self.model = "opus"
        self.effort = None
        self.last_turn_usage = usage
        self.last_turn_cost_usd = cost
        self.last_turn_outcome = "ok"
        self._count = count
        self.set_model_calls = []
        self.set_effort_calls = []
        self.set_model_error = None
        self.set_effort_error = None

    async def query(self, text):
        yield "answered"

    async def status(self, *, force_refresh: bool = False):
        return {"brain": self.name, "model": self.model, "session_id": self.session_id}

    async def count_input_tokens(self, text):
        return self._count

    async def set_model(self, model):
        self.set_model_calls.append(model)
        if self.set_model_error:
            return self.set_model_error
        self.model = model
        return None

    async def interrupt_active_turn(self):
        return False

    async def set_effort(self, effort):
        self.set_effort_calls.append(effort)
        if self.set_effort_error:
            return self.set_effort_error
        self.effort = effort or None
        return None


def make_bridge(brain, *, env_file=None):
    instance = bridge.Bridge.__new__(bridge.Bridge)
    instance.brain = brain
    instance.brain_name = brain.name
    instance.telegram = FakeTelegram()
    instance._brain_lock = asyncio.Lock()
    instance._active_turn_task = None
    instance._pending_handoff = None
    instance._status_timeout = 0.05
    instance.tokens = TokenLedger()
    instance._status_cache = instance._basic_status()
    instance._conversation_history = bridge.SharedConversationHistory()
    instance._conversation_history.mark_seen(brain.name)
    return instance


# ------------------------------------------------------------------- /tokens
def test_tokens_reports_recorded_prompts():
    instance = make_bridge(FakeBrain())
    instance.tokens.record(
        normalize_usage(
            {"input_tokens": 100, "output_tokens": 50}, brain="claude", prompt="ask one"
        )
    )
    instance._handle_tokens(42, "/tokens")
    assert "ask one" in instance.telegram.messages[-1][1]


def test_tokens_honours_a_count_and_rejects_nonsense():
    instance = make_bridge(FakeBrain())
    for index in range(5):
        instance.tokens.record(
            normalize_usage({"input_tokens": index + 1, "output_tokens": 1})
        )
    instance._handle_tokens(42, "/tokens 2")
    assert "Last 2 prompts" in instance.telegram.messages[-1][1]
    instance._handle_tokens(42, "/tokens lots")
    assert "Usage: /tokens" in instance.telegram.messages[-1][1]


# -------------------------------------------------------------------- /quote
def test_quote_uses_the_brains_exact_count_without_running_a_turn():
    async def scenario():
        brain = FakeBrain(count=(1834, "exact"))
        instance = make_bridge(brain)
        await instance._handle_quote(42, "/quote please refactor the parser")
        reply = instance.telegram.messages[-1][1]
        assert "1,834" in reply
        assert "exact" in reply

    asyncio.run(scenario())


def test_quote_falls_back_to_a_labelled_estimate_when_counting_fails():
    async def scenario():
        brain = FakeBrain()

        async def boom(_text):
            raise RuntimeError("no network")

        brain.count_input_tokens = boom
        instance = make_bridge(brain)
        await instance._handle_quote(42, "/quote " + "word " * 200)
        reply = instance.telegram.messages[-1][1]
        assert "estimated" in reply
        assert "local estimate" in reply

    asyncio.run(scenario())


def test_quote_includes_context_that_would_ride_along_with_the_next_turn():
    async def scenario():
        instance = make_bridge(FakeBrain(count=(100, "exact")))
        instance._pending_handoff = bridge.Handoff("x" * 4000, 3, 4)
        await instance._handle_quote(42, "/quote short prompt")
        assert "carried-over conversation" in instance.telegram.messages[-1][1]

    asyncio.run(scenario())


def test_quote_without_text_explains_itself():
    async def scenario():
        instance = make_bridge(FakeBrain())
        await instance._handle_quote(42, "/quote")
        assert "Usage: /quote" in instance.telegram.messages[-1][1]

    asyncio.run(scenario())


# ------------------------------------------------------------ /model, /effort
def test_model_with_no_argument_shows_the_current_value():
    async def scenario():
        instance = make_bridge(FakeBrain())
        await instance._handle_model(42, "/model")
        assert "Model [claude]: opus" in instance.telegram.messages[-1][1]

    asyncio.run(scenario())


def test_model_switches_the_brain_and_persists_to_env(tmp_path, monkeypatch):
    async def scenario():
        env_file = tmp_path / ".env"
        env_file.write_text("OVERLORD_MODEL=opus\nKEEP=me\n", encoding="utf-8")
        monkeypatch.setattr(bridge, "BASE_DIR", tmp_path)
        brain = FakeBrain()
        instance = make_bridge(brain)
        await instance._handle_model(42, "/model sonnet")
        assert brain.set_model_calls == ["sonnet"]
        assert "sonnet" in instance.telegram.messages[-1][1]
        written = env_file.read_text(encoding="utf-8")
        assert "OVERLORD_MODEL=sonnet" in written
        assert "KEEP=me" in written

    asyncio.run(scenario())


def test_a_rejected_model_is_reported_and_nothing_is_persisted(tmp_path, monkeypatch):
    async def scenario():
        env_file = tmp_path / ".env"
        env_file.write_text("OVERLORD_MODEL=opus\n", encoding="utf-8")
        monkeypatch.setattr(bridge, "BASE_DIR", tmp_path)
        brain = FakeBrain()
        brain.set_model_error = "Codex refused the new model"
        instance = make_bridge(brain)
        await instance._handle_model(42, "/model nope")
        assert "⚠️" in instance.telegram.messages[-1][1]
        assert env_file.read_text(encoding="utf-8") == "OVERLORD_MODEL=opus\n"

    asyncio.run(scenario())


def test_effort_persists_under_the_brains_own_env_key(tmp_path, monkeypatch):
    async def scenario():
        env_file = tmp_path / ".env"
        env_file.write_text("OVERLORD_CODEX_EFFORT=low\n", encoding="utf-8")
        monkeypatch.setattr(bridge, "BASE_DIR", tmp_path)
        brain = FakeBrain()
        brain.name = "codex"
        instance = make_bridge(brain)
        await instance._handle_effort(42, "/effort high")
        written = env_file.read_text(encoding="utf-8")
        # The Codex key is updated; the Claude key is never touched by it.
        assert "OVERLORD_CODEX_EFFORT=high" in written
        assert "OVERLORD_EFFORT=" not in written.replace("OVERLORD_CODEX_EFFORT=", "")

    asyncio.run(scenario())


def test_effort_is_declined_by_a_brain_that_has_no_such_setting():
    async def scenario():
        brain = FakeBrain()
        brain.supports_effort = False
        instance = make_bridge(brain)
        await instance._handle_effort(42, "/effort high")
        assert "no reasoning-effort setting" in instance.telegram.messages[-1][1]
        assert brain.set_effort_calls == []

    asyncio.run(scenario())


def test_env_keys_are_scoped_per_brain():
    assert bridge.Bridge._env_key_for("model", "claude") == "OVERLORD_MODEL"
    assert bridge.Bridge._env_key_for("model", "codex") == "OVERLORD_CODEX_MODEL"
    assert bridge.Bridge._env_key_for("effort", "claude") == "OVERLORD_EFFORT"
    assert bridge.Bridge._env_key_for("effort", "codex") == "OVERLORD_CODEX_EFFORT"


# --------------------------------------------------------------- turn footer
def test_a_finished_turn_is_booked_and_reported(monkeypatch):
    async def scenario():
        monkeypatch.setattr(bridge, "TOKEN_FOOTER", True)
        brain = FakeBrain(
            usage={"input_tokens": 1240, "output_tokens": 830}, cost=0.03
        )
        instance = make_bridge(brain)
        await instance._handle_turn(42, "do the thing")
        assert instance.tokens.totals.prompts == 1
        assert instance.tokens.last.prompt_preview == "do the thing"
        assert "🧮" in instance.telegram.messages[-1][1]

    asyncio.run(scenario())


def test_the_footer_can_be_switched_off_without_losing_the_accounting(monkeypatch):
    async def scenario():
        monkeypatch.setattr(bridge, "TOKEN_FOOTER", False)
        brain = FakeBrain(usage={"input_tokens": 10, "output_tokens": 5})
        instance = make_bridge(brain)
        await instance._handle_turn(42, "quiet please")
        assert instance.tokens.totals.prompts == 1
        assert all("🧮" not in text for _, text in instance.telegram.messages)

    asyncio.run(scenario())


def test_a_turn_that_reports_no_usage_is_skipped_not_booked_as_zero():
    async def scenario():
        instance = make_bridge(FakeBrain(usage=None))
        await instance._handle_turn(42, "handed to the terminal session")
        assert instance.tokens.totals.prompts == 0

    asyncio.run(scenario())


def test_accounting_failures_never_break_a_delivered_reply():
    async def scenario():
        brain = FakeBrain(usage={"input_tokens": 10, "output_tokens": 5})
        instance = make_bridge(brain)

        class Exploding:
            def record(self, _usage):
                raise RuntimeError("disk gone")

        instance.tokens = Exploding()
        await instance._handle_turn(42, "still works")
        # The answer itself was delivered; only the footer is missing.
        assert ("answered" in text for _, text in instance.telegram.messages)

    asyncio.run(scenario())


# ------------------------------------------------- interrupted / failed turns
class SlowBrain(FakeBrain):
    """A brain whose turn hangs until it is cancelled, having spent tokens."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.started = asyncio.Event()

    async def query(self, text):
        self.started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            # Mirrors the real brains: the generator's own finally books
            # whatever the engine had reported before the interruption.
            self.last_turn_usage = {"input_tokens": 900, "output_tokens": 120}
            raise
        yield "never"


def test_a_stopped_turn_still_books_the_tokens_it_spent():
    async def scenario():
        brain = SlowBrain()
        instance = make_bridge(brain)
        instance._start_turn(42, "long job")
        await brain.started.wait()
        await instance._handle_stop(42)
        assert instance.tokens.totals.prompts == 1
        booked = instance.tokens.last
        assert booked.outcome == "stopped"
        assert booked.input_tokens == 900
        assert "stopped mid-turn" in instance.telegram.messages[-1][1]

    asyncio.run(scenario())


def test_a_steered_turn_books_the_abandoned_work_before_the_replacement():
    async def scenario():
        brain = SlowBrain()
        instance = make_bridge(brain)
        instance._start_turn(42, "first plan")
        await brain.started.wait()
        await instance._handle_steer(42, "/steer second plan")
        # The interrupted turn was booked, and labelled as cut short, before the
        # replacement turn had a chance to finish.
        assert instance.tokens.entries[0].outcome == "stopped"
        assert instance.tokens.entries[0].prompt_preview == "first plan"
        await instance._stop_active_turn()

    asyncio.run(scenario())


def test_a_failed_turn_is_booked_and_labelled():
    async def scenario():
        brain = FakeBrain(usage={"input_tokens": 300, "output_tokens": 10})

        async def exploding(text):
            brain.last_turn_usage = {"input_tokens": 300, "output_tokens": 10}
            raise RuntimeError("upstream said no")
            yield ""

        brain.query = exploding
        instance = make_bridge(brain)
        await instance._handle_turn(42, "doomed ask")
        assert instance.tokens.last.outcome == "error"
        assert instance.tokens.last.input_tokens == 300

    asyncio.run(scenario())


def test_an_engine_reported_failure_such_as_a_usage_cap_keeps_its_label():
    async def scenario():
        brain = FakeBrain(usage={"input_tokens": 50, "output_tokens": 5})
        brain.last_turn_outcome = "error"
        instance = make_bridge(brain)
        await instance._handle_turn(42, "one ask too many")
        # The bridge saw a clean turn; the engine's own verdict wins.
        assert instance.tokens.last.outcome == "error"

    asyncio.run(scenario())


def test_a_normal_turn_is_not_labelled():
    async def scenario():
        instance = make_bridge(
            FakeBrain(usage={"input_tokens": 10, "output_tokens": 5})
        )
        await instance._handle_turn(42, "fine")
        assert instance.tokens.last.outcome == "ok"
        assert "stopped" not in instance.telegram.messages[-1][1]

    asyncio.run(scenario())


# ---------------------------------------------------------------- /status all
def test_status_all_reports_every_brain_with_the_active_one_first():
    async def scenario():
        instance = make_bridge(FakeBrain())
        instance._status_by_brain = {
            "claude": instance._basic_status(),
            "codex": {"brain": "codex", "model": "gpt-5-codex", "effort": "medium"},
        }
        await instance._handle_status(42, "/status all")
        reply = instance.telegram.messages[-1][1]
        assert reply.index("CLAUDE") < reply.index("CODEX")
        assert "CLAUDE  •  ACTIVE" in reply
        assert "CODEX  •  STANDBY" in reply
        assert "gpt-5-codex" in reply
        assert "Standby brains are shown from their last cached reading" in reply

    asyncio.run(scenario())


def test_plain_status_still_reports_only_the_active_brain():
    async def scenario():
        instance = make_bridge(FakeBrain())
        await instance._handle_status(42, "/status")
        reply = instance.telegram.messages[-1][1]
        assert "CODEX" not in reply
        assert "Brain: claude" in reply

    asyncio.run(scenario())


def test_every_status_reply_carries_the_running_version():
    async def scenario():
        instance = make_bridge(FakeBrain())
        await instance._handle_status(42, "/status")
        assert bridge.display_version() in instance.telegram.messages[-1][1]
        await instance._handle_status(42, "/status all")
        assert bridge.display_version() in instance.telegram.messages[-1][1]

    asyncio.run(scenario())


# ------------------------------------------------------- console command file
def make_console_bridge(tmp_path, brain=None):
    instance = make_bridge(brain or FakeBrain())
    instance._console_status_file = tmp_path / "brain-status.json"
    instance._console_command_file = tmp_path / "console-command.json"
    instance._console_command_mtime = 0
    instance._status_by_brain = {
        name: instance._basic_status_for(name) for name in bridge.VALID_BRAINS
    }
    return instance


def test_the_console_refresh_button_takes_a_live_reading(tmp_path):
    async def scenario():
        brain = FakeBrain()
        calls = []
        original = brain.status

        async def counted(*, force_refresh=False):
            calls.append(force_refresh)
            return await original(force_refresh=force_refresh)

        brain.status = counted
        instance = make_console_bridge(tmp_path, brain)
        await instance._run_console_action("refresh_status")
        assert calls == [True]

    asyncio.run(scenario())


def test_the_console_send_button_pushes_status_to_the_owner(tmp_path):
    async def scenario():
        instance = make_console_bridge(tmp_path)
        await instance._run_console_action("send_status_all")
        assert "CODEX  •  STANDBY" in instance.telegram.messages[-1][1]

    asyncio.run(scenario())


def test_an_unknown_console_action_is_ignored_quietly(tmp_path):
    async def scenario():
        instance = make_console_bridge(tmp_path)
        await instance._run_console_action("rm -rf /")
        assert instance.telegram.messages == []

    asyncio.run(scenario())


def test_the_console_status_payload_carries_the_version(tmp_path):
    instance = make_console_bridge(tmp_path)
    instance._write_console_status()
    import json as _json

    payload = _json.loads(
        instance._console_status_file.read_text(encoding="utf-8")
    )
    assert payload["version"] == bridge.display_version()
    assert payload["active_brain"] == "claude"
    assert set(payload["brains"]) == set(bridge.VALID_BRAINS)


def test_the_command_loop_ignores_a_file_left_over_from_a_previous_run(tmp_path):
    async def scenario():
        instance = make_console_bridge(tmp_path)
        instance._console_command_file.write_text(
            '{"action": "send_status", "at": 1}', encoding="utf-8"
        )
        ran = []
        instance._run_console_action = lambda action: ran.append(action) or _noop()

        async def _noop():
            return None

        instance._shutdown_event = asyncio.Event()
        task = asyncio.ensure_future(instance._console_command_loop())
        await asyncio.sleep(0.6)
        instance._shutdown_event.set()
        await asyncio.sleep(0.5)
        task.cancel()
        # The stale file was adopted as the baseline, not replayed on startup.
        assert ran == []

    asyncio.run(scenario())


def test_the_command_loop_picks_up_a_new_button_press(tmp_path):
    async def scenario():
        instance = make_console_bridge(tmp_path)
        ran = []

        async def record(action):
            ran.append(action)

        instance._run_console_action = record
        instance._shutdown_event = asyncio.Event()
        task = asyncio.ensure_future(instance._console_command_loop())
        await asyncio.sleep(0.1)
        instance._console_command_file.write_text(
            '{"action": "refresh_all", "at": 2}', encoding="utf-8"
        )
        await asyncio.sleep(0.7)
        instance._shutdown_event.set()
        task.cancel()
        assert ran == ["refresh_all"]

    asyncio.run(scenario())


def test_a_corrupt_command_file_does_not_stop_the_loop(tmp_path):
    async def scenario():
        instance = make_console_bridge(tmp_path)
        ran = []

        async def record(action):
            ran.append(action)

        instance._run_console_action = record
        instance._shutdown_event = asyncio.Event()
        task = asyncio.ensure_future(instance._console_command_loop())
        await asyncio.sleep(0.1)
        instance._console_command_file.write_text("{not json", encoding="utf-8")
        await asyncio.sleep(0.6)
        instance._console_command_file.write_text(
            '{"action": "refresh_status", "at": 3}', encoding="utf-8"
        )
        await asyncio.sleep(0.7)
        instance._shutdown_event.set()
        task.cancel()
        assert ran == ["refresh_status"]

    asyncio.run(scenario())
