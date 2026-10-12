"""Free-model chat: pacing, fallback, admission, history, and bridge wiring."""

import asyncio
import json

import pytest

import bridge
from modules import free_brain
from modules.commands import VALID_BRAINS, format_status
from modules.free_brain import (
    FreeBrain,
    ModelSpec,
    UsageLimiter,
    _parse_duration,
    format_wait,
    parse_models,
)

NV = ModelSpec("nvidia", "openai/gpt-oss-120b")
NV2 = ModelSpec("nvidia", "meta/llama-3.3-70b-instruct")
OR = ModelSpec("openrouter", "vendor/model:free")


class Clock:
    def __init__(self, now=1_800_000_000.0):
        self.now = now

    def __call__(self):
        return self.now


def run(coro):
    return asyncio.run(coro)


# ------------------------------------------------------------------ parsing
def test_models_parse_with_providers_aliases_and_dedup():
    specs = parse_models("gpt-oss, nvidia:llama, openrouter:vendor/model:free, nvidia:gpt-oss, ,")
    assert specs == [NV, NV2, OR]
    assert parse_models("") == [] and parse_models("nvidia:") == []


@pytest.mark.parametrize("value, expected", [
    ("30", 30.0), ("1.5", 1.5), ("45s", 45.0), ("2m", 120.0), ("1m30s", 90.0), ("1h", 3600.0),
    (None, None), ("", None), ("soon", None), ("-5", 0.0),
])
def test_durations(value, expected):
    assert _parse_duration(value) == expected


def test_wait_formatting():
    assert [format_wait(s) for s in (0, 45, 89, 120, 4000, 7200)] == ["0s", "45s", "89s", "2m", "66m", "2h"]


# ------------------------------------------------------------------ limiter
def test_per_minute_window_blocks_then_frees():
    clock = Clock()
    limiter = UsageLimiter(None, {"nvidia": (2, 0)}, clock)
    assert limiter.availability(NV)[0] == 0
    limiter.record(NV)
    clock.now += 10
    limiter.record(NV)
    wait, reason = limiter.availability(NV)
    assert 49 < wait <= 50 and "2/min" in reason
    clock.now += 51
    assert limiter.availability(NV)[0] == 0
    assert limiter.availability(OR)[0] == 0  # other providers have their own budget


def test_daily_cap_holds_until_utc_midnight_then_resets():
    clock = Clock(1_800_000_000.0)  # 2027-01-15 08:00 UTC
    limiter = UsageLimiter(None, {"openrouter": (0, 2)}, clock)
    limiter.record(OR)
    limiter.record(OR)
    wait, reason = limiter.availability(OR)
    assert "2/day" in reason and 0 < wait <= 86_400
    clock.now += wait + 1
    assert limiter.availability(OR)[0] == 0 and limiter.daily_count("openrouter") == 0


def test_cooldowns_apply_per_model_or_per_provider():
    clock = Clock()
    limiter = UsageLimiter(None, {}, clock)
    limiter.cool_down(NV.key, 30)
    assert limiter.availability(NV)[0] == 30 and limiter.availability(NV2)[0] == 0
    limiter.cool_down("nvidia", 100)
    assert limiter.availability(NV2)[0] == 100
    assert limiter.cooling(NV2) == 100
    clock.now += 101
    assert limiter.availability(NV)[0] == 0


def test_usage_survives_a_restart_and_garbage_state_is_ignored(tmp_path):
    clock = Clock()
    path = tmp_path / "usage.json"
    first = UsageLimiter(path, {"nvidia": (5, 3)}, clock)
    first.record(NV)
    first.cool_down(NV2.key, 120)
    second = UsageLimiter(path, {"nvidia": (5, 3)}, clock)
    assert second.snapshot("nvidia") == {"minute_used": 1, "minute_cap": 5, "day_used": 1, "day_cap": 3}
    assert second.availability(NV2)[0] > 100
    path.write_text(json.dumps({"recent": {"nvidia": ["x", True, -5]}, "daily": {"nvidia": {"count": -1}},
                                "cooldown": {"k": "never"}}), encoding="utf-8")
    third = UsageLimiter(path, {"nvidia": (5, 3)}, clock)
    assert third.snapshot("nvidia")["minute_used"] == 0 and third.daily_count("nvidia") == 0
    path.write_text("not json", encoding="utf-8")
    UsageLimiter(path, {}, clock)  # must not raise


