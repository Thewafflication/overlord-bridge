"""Start-up progress/splash helpers, the API-key setup window's logic, and key reload."""

import asyncio
import importlib.util
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

import bridge
from modules import startup_state

ROOT = Path(__file__).resolve().parent.parent


def load_tool(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "tools" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


splash = load_tool("overlord_splash")
setup = load_tool("overlord_setup")


@pytest.fixture(autouse=True)
def reset_state():
    startup_state._state_path = None
    yield
    startup_state._state_path = None


# --------------------------------------------------------- start-up reporting
def test_reports_are_ignored_until_begin_configures_a_path(tmp_path):
    startup_state.report("anything")
    startup_state.ready()
    startup_state.failed("x")
    assert not list(tmp_path.iterdir())


def test_state_file_tracks_stage_ready_and_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(startup_state.sys, "platform", "linux")  # no window in this test
    startup_state.begin(tmp_path)
    path = tmp_path / "run" / "startup.json"
    first = json.loads(path.read_text(encoding="utf-8"))
    assert first["state"] == "starting" and first["stage"] == "Loading libraries"
    assert first["pid"] == os.getpid()
    startup_state.report("Starting the claude brain")
    assert json.loads(path.read_text(encoding="utf-8"))["stage"] == "Starting the claude brain"
    startup_state.ready()
    assert json.loads(path.read_text(encoding="utf-8"))["state"] == "ready"
    startup_state.failed("Telegram", "no network")
    done = json.loads(path.read_text(encoding="utf-8"))
    assert (done["state"], done["detail"]) == ("failed", "no network")
    assert not list(path.parent.glob("*.tmp"))


def test_the_splash_is_launched_on_windows_with_the_right_arguments(tmp_path, monkeypatch):
    launched = []
    monkeypatch.setattr(startup_state.sys, "platform", "win32")
    monkeypatch.delenv("OVERLORD_SPLASH", raising=False)
    monkeypatch.setattr(startup_state.subprocess, "Popen", lambda argv, **kw: launched.append(argv))
    (tmp_path / "run").mkdir()
    (tmp_path / "run" / "overlord.log").write_bytes(b"old line\n")
    startup_state.begin(tmp_path)
    argv = launched[0]
    assert argv[1].endswith("overlord_splash.py")
    assert argv[argv.index("--log-offset") + 1] == str(len("old line\n"))
    assert argv[argv.index("--parent-pid") + 1] == str(os.getpid())
    # The state was reset BEFORE the window could read a previous run's "ready".
    assert json.loads((tmp_path / "run" / "startup.json").read_text())["state"] == "starting"


@pytest.mark.parametrize("value", ["0", "false", "OFF", "no"])
def test_the_splash_can_be_disabled(tmp_path, monkeypatch, value):
    launched = []
    monkeypatch.setattr(startup_state.sys, "platform", "win32")
    monkeypatch.setenv("OVERLORD_SPLASH", value)
    monkeypatch.setattr(startup_state.subprocess, "Popen", lambda argv, **kw: launched.append(argv))
    startup_state.begin(tmp_path)
    assert launched == [] and (tmp_path / "run" / "startup.json").exists()


def test_a_missing_window_never_fails_startup(tmp_path, monkeypatch):
    def broken(*a, **k):
        raise OSError("no pythonw")

    monkeypatch.setattr(startup_state.sys, "platform", "win32")
    monkeypatch.setattr(startup_state.subprocess, "Popen", broken)
    startup_state.begin(tmp_path)  # must not raise


def test_importing_the_bridge_does_not_start_progress_reporting():
    assert startup_state._state_path is None  # only `python bridge.py` configures it


# ------------------------------------------------------------ splash helpers
def test_state_reads_tolerate_missing_and_garbled_files(tmp_path):
    assert splash.read_state(tmp_path / "none.json") == {}
    (tmp_path / "bad.json").write_text("{nope", encoding="utf-8")
    assert splash.read_state(tmp_path / "bad.json") == {}
    (tmp_path / "list.json").write_text("[1]", encoding="utf-8")
    assert splash.read_state(tmp_path / "list.json") == {}


def test_log_tail_returns_only_complete_new_lines_and_survives_rotation(tmp_path):
    log = tmp_path / "overlord.log"
    log.write_bytes(b"old\nnew one\npart")
    lines, offset = splash.tail_new(log, 4)
    assert lines == ["new one"] and offset == len(b"old\nnew one\n")
    log.write_bytes("old\nnew one\npartial finished\nnaïve ✓\n".encode("utf-8"))
    lines, offset = splash.tail_new(log, offset)
    assert lines == ["partial finished", "naïve ✓"]
    log.write_bytes(b"fresh after rotation\n")  # smaller than the saved offset
    assert splash.tail_new(log, offset)[0] == ["fresh after rotation"]
    assert splash.tail_new(tmp_path / "missing.log", 5) == ([], 5)


@pytest.mark.parametrize(
    "state, elapsed, alive, expected",
    [
        ({"state": "starting", "stage": "Connecting to Telegram"}, 3, True, ("wait", "Connecting to Telegram")),
        ({}, 3, True, ("wait", "Starting…")),
        ({"state": "ready"}, 9, True, ("ready", "Online")),
        ({"state": "ready"}, 9, False, ("ready", "Online")),  # finished, then exited: still fine
        ({"state": "failed", "detail": "Telegram did not connect"}, 3, True,
         ("failed", "Telegram did not connect")),
        ({"state": "failed", "detail": "Overlord is already running on this machine."}, 3, True,
         ("benign", "Overlord is already running on this machine.")),
        ({"state": "starting", "stage": "x"}, 3, False, ("failed",
         "Overlord stopped before it finished starting. See the log above.")),
        ({"state": "starting", "stage": "x"}, 999, True, ("failed",
         "Still not online after 180s. See the log above.")),
    ],
)
def test_splash_decisions(state, elapsed, alive, expected):
    assert splash.decide(state, elapsed=elapsed, parent_alive=alive) == expected


def test_process_liveness_checks():
    assert splash.pid_alive(os.getpid()) is True
    assert splash.pid_alive(0) is True  # unknown parent: never close on that basis
    assert splash.pid_alive(2_000_000_000) is False


def test_log_levels_are_classified():
    assert splash.level_for_line("t overlord.bridge ERROR boom") == "error"
    assert splash.level_for_line("t overlord.bridge WARNING hmm") == "warning"
    assert splash.level_for_line("just text") == "plain"


# --------------------------------------------------------------- setup logic
def test_keys_are_masked_for_display():
    assert setup.mask("") == "not set"
    assert setup.mask("short") == "•••••"
    shown = setup.mask("nvapi-ABCDEFGHIJKLMNOPQRST1234")
    assert shown == "nvapi…1234" and "ABCDEF" not in shown


@pytest.mark.parametrize("key, problem", [
    ("", "Enter a key"), ("nvapi-" + "a" * 10 + " b" * 5, "spaces"), ("sk-abc" + "a" * 30, "nvapi-"),
    ("nvapi-short", "too short"), ("nvapi-" + "A1" * 20, None), ("  nvapi-" + "A1" * 20 + "\n", None),
])
def test_nvidia_key_shape_checks(key, problem):
    result = setup.check_nvidia_format(key)
    assert (result is None) if problem is None else (problem in result)


def test_current_settings_are_read_from_a_bom_prefixed_env(tmp_path):
    env = tmp_path / ".env"
    env.write_bytes("﻿# c\nOVERLORD_WORKER_NVIDIA_API_KEY='nvapi-old'\nOTHER=1\n".encode("utf-8"))
    assert setup.read_env(env, (setup.NVIDIA_KEY, setup.OPENROUTER_KEY)) == {setup.NVIDIA_KEY: "nvapi-old"}
    assert setup.read_env(tmp_path / "missing", (setup.NVIDIA_KEY,)) == {}


def test_saving_updates_only_what_was_given_and_keeps_the_rest(tmp_path):
    env = tmp_path / ".env"
    env.write_text("TELEGRAM_BOT_TOKEN=t\nOVERLORD_WORKER_NVIDIA_API_KEY=nvapi-old\n", encoding="utf-8")
    setup.save_settings(env, {setup.NVIDIA_KEY: None, setup.OPENROUTER_KEY: " sk-or-new ",
                              setup.OPENROUTER_ENABLED: "0"})
    text = env.read_text(encoding="utf-8")
    assert "OVERLORD_WORKER_NVIDIA_API_KEY=nvapi-old" in text and "TELEGRAM_BOT_TOKEN=t" in text
    assert "OVERLORD_FREE_OPENROUTER_API_KEY=sk-or-new" in text
    assert "OVERLORD_FREE_OPENROUTER_ENABLED=0" in text
    setup.save_settings(env, {setup.NVIDIA_KEY: ""})  # explicit clear
    assert "OVERLORD_WORKER_NVIDIA_API_KEY=\n" in env.read_text(encoding="utf-8")


def test_reload_request_is_an_atomic_command_file(tmp_path):
    command = tmp_path / "run" / "console-command.json"
    assert setup.request_reload(command) is True
    payload = json.loads(command.read_text(encoding="utf-8"))
    assert payload["action"] == "reload_env" and isinstance(payload["at"], int)
    assert not list(command.parent.glob("*.tmp"))
    assert setup.request_reload(None) is False
    blocker = tmp_path / "file"
    blocker.write_text("x", encoding="utf-8")
    assert setup.request_reload(blocker / "sub" / "cmd.json") is False


@pytest.mark.parametrize("status, ok, text", [
    (200, True, "accepted"), (401, False, "rejected"), (403, False, "rejected"),
    (429, True, "rate limiting"), (500, False, "HTTP 500"),
])
def test_key_probe_interprets_provider_answers(monkeypatch, status, ok, text):
    seen = []
    monkeypatch.setattr(setup, "_get", lambda url, key, timeout: seen.append((url, key)) or (status, ""))
    result_ok, message = setup.probe_key(setup.NVIDIA_MODELS_URL, " nvapi-x ", "NVIDIA")
    assert result_ok is ok and text in message
    assert seen == [(setup.NVIDIA_MODELS_URL, "nvapi-x")]


def test_key_probe_reports_unreachable_providers(monkeypatch):
    def down(url, key, timeout):
        raise OSError("name resolution failed")

    monkeypatch.setattr(setup, "_get", down)
    ok, message = setup.probe_key(setup.OPENROUTER_KEY_URL, "k", "OpenRouter")
    assert ok is False and "Could not reach OpenRouter" in message


# ------------------------------------------------------ tray + live reload
def test_tray_opens_the_setup_window_with_the_command_file(monkeypatch, tmp_path):
    from modules.windows_tray import WindowsTray

    launched = []
    monkeypatch.setattr("modules.windows_tray.subprocess.Popen", lambda argv, **kw: launched.append(argv))
    tray = WindowsTray(lambda: None, command_path=tmp_path / "cmd.json")
    assert tray.launch_setup() is True
    argv = launched[0]
    assert argv[1].endswith("overlord_setup.py")
    assert argv[argv.index("--command") + 1] == str(tmp_path / "cmd.json")
    assert argv[argv.index("--env") + 1].endswith(".env")

    def broken(*a, **k):
        raise OSError("nope")

    monkeypatch.setattr("modules.windows_tray.subprocess.Popen", broken)
    assert tray.launch_setup() is False


class FakeTelegram:
    def __init__(self):
        self.messages = []

    def send(self, chat_id, text):
        self.messages.append(text)


def make_bridge(tmp_path, brain_name="claude"):
    instance = bridge.Bridge.__new__(bridge.Bridge)
    instance.brain = SimpleNamespace(name=brain_name, model="m", effort=None, session_id=None)
    instance.telegram = FakeTelegram()
    instance.gate = None
    instance._brain_lock = asyncio.Lock()
    instance._status_by_brain, instance._status_cache = {}, {}
    instance._console_status_file = None
    return instance


def test_reload_applies_the_file_and_leaves_other_settings_alone(tmp_path, monkeypatch):
    monkeypatch.setattr(bridge, "BASE_DIR", tmp_path)
    monkeypatch.setattr(bridge, "OWNER", 42)
    monkeypatch.setenv("OVERLORD_WORKER_NVIDIA_API_KEY", "old")
    monkeypatch.setenv("OVERLORD_FREE_NVIDIA_RPM", "7")  # process env, not in the file
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "must-not-change")
    (tmp_path / ".env").write_text(
        "TELEGRAM_BOT_TOKEN=attacker\nOVERLORD_WORKER_NVIDIA_API_KEY=nvapi-new\n"
        "OVERLORD_FREE_OPENROUTER_ENABLED=0\nOVERLORD_BRAIN=free\n", encoding="utf-8")
    instance = make_bridge(tmp_path)
    asyncio.run(instance._reload_env())
    assert os.environ["OVERLORD_WORKER_NVIDIA_API_KEY"] == "nvapi-new"
    assert os.environ["OVERLORD_FREE_OPENROUTER_ENABLED"] == "0"
    assert os.environ["OVERLORD_FREE_NVIDIA_RPM"] == "7"
    assert os.environ["TELEGRAM_BOT_TOKEN"] == "must-not-change"  # not a reloadable setting
    assert os.environ.get("OVERLORD_BRAIN") != "free"
    assert "reloaded" in instance.telegram.messages[-1]
    os.environ.pop("OVERLORD_FREE_OPENROUTER_ENABLED", None)


