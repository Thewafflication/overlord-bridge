"""Bridge helpers: worker-report delivery, console status/commands, cached usage, resets."""

import asyncio
import json
import os
from types import SimpleNamespace

import pytest

import bridge
from modules.conversation_history import SharedConversationHistory
from modules.token_meter import TokenLedger, normalize_usage


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
    model = "opus"
    effort = None
    session_id = "sess"
    supports_effort = True

    def __init__(self):
        self.events = []
        self.reset_calls = 0
        self.compact_error = None
        self.last_turn_usage = None
        self.last_turn_cost_usd = None
        self.last_turn_outcome = "ok"
        self.record_result = True
        self.visible_result = True

    async def record_event(self, text, metadata=None):
        self.events.append(("thread", text))
        return self.record_result

    async def record_visible_event(self, text, metadata=None):
        self.events.append(("visible", text))
        return self.visible_result

    async def reset(self):
        self.reset_calls += 1

    async def compact(self, *, timeout=120):
        self.events.append(("compact", None))
        return self.compact_error

    async def interrupt_active_turn(self):
        return False

    async def status(self, *, force_refresh=False):
        return {"brain": self.name, "model": self.model, "session_id": self.session_id}


def make_bridge(tmp_path, brain=None):
    instance = bridge.Bridge.__new__(bridge.Bridge)
    instance.brain = brain or FakeBrain()
    instance.brain_name = instance.brain.name
    instance.telegram = FakeTelegram()
    instance.gate = SimpleNamespace(
        pending={}, choice_pending={}, revoke_grants=lambda grant=None: 0,
        format_grants=lambda: "grants!",
    )
    instance._brain_lock = asyncio.Lock()
    instance._pending_handoff = None
    instance._status_timeout = 0.05
    instance.tokens = TokenLedger()
    instance._status_cache = {}
    instance._status_by_brain = {}
    instance._conversation_history = SharedConversationHistory(path=tmp_path / "conv.json")
    instance._console_status_file = tmp_path / "run" / "status.json"
    instance._console_command_file = tmp_path / "run" / "command.json"
    instance._console_command_mtime = 0
    instance._shutdown_event = asyncio.Event()
    instance._thread_report_unsupported_logged = False
    instance._visible_report_unsupported_logged = False
    instance.tray = SimpleNamespace(set_brain=lambda name: None)
    return instance


def run(coro):
    return asyncio.run(coro)


REPORT = {
    "name": "Chorus", "folder": "/home/ben/Projects/app", "brain": "claude",
    "status": "finished", "session": "s1", "exit_code": 0, "duration_seconds": 12.5,
    "result_tail": "  all green  ",
}


# ------------------------------------------------------- report formatting
def test_thread_report_lists_known_fields_and_marks_itself_as_bridge_text():
    text = bridge.format_worker_thread_report(REPORT)
    assert text.startswith("[BRIDGE/SYSTEM WORKER REPORT]")
    assert "not Ben's message" in text
    for line in ("name: Chorus", "status: finished", "exit_code: 0", "duration_seconds: 12.5"):
        assert line in text
    assert "result_tail:\nall green" in text
    assert "real_codex_session_id" not in text  # absent fields are omitted
    assert "result_tail" not in bridge.format_worker_thread_report({"name": "x"})


def test_inline_report_is_always_one_line_whatever_the_dispatch_file_said():
    hostile = {"name": "Evil\nName", "status": "failed\r\nnow", "folder": "/a\n/b",
               "duration_seconds": 3}
    text = bridge.format_worker_inline_report(hostile)
    assert "\n" not in text and "\r" not in text
    assert "Evil Name: status=failed now, 3s, folder=/a /b" in text
    assert bridge.format_worker_inline_report({}) == (
        "[worker report] worker: status=unknown (full report: worker_reports/latest/worker.json)"
    )


# --------------------------------------------------- worker-report delivery
def test_report_reaches_the_thread_feed_and_terminal_when_enabled(tmp_path, monkeypatch):
    instance = make_bridge(tmp_path)
    calls = []
    monkeypatch.setattr(bridge, "WORKER_REPORT_TO_THREAD", True)
    monkeypatch.setattr(bridge, "WORKER_REPORT_VISIBLE_TURN", True)
    monkeypatch.setattr(bridge, "WORKER_REPORT_CLI_FEED", True)
    monkeypatch.setattr(bridge, "WORKER_REPORT_TERMINAL_INJECT", True)
    monkeypatch.setattr(bridge, "WORKER_REPORT_CLI_FEED_PATH", tmp_path / "feed.log")
    monkeypatch.setattr(bridge, "WORKER_REPORT_TMUX_SESSION", "overlord-claude")
    monkeypatch.setattr(bridge.cli_notify, "tmux_session_exists", lambda s: True)
    monkeypatch.setattr(bridge.cli_notify, "pane_input_is_idle", lambda s: True)
    monkeypatch.setattr(bridge.cli_notify, "inject_turn", lambda s, t: calls.append((s, t)) or True)
    run(instance._handle_worker_report(REPORT))
    assert [kind for kind, _ in instance.brain.events] == ["thread", "visible"]
    assert "Chorus" in (tmp_path / "feed.log").read_text(encoding="utf-8")
    assert calls and calls[0][0] == "overlord-claude" and "\n" not in calls[0][1]