# ------------------------------------------------------------------- brain
def reply(text, usage=None):
    body = {"choices": [{"message": {"content": text}}]}
    if usage:
        body["usage"] = usage
    return 200, {}, body


def make(tmp_path, monkeypatch, responses, *, models=(NV, NV2), keys=None, clock=None, **kwargs):
    calls = []
    queue = list(responses)

    async def fake_post(url, payload, api_key, timeout):
        calls.append((url, payload, api_key))
        item = queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    sleeps = []

    async def fake_sleep(seconds):
        sleeps.append(seconds)

    monkeypatch.setattr(free_brain, "_post", fake_post)
    limiter = UsageLimiter(tmp_path / "usage.json", kwargs.pop("limits", {"nvidia": (20, 0)}),
                           clock or Clock())
    brain = FreeBrain(
        session_file=tmp_path / ".session.free", models=list(models),
        keys=keys or {"nvidia": "nv-key", "openrouter": "or-key"}, limiter=limiter,
        sleep=fake_sleep, **kwargs,
    )
    brain.calls, brain.sleeps = calls, sleeps
    return brain


async def ask(brain, text="hi"):
    return [chunk async for chunk in brain.query(text)]


def test_a_chat_turn_sends_history_and_records_usage(tmp_path, monkeypatch):
    brain = make(tmp_path, monkeypatch, [reply("Hello!", {"prompt_tokens": 9, "completion_tokens": 3}),
                                         reply("Second")])
    assert run(ask(brain, "hi")) == ["Hello!"]
    assert brain.last_turn_usage == {"prompt_tokens": 9, "completion_tokens": 3}
    assert run(ask(brain, "again")) == ["Second"]
    url, payload, key = brain.calls[1]
    assert url == "https://integrate.api.nvidia.com/v1/chat/completions" and key == "nv-key"
    roles = [m["role"] for m in payload["messages"]]
    assert roles == ["system", "user", "assistant", "user"]
    assert payload["messages"][-1]["content"] == "again" and payload["model"] == NV.model
    assert brain.session_id == "chat"
    assert brain.limiter.snapshot("nvidia")["minute_used"] == 2


def test_history_is_persisted_trimmed_and_reset(tmp_path, monkeypatch):
    brain = make(tmp_path, monkeypatch, [reply("a" * 1500)] * 4, history_chars=2000)
    for _ in range(4):
        run(ask(brain, "q" * 600))
    assert sum(len(m["content"]) for m in brain._history) <= 2000 + 2100
    assert brain._history[0]["role"] == "user" and len(brain._history) % 2 == 0
    restored = make(tmp_path, monkeypatch, [])
    run(restored.connect())
    assert restored._history == brain._history
    run(restored.reset())
    assert restored.session_id is None and not (tmp_path / ".session.free").exists()
    (tmp_path / ".session.free").write_text('[{"role": "system", "content": "x"}, 5, {"role": "user"}]',
                                            encoding="utf-8")
    run(restored.connect())
    assert restored._history == []


def test_a_rate_limited_model_falls_through_to_the_next_and_cools_down(tmp_path, monkeypatch):
    brain = make(tmp_path, monkeypatch, [(429, {"retry-after": "90"}, {}), reply("from llama"),
                                         reply("second turn")])
    out = run(ask(brain))
    assert out[0].startswith("from llama") and f"answered by {NV2.key}" in out[0]
    assert "rate limited, retry in 1m" in out[0]
    assert brain.limiter.availability(NV)[0] > 85
    # The next turn skips the cooling model without spending a request on it.
    run(ask(brain))
    assert [c[1]["model"] for c in brain.calls] == [NV.model, NV2.model, NV2.model]