def test_reload_rebuilds_the_active_free_brain_with_the_new_keys(tmp_path, monkeypatch):
    monkeypatch.setattr(bridge, "BASE_DIR", tmp_path)
    monkeypatch.setattr(bridge, "OWNER", 42)
    monkeypatch.setenv("OVERLORD_FREE_MODELS", "nvidia:gpt-oss")
    monkeypatch.delenv("OVERLORD_WORKER_NVIDIA_API_KEY", raising=False)
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
    monkeypatch.setenv("OVERLORD_FREE_OPENROUTER_ENABLED", "0")
    monkeypatch.setattr(bridge, "session_file_for", lambda name: tmp_path / f"pin-{name}")
    monkeypatch.setattr(bridge.Bridge, "_read_cached_usage", staticmethod(lambda name: None))
    instance = make_bridge(tmp_path, "free")
    instance.brain = bridge.build_brain(None, "free")
    assert instance.brain.models == []  # no key yet
    (tmp_path / ".env").write_text("OVERLORD_WORKER_NVIDIA_API_KEY=nvapi-" + "x" * 30 + "\n",
                                   encoding="utf-8")
    old = instance.brain
    asyncio.run(instance._reload_env())
    assert instance.brain is not old and [m.model for m in instance.brain.models] == ["openai/gpt-oss-20b"]
    assert "Keys: nvidia ✓" in "\n".join(instance._status_by_brain["free"]["usage_summary"])
    os.environ.pop("OVERLORD_WORKER_NVIDIA_API_KEY", None)


def test_reload_is_available_as_a_console_action(tmp_path, monkeypatch):
    instance = make_bridge(tmp_path)
    called = []

    async def fake_reload():
        called.append(True)

    monkeypatch.setattr(instance, "_reload_env", fake_reload)
    asyncio.run(instance._run_console_action("reload_env"))
    assert called == [True]


def test_console_shows_a_card_for_each_brain():
    console = load_tool("overlord_console")
    text = console.format_brain_summary("free", {"model": "openrouter:x", "usage_summary": ["Keys: nvidia ✓"]}, "free")
    assert "FREE  •  ACTIVE" in text and "Keys: nvidia ✓" in text