def test_report_delivery_is_skipped_entirely_when_every_channel_is_off(tmp_path, monkeypatch):
    instance = make_bridge(tmp_path)
    for flag in ("WORKER_REPORT_TO_THREAD", "WORKER_REPORT_VISIBLE_TURN",
                 "WORKER_REPORT_CLI_FEED", "WORKER_REPORT_TERMINAL_INJECT"):
        monkeypatch.setattr(bridge, flag, False)
    run(instance._handle_worker_report(REPORT))
    assert instance.brain.events == []


def test_busy_or_missing_terminals_are_never_typed_into(tmp_path, monkeypatch):
    instance = make_bridge(tmp_path)
    typed = []
    monkeypatch.setattr(bridge, "WORKER_REPORT_TO_THREAD", False)
    monkeypatch.setattr(bridge, "WORKER_REPORT_VISIBLE_TURN", False)
    monkeypatch.setattr(bridge, "WORKER_REPORT_CLI_FEED", False)
    monkeypatch.setattr(bridge, "WORKER_REPORT_TERMINAL_INJECT", True)
    monkeypatch.setattr(bridge.cli_notify, "inject_turn", lambda s, t: typed.append(t) or True)
    monkeypatch.setattr(bridge.cli_notify, "tmux_session_exists", lambda s: False)
    run(instance._handle_worker_report(REPORT))
    monkeypatch.setattr(bridge.cli_notify, "tmux_session_exists", lambda s: True)
    for idle in (False, None):
        monkeypatch.setattr(bridge.cli_notify, "pane_input_is_idle", lambda s, idle=idle: idle)
        run(instance._handle_worker_report(REPORT))
    assert typed == []


def test_an_unwritable_feed_does_not_break_report_delivery(tmp_path, monkeypatch):
    instance = make_bridge(tmp_path)
    monkeypatch.setattr(bridge, "WORKER_REPORT_TO_THREAD", False)
    monkeypatch.setattr(bridge, "WORKER_REPORT_VISIBLE_TURN", False)
    monkeypatch.setattr(bridge, "WORKER_REPORT_CLI_FEED", True)
    monkeypatch.setattr(bridge, "WORKER_REPORT_TERMINAL_INJECT", False)
    blocker = tmp_path / "blocker"
    blocker.write_text("file", encoding="utf-8")
    monkeypatch.setattr(bridge, "WORKER_REPORT_CLI_FEED_PATH", blocker / "feed.log")
    run(instance._handle_worker_report(REPORT))  # must not raise


def test_brain_failures_while_recording_reports_are_contained(tmp_path, monkeypatch):
    instance = make_bridge(tmp_path)

    async def boom(text, metadata=None):
        raise RuntimeError("thread closed")

    instance.brain.record_event = boom
    monkeypatch.setattr(bridge, "WORKER_REPORT_TO_THREAD", True)
    monkeypatch.setattr(bridge, "WORKER_REPORT_VISIBLE_TURN", False)
    monkeypatch.setattr(bridge, "WORKER_REPORT_CLI_FEED", False)
    monkeypatch.setattr(bridge, "WORKER_REPORT_TERMINAL_INJECT", False)
    run(instance._handle_worker_report(REPORT))
    assert instance._thread_report_unsupported_logged is True


# ----------------------------------------------------------- cached usage
def test_claude_cached_usage_is_read_from_the_hook_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    cache = tmp_path / ".cache" / "near-limit-handoff" / "usage.json"
    cache.parent.mkdir(parents=True)
    cache.write_text(json.dumps({
        "five_hour": {"utilization": "33.33", "resets_at": "soon"},
        "seven_day": {"utilization": 99.99},
    }), encoding="utf-8")
    usage = bridge.Bridge._read_cached_usage("claude")
    assert usage["session"] == {"used": 33.3, "gas": 66.7, "resets_at": "soon", "reset_passed": False}
    assert usage["weekly"]["gas"] == 0.0 and usage["source"] == "cache"