def test_every_model_spent_reports_when_one_returns(tmp_path, monkeypatch):
    clock = Clock()
    brain = make(tmp_path, monkeypatch, [], limits={"nvidia": (1, 0)}, clock=clock)
    brain.limiter.record(NV)  # the shared provider budget is already used up
    out = run(ask(brain))
    assert len(out) == 1 and out[0].startswith("⚠️ No free model could answer")
    assert "1/min limit" in out[0] and "Next model free in about" in out[0]
    assert brain.last_turn_outcome == "error" and brain.calls == [] and brain._history == []


def test_short_waits_are_slept_through_instead_of_skipped(tmp_path, monkeypatch):
    clock = Clock()
    brain = make(tmp_path, monkeypatch, [reply("ok")], limits={"nvidia": (1, 0)}, clock=clock, max_wait=8)
    brain.limiter.record(NV)
    clock.now += 55  # five seconds of the window left
    assert run(ask(brain)) == ["ok"] and 4 < brain.sleeps[0] <= 5


@pytest.mark.parametrize("status, text", [(500, "provider error"), (401, "rejected the API key"),
                                          (404, "HTTP 404"), (200, "empty reply")])
def test_failures_move_on_and_are_named(tmp_path, monkeypatch, status, text):
    first = (status, {}, {"error": {"message": "nope"}}) if status != 200 else (200, {}, {"choices": []})
    brain = make(tmp_path, monkeypatch, [first, reply("rescued")])
    out = run(ask(brain))[0]
    if status == 401:  # an auth failure poisons the whole provider
        assert out.startswith("⚠️ No free model") or "rescued" not in out
    else:
        assert "rescued" in out
    assert text in out


def test_network_errors_cool_the_model_and_try_the_next(tmp_path, monkeypatch):
    brain = make(tmp_path, monkeypatch, [OSError("connection reset"), reply("fine")])
    out = run(ask(brain))[0]
    assert "fine" in out and "unreachable" in out and brain.limiter.cooling(NV) > 0


def test_provider_budget_headers_trigger_a_proactive_cooldown(tmp_path, monkeypatch):
    brain = make(tmp_path, monkeypatch, [(200, {"x-ratelimit-remaining-requests": "0",
                                                "x-ratelimit-reset-requests": "2m"},
                                          {"choices": [{"message": {"content": "last one"}}]})])
    assert run(ask(brain)) == ["last one"]
    assert 100 < brain.limiter.availability(NV)[0] <= 120


def test_list_style_content_is_joined(tmp_path, monkeypatch):
    body = {"choices": [{"message": {"content": [{"text": "a"}, {"text": "b"}, "x"]}}]}
    brain = make(tmp_path, monkeypatch, [(200, {}, body)])
    assert run(ask(brain)) == ["ab"]


def test_nvidia_requests_carry_model_overrides_capped_by_max_tokens(tmp_path, monkeypatch):
    brain = make(tmp_path, monkeypatch, [reply("x")], max_tokens=512)
    run(ask(brain))
    payload = brain.calls[0][1]
    assert payload["max_tokens"] == 512 and payload["top_p"] == 1


# ------------------------------------------------------------- availability
def test_models_without_keys_or_consent_are_unavailable_with_reasons(tmp_path, monkeypatch):
    brain = make(tmp_path, monkeypatch, [], models=(NV, OR, ModelSpec("openrouter", "paid/model")),
                 keys={"nvidia": "", "openrouter": "k"})
    assert brain.models == [] and brain.model is None
    reasons = " | ".join(brain.unavailable)
    assert "no nvidia API key" in reasons and "third parties" in reasons
    out = run(ask(brain))[0]
    assert "No free model is usable" in out and brain.calls == []
    enabled = make(tmp_path, monkeypatch, [], models=(OR, ModelSpec("openrouter", "paid/model")),
                   openrouter_enabled=True)
    assert enabled.models == [OR] and "must end in :free" in enabled.unavailable[0]