@pytest.mark.parametrize("content", ["not json", "[]", "{}", '{"five_hour": {"utilization": "x"}}'])
def test_unusable_claude_cache_reads_as_missing(tmp_path, monkeypatch, content):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    cache = tmp_path / ".cache" / "near-limit-handoff" / "usage.json"
    cache.parent.mkdir(parents=True)
    cache.write_text(content, encoding="utf-8")
    assert bridge.Bridge._read_cached_usage("claude") is None


def test_codex_cached_usage_and_unknown_brains(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    assert bridge.Bridge._read_cached_usage("codex") is None
    cache = tmp_path / ".cache" / "overlord" / "codex_usage.json"
    cache.parent.mkdir(parents=True)
    cache.write_text(json.dumps({"session": {"used": 1, "gas": 99}}), encoding="utf-8")
    assert bridge.Bridge._read_cached_usage("codex") == {"session": {"used": 1, "gas": 99}}
    cache.write_text("[1]", encoding="utf-8")
    assert bridge.Bridge._read_cached_usage("codex") is None
    assert bridge.Bridge._read_cached_usage("gemini") is None


def test_basic_status_for_a_standby_brain_reports_saved_sessions(tmp_path, monkeypatch):
    instance = make_bridge(tmp_path)
    monkeypatch.setattr(bridge, "session_file_for", lambda name: tmp_path / f"pin-{name}")
    monkeypatch.setattr(bridge.Bridge, "_read_cached_usage", staticmethod(lambda name: None))
    assert instance._basic_status_for("codex")["session_id"] is None
    (tmp_path / "pin-codex").write_text("thread", encoding="utf-8")
    standby = instance._basic_status_for("codex")
    assert standby["session_id"] == "saved" and standby["brain"] == "codex"
    active = instance._basic_status_for("claude")
    assert active["model"] == "opus" and active["session_id"] == "sess"


# ------------------------------------------------------ console integration
def test_console_status_file_is_written_atomically_with_turn_state(tmp_path):
    instance = make_bridge(tmp_path)
    instance._status_by_brain = {"claude": {"brain": "claude", "model": "opus"},
                                 "codex": {"brain": "codex"}}
    instance._write_console_status()
    data = json.loads(instance._console_status_file.read_text(encoding="utf-8"))
    assert data["active_brain"] == "claude"
    assert data["brains"]["claude"]["turn_state"] == "idle"
    assert "turn_state" not in data["brains"]["codex"]
    assert data["version"].startswith("v")
    assert not list(instance._console_status_file.parent.glob("*.tmp"))


def test_console_status_failures_are_not_fatal(tmp_path):
    instance = make_bridge(tmp_path)
    blocker = tmp_path / "blocker"
    blocker.write_text("file", encoding="utf-8")
    instance._console_status_file = blocker / "status.json"
    instance._write_console_status()  # must not raise
    instance._console_status_file = None
    instance._write_console_status()


def test_console_buttons_trigger_read_only_actions(tmp_path, monkeypatch):
    async def scenario():
        instance = make_bridge(tmp_path)
        refreshed = []

        async def refresh(brain, *, force=False):
            refreshed.append(force)

        monkeypatch.setattr(instance, "_refresh_status", refresh)
        await instance._run_console_action("refresh_status")
        await instance._run_console_action("refresh_all")
        await instance._run_console_action("send_status")
        await instance._run_console_action("send_status_all")
        await instance._run_console_action("format_everything")  # unknown: ignored
        assert refreshed[:2] == [True, True]
        assert any("Overlord status" in text for _, text in instance.telegram.messages)
        assert instance.brain.reset_calls == 0

    run(scenario())


def test_console_command_loop_acts_once_per_file_change_and_survives_bad_files(tmp_path, monkeypatch):
    async def scenario():
        instance = make_bridge(tmp_path)
        actions = []

        async def act(action):
            actions.append(action)
            if action == "explode":
                raise RuntimeError("boom")

        monkeypatch.setattr(instance, "_run_console_action", act)
        real_sleep = asyncio.sleep

        async def fast_sleep(delay):
            await real_sleep(0.01)

        monkeypatch.setattr(bridge.asyncio, "sleep", fast_sleep)
        instance._console_command_file.parent.mkdir(parents=True, exist_ok=True)
        instance._console_command_file.write_text('{"action": "stale"}', encoding="utf-8")
        loop = asyncio.create_task(instance._console_command_loop())
        await real_sleep(0.05)
        assert actions == []  # whatever was on disk before startup is ignored

        def publish(text, mtime):
            instance._console_command_file.write_text(text, encoding="utf-8")
            os.utime(instance._console_command_file, ns=(mtime, mtime))

        base = instance._console_command_file.stat().st_mtime_ns
        publish("{broken", base + 1_000_000_000)
        publish('{"action": " Refresh_Status "}', base + 2_000_000_000)
        await real_sleep(0.1)
        publish('{"action": "explode"}', base + 3_000_000_000)
        await real_sleep(0.1)
        publish("null", base + 4_000_000_000)
        await real_sleep(0.1)
        publish('{"action": "send_status"}', base + 5_000_000_000)
        await real_sleep(0.1)
        instance._shutdown_event.set()
        await asyncio.wait_for(loop, 2)
        assert actions == ["refresh_status", "explode", "", "send_status"]

    run(scenario())


# ------------------------------------------------------------ session reset
def test_new_session_clears_context_tokens_and_grants(tmp_path):
    async def scenario():
        instance = make_bridge(tmp_path)
        revoked = []
        instance.gate.revoke_grants = lambda grant=None: revoked.append(grant) or 0
        instance._conversation_history.append_exchange("q", "a")
        instance.tokens.record(normalize_usage({"input_tokens": 5, "output_tokens": 1}))
        instance._pending_handoff = SimpleNamespace(text="old")
        await instance._reset_session(42)
        assert instance.brain.reset_calls == 1
        assert instance._conversation_history.handoff_for("claude") is None
        assert instance.tokens.totals.prompts == 0 and instance._pending_handoff is None
        assert revoked == [None]
        assert "Fresh session" in instance.telegram.messages[-1][1]

    run(scenario())


def test_failed_reset_is_reported_and_leaves_state_alone(tmp_path):
    async def scenario():
        instance = make_bridge(tmp_path)

        async def broken():
            raise RuntimeError("cannot delete pin")

        instance.brain.reset = broken
        instance.tokens.record(normalize_usage({"input_tokens": 5, "output_tokens": 1}))
        await instance._reset_session(42)
        assert "Could not reset session: cannot delete pin" in instance.telegram.messages[-1][1]
        assert instance.tokens.totals.prompts == 1

    run(scenario())


# ----------------------------------------------------------- /permissions
@pytest.mark.parametrize(
    "text, expected",
    [
        ("/permissions", "grants!"),
        ("/permissions revoke all", "Revoked 3 permission grants."),
        ("/permissions revoke abc123", "Revoked 3 permission grants."),
        ("/permissions revoke", "Usage: /permissions [revoke <id|all>]"),
        ("/permissions nonsense x", "Usage: /permissions [revoke <id|all>]"),
    ],
)
def test_permissions_command(tmp_path, text, expected):
    instance = make_bridge(tmp_path)
    seen = []
    instance.gate.revoke_grants = lambda grant=None: seen.append(grant) or 3
    instance._handle_permissions(42, text)
    assert instance.telegram.messages[-1][1] == expected
    if "revoke all" in text:
        assert seen == [None]
    elif "revoke abc123" in text:
        assert seen == ["abc123"]


# ---------------------------------------------------------------- /compact
def test_compaction_reports_success_failure_and_books_tokens(tmp_path):
    async def scenario():
        instance = make_bridge(tmp_path)
        instance.brain.last_turn_usage = {"input_tokens": 100, "output_tokens": 20}
        instance._start_compaction(42)
        await instance._active_turn_task
        texts = [t for _, t in instance.telegram.messages]
        assert "Compacting the conversation…" in texts
        assert any("compacted" in t for t in texts)
        assert instance.tokens.totals.prompts == 1 and instance.tokens.last.prompt_preview == "/compact"
        instance.brain.compact_error = "Codex has an active operation"
        instance._start_compaction(42)
        await instance._active_turn_task
        assert any(
            text.startswith("⚠️ Codex has an active operation")
            for _, text in instance.telegram.messages
        )

    run(scenario())


def test_compaction_is_refused_while_busy_and_without_a_checkpoint(tmp_path):
    async def scenario():
        instance = make_bridge(tmp_path)
        instance.gate.pending = {"r": object()}
        instance._start_compaction(42)
        assert "Finish or stop" in instance.telegram.messages[-1][1]
        assert instance._active_turn_task is None
        instance.gate.pending = {}
        instance._conversation_history = SharedConversationHistory()  # cannot checkpoint
        instance._start_compaction(42)
        await instance._active_turn_task
        assert "checkpoint save failed" in instance.telegram.messages[-1][1]
        assert ("compact", None) not in instance.brain.events

    run(scenario())


# ---------------------------------------------------------------- /context
def test_context_reports_window_snapshot_and_compaction_state(tmp_path):
    instance = make_bridge(tmp_path)
    instance._status_cache = {"tokens": {"modelContextWindow": 200_000}}
    instance.brain.context_snapshot = {
        "session_id": "sess", "model": "opus", "used": 50_000, "maximum": 200_000,
        "percentage": 25.0, "observed_at": "2026-07-01T00:00:00+00:00",
    }
    instance.brain.compaction_status = "completed"
    instance._handle_context(42)
    text = instance.telegram.messages[-1][1]
    assert "Model context window: 200,000 tokens" in text
    assert "Last native snapshot: 50,000/200,000 tokens (25.0%)" in text
    assert "Native compaction: completed" in text
    instance.brain.context_snapshot["session_id"] = "another"  # belongs to a different session
    instance._handle_context(42)
    assert "Last native snapshot" not in instance.telegram.messages[-1][1]


# --------------------------------------------------------------- start-up
def test_shared_instructions_prefer_the_configured_file_then_agents_md(tmp_path, monkeypatch):
    custom = tmp_path / "custom.md"
    custom.write_text("  custom — rules  \n", encoding="utf-8")
    monkeypatch.setattr(bridge, "INSTRUCTIONS_FILE", str(custom))
    assert bridge.load_shared_instructions() == "custom — rules"
    custom.write_text("   \n", encoding="utf-8")  # blank: fall through to the default file
    monkeypatch.setattr(bridge, "BASE_DIR", tmp_path)
    (tmp_path / "AGENTS.md").write_text("default rules", encoding="utf-8")
    assert bridge.load_shared_instructions() == "default rules"
    (tmp_path / "AGENTS.md").unlink()
    assert bridge.load_shared_instructions() == ""


def test_session_files_are_per_brain_and_unknown_brains_map_to_claude():
    assert bridge.session_file_for("codex").name == ".session.codex"
    assert bridge.session_file_for("claude").name == ".session.claude"
    assert bridge.session_file_for("gemini").name == ".session.claude"


def test_env_path_resolves_relative_to_the_install_and_expands_home(monkeypatch, tmp_path):
    monkeypatch.setenv("OVL_PATH", "sub/dir")
    assert bridge.env_path("OVL_PATH", tmp_path) == bridge.BASE_DIR / "sub" / "dir"
    monkeypatch.setenv("OVL_PATH", str(tmp_path))
    assert bridge.env_path("OVL_PATH", bridge.BASE_DIR) == tmp_path
    monkeypatch.delenv("OVL_PATH")
    assert bridge.env_path("OVL_PATH", tmp_path) == tmp_path
    monkeypatch.setenv("OVL_PATH", "~/x")
    assert bridge.env_path("OVL_PATH", tmp_path).is_absolute()


def test_build_brain_selects_the_engine_and_falls_back_to_claude(monkeypatch):
    gate = SimpleNamespace()
    monkeypatch.setattr(bridge, "load_shared_instructions", lambda: "")
    claude = bridge.build_brain(gate, "claude")
    assert claude.name == "claude" and "Telegram" in claude.developer_instructions
    assert bridge.build_brain(gate, "mystery").name == "claude"
    assert bridge.build_brain(gate, " CODEX ").name == "codex"


def test_shared_instructions_survive_an_ansi_saved_file_and_a_bom(tmp_path, monkeypatch):
    path = tmp_path / "rules.md"
    monkeypatch.setattr(bridge, "INSTRUCTIONS_FILE", str(path))
    path.write_bytes(b"Caf\xe9 rules")  # cp1252, invalid as UTF-8
    assert bridge.load_shared_instructions() == "Café rules"
    path.write_bytes("\ufeffUTF-8 rules — fine".encode("utf-8"))
    assert bridge.load_shared_instructions() == "UTF-8 rules — fine"


def test_cached_claude_windows_that_already_reset_are_not_reported_as_full(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    cache = tmp_path / ".cache" / "near-limit-handoff" / "usage.json"
    cache.parent.mkdir(parents=True)
    cache.write_text(json.dumps({
        "five_hour": {"utilization": 100.0, "resets_at": "2026-09-02T20:00:00+00:00"},
        "seven_day": {"utilization": 13.0, "resets_at": "2026-09-08T16:00:00+00:00"},
    }), encoding="utf-8")
    usage = bridge.Bridge._read_cached_usage("claude")
    assert usage["session"]["used"] == 0.0 and usage["session"]["reset_passed"] is True
    assert usage["weekly"]["gas"] == 100.0