def test_openrouter_is_admitted_only_while_the_catalog_prices_it_at_zero(tmp_path, monkeypatch):
    catalog = {"data": [{"id": OR.model, "pricing": {"prompt": "0", "completion": "0"},
                         "supported_parameters": ["tools"]}]}

    async def fake_get(url, *, timeout, api_key):
        assert url == "https://openrouter.ai/api/v1/models" and api_key == "or-key"
        return catalog

    monkeypatch.setattr(free_brain, "_http_get_json", fake_get)
    brain = make(tmp_path, monkeypatch, [reply("hello from or")], models=(OR,),
                 openrouter_enabled=True, limits={"openrouter": (10, 10)})
    assert run(ask(brain)) == ["hello from or"]
    url, payload, key = brain.calls[0]
    assert url.startswith("https://openrouter.ai/api/v1") and key == "or-key"
    assert payload["provider"]["allow_fallbacks"] is False
    assert payload["provider"]["max_price"] == {"prompt": 0, "completion": 0}
    catalog["data"][0]["pricing"]["completion"] = "0.5"
    priced = make(tmp_path, monkeypatch, [], models=(OR,), openrouter_enabled=True)
    out = run(ask(priced))[0]
    assert "not admitted as free" in out and priced.calls == []


# -------------------------------------------------------------- model choice
def test_models_are_switched_by_number_name_alias_or_fragment(tmp_path, monkeypatch):
    brain = make(tmp_path, monkeypatch, [], models=(NV, NV2), model="llama")
    assert brain.model == NV2.key
    for value, expected in (("1", NV.key), ("meta/llama-3.3-70b-instruct", NV2.key),
                            ("gpt-oss", NV.key), ("nvidia:openai/gpt-oss-120b", NV.key),
                            ("LLAMA-3.3", NV2.key)):
        assert run(brain.set_model(value)) is None and brain.model == expected, value
    for bad in ("9", "mistral", "", "nvidia"):
        message = run(brain.set_model(bad))
        assert message and "Available:" in message and "1. " in message
    assert "← current" in brain.model_help


def test_the_selected_model_is_tried_first_and_others_are_fallbacks(tmp_path, monkeypatch):
    brain = make(tmp_path, monkeypatch, [reply("x")], models=(NV, NV2), model=NV2.key)
    run(ask(brain))
    assert brain.calls[0][1]["model"] == NV2.model
    assert [s.key for s in brain._order()] == [NV2.key, NV.key]


def test_status_reports_budgets_cooldowns_and_unavailable_models(tmp_path, monkeypatch):
    brain = make(tmp_path, monkeypatch, [reply("x")], models=(NV, OR), limits={"nvidia": (20, 0)},
                 keys={"nvidia": "k", "openrouter": ""})
    run(ask(brain))
    brain.limiter.cool_down(NV.key, 120)
    status = run(brain.status())
    summary = "\n".join(status["usage_summary"])
    assert "nvidia: 1/20 per min · 1 today (no daily cap set)" in summary
    assert "cooling down, back in 2m" in summary and "unavailable — openrouter:" in summary
    text = format_status(status)
    assert "Usage: unavailable" not in text and "nvidia: 1/20 per min" in text
    assert "Session: active" in text


# ------------------------------------------------------------- bridge wiring
def test_free_is_a_selectable_brain_with_its_own_session_pin():
    assert "free" in VALID_BRAINS
    assert bridge.session_file_for("free").name == ".session.free"
    assert bridge.session_file_for("nonsense").name == ".session.claude"
    assert bridge.Bridge._env_key_for("model", "free") == "OVERLORD_FREE_MODEL"
    assert bridge.Bridge._read_cached_usage("free") is None  # never Claude's cache


def test_build_brain_reads_models_keys_and_limits_from_the_environment(monkeypatch):
    for name, value in {
        "OVERLORD_FREE_MODELS": "nvidia:gpt-oss,openrouter:v/m:free",
        "OVERLORD_FREE_MODEL": "gpt-oss", "OVERLORD_WORKER_NVIDIA_API_KEY": "nv",
        "OVERLORD_FREE_NVIDIA_RPM": "7", "OVERLORD_FREE_OPENROUTER_DAILY": "oops",
        "OVERLORD_FREE_OPENROUTER_API_KEY": "or",
    }.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("OVERLORD_FREE_OPENROUTER_ENABLED", "0")  # explicit opt-out
    brain = bridge.build_brain(object(), "free")
    assert brain.name == "free" and brain.model == NV.key
    assert [s.key for s in brain.models] == [NV.key]  # openrouter is opted out
    assert brain.limiter.limits["nvidia"] == (7, 0)
    assert brain.limiter.limits["openrouter"] == free_brain.DEFAULT_LIMITS["openrouter"]


def test_model_command_lists_the_choices_and_switches(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from test_bridge_dispatch import FakeTelegram

    brain = make(tmp_path, monkeypatch, [], models=(NV, NV2))
    instance = bridge.Bridge.__new__(bridge.Bridge)
    instance.brain, instance.brain_name = brain, "free"
    instance.telegram = FakeTelegram()
    instance._brain_lock = asyncio.Lock()
    instance._status_cache, instance._status_by_brain = {}, {}
    instance._console_status_file = None
    monkeypatch.setattr(bridge, "set_env_value", lambda *a: None)

    async def scenario():
        await instance._handle_model(42, "/model")
        assert "1. nvidia:openai/gpt-oss-120b" in instance.telegram.messages[-1][1]
        await instance._handle_model(42, "/model 2")
        assert brain.model == NV2.key
        assert "→ nvidia:meta/llama-3.3-70b-instruct" in instance.telegram.messages[-1][1]
        await instance._handle_effort(42, "/effort high")
        assert "no reasoning-effort" in instance.telegram.messages[-1][1]
        await asyncio.sleep(0)

    run(scenario())
    bridge.os.environ.pop("OVERLORD_FREE_MODEL", None)


# ------------------------------------------------- OpenRouter as the default
CATALOG = {"data": [
    {"id": "big/model-a:free", "context_length": 1_000_000, "pricing": {"prompt": "0", "completion": "0"}},
    {"id": "big/model-b:free", "context_length": 900_000, "pricing": {"prompt": "0", "completion": "0"}},
    {"id": "other/model-c:free", "context_length": 200_000, "pricing": {"prompt": "0", "completion": "0"}},
    {"id": "other/content-safety:free", "context_length": 999_999, "pricing": {"prompt": "0", "completion": "0"}},
    {"id": "paid/model:free", "context_length": 999_999, "pricing": {"prompt": "0.1", "completion": "0"}},
    {"id": "third/model-d:free", "context_length": 100_000, "pricing": {"prompt": "0", "completion": "0"}},
    {"id": "fourth/model-e:free", "context_length": 50_000, "pricing": {"prompt": "0", "completion": "0"}},
    {"id": "vendor/not-free", "context_length": 5_000_000, "pricing": {"prompt": "0", "completion": "0"}},
    "junk", {"id": 5},
]}


def test_discovery_picks_priced_at_zero_chat_models_one_per_vendor():
    assert free_brain.discover_free_models(CATALOG) == [
        "big/model-a:free", "other/model-c:free", "third/model-d:free"]
    assert free_brain.discover_free_models(CATALOG, limit=1) == ["big/model-a:free"]
    assert free_brain.discover_free_models({"data": "x"}) == []
    assert free_brain.discover_free_models(None) == []


def test_openrouter_leads_the_default_model_list():
    specs = parse_models(free_brain.DEFAULT_MODELS)
    assert specs[0] == ModelSpec("openrouter", "free")
    assert {s.provider for s in specs} == {"openrouter", "nvidia"}


def test_connect_expands_the_placeholder_from_the_live_catalog(tmp_path, monkeypatch):
    async def fake_get(url, *, timeout, api_key):
        return CATALOG

    monkeypatch.setattr(free_brain, "_http_get_json", fake_get)
    brain = make(tmp_path, monkeypatch, [], models=(ModelSpec("openrouter", "free"), NV),
                 openrouter_enabled=True)
    assert brain.models == [NV] and brain.model == NV.key
    assert "discovered" in "\n".join(brain.status_snapshot()["usage_summary"])
    run(brain.connect())
    assert [s.key for s in brain.models] == [
        "openrouter:big/model-a:free", "openrouter:other/model-c:free",
        "openrouter:third/model-d:free", NV.key]
    assert brain.model == "openrouter:big/model-a:free"  # OpenRouter leads


def test_a_preferred_model_survives_discovery(tmp_path, monkeypatch):
    async def fake_get(url, *, timeout, api_key):
        return CATALOG

    monkeypatch.setattr(free_brain, "_http_get_json", fake_get)
    brain = make(tmp_path, monkeypatch, [], models=(ModelSpec("openrouter", "free"), NV),
                 openrouter_enabled=True, model="other/model-c:free")
    run(brain.connect())
    assert brain.model == "openrouter:other/model-c:free"


def test_discovery_falls_back_to_known_models_when_the_catalog_is_unreachable(tmp_path, monkeypatch):
    async def broken(url, *, timeout, api_key):
        raise OSError("offline")

    monkeypatch.setattr(free_brain, "_http_get_json", broken)
    brain = make(tmp_path, monkeypatch, [], models=(ModelSpec("openrouter", "free"),),
                 openrouter_enabled=True)
    run(brain.connect())
    assert [s.model for s in brain.models] == list(free_brain.FALLBACK_OPENROUTER)


def test_discovery_without_a_key_or_with_openrouter_disabled_says_why(tmp_path, monkeypatch):
    keyless = make(tmp_path, monkeypatch, [], models=(ModelSpec("openrouter", "free"), NV),
                   keys={"nvidia": "k", "openrouter": ""}, openrouter_enabled=True)
    run(keyless.connect())
    assert keyless.models == [NV] and "no openrouter API key" in keyless.unavailable[0]
    optout = make(tmp_path, monkeypatch, [], models=(ModelSpec("openrouter", "free"), NV),
                  openrouter_enabled=False)
    run(optout.connect())
    assert optout.models == [NV] and "disabled" in optout.unavailable[0]


def test_openrouter_is_on_by_default_in_the_bridge(monkeypatch):
    monkeypatch.delenv("OVERLORD_FREE_OPENROUTER_ENABLED", raising=False)
    monkeypatch.delenv("OVERLORD_FREE_MODELS", raising=False)
    monkeypatch.setenv("OVERLORD_FREE_OPENROUTER_API_KEY", "or-key")
    monkeypatch.delenv("OVERLORD_FREE_MODEL", raising=False)
    brain = bridge.build_brain(object(), "free")
    assert brain._discover_at == 0  # the placeholder is active, not gated off


def test_chat_models_are_admitted_without_tool_support(tmp_path, monkeypatch):
    catalog = {"data": [{"id": OR.model, "pricing": {"prompt": "0", "completion": "0"}}]}

    async def fake_get(url, *, timeout, api_key):
        return catalog

    monkeypatch.setattr(free_brain, "_http_get_json", fake_get)
    brain = make(tmp_path, monkeypatch, [reply("hi")], models=(OR,), openrouter_enabled=True,
                 limits={"openrouter": (10, 10)})
    assert run(ask(brain)) == ["hi"]


# ------------------------------------------------------------------- status
def test_status_lists_every_model_with_its_state_and_marks_the_current_one(tmp_path, monkeypatch):
    brain = make(tmp_path, monkeypatch, [], models=(NV, NV2))
    brain.limiter.cool_down(NV2.key, 90)
    lines = brain.status_snapshot()["usage_summary"]
    assert lines[0] == "Keys: nvidia ✓, openrouter ✓"
    assert f"● {NV.key}: ready" in lines
    assert any(l.startswith(f"○ {NV2.key}: cooling down, back in") for l in lines)


def test_a_standby_free_brain_still_reports_status(monkeypatch):
    for name in ("OVERLORD_WORKER_NVIDIA_API_KEY", "OVERLORD_FREE_MODELS"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("OVERLORD_WORKER_NVIDIA_API_KEY", "nv")
    monkeypatch.setenv("OVERLORD_FREE_OPENROUTER_ENABLED", "0")
    instance = bridge.Bridge.__new__(bridge.Bridge)
    instance.brain = type("Active", (), {"name": "claude", "model": "opus", "effort": None,
                                         "session_id": None})()
    status = instance._basic_status_for("free")
    text = format_status(status)
    assert "Keys: nvidia ✓" in text and "Usage: unavailable" not in text
    assert "nvidia:openai/gpt-oss-120b" in text
