"""Gauge robustness and router corner cases (probes are always faked; no network)."""

import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent / "plugins" / "overlord" / "scripts"
sys.path.insert(0, str(SCRIPTS))

import engine_gauge as eg  # noqa: E402


def install(monkeypatch, **states):
    """engine -> (usable, state[, gas]); unspecified engines are ready."""
    probes = {}
    for name in eg.ENGINES:
        spec = states.get(name.replace("-", "_"), (True, "ready"))
        probes[name] = lambda n=name, s=spec: eg._entry(
            n, usable=s[0], gas=s[2] if len(s) > 2 else None, state=s[1], reason=f"{n} {s[1]}"
        )
    monkeypatch.setattr(eg, "_PROBES", probes)


# ------------------------------------------------------------ probe isolation
def test_one_crashing_probe_does_not_blank_the_gauge(monkeypatch):
    install(monkeypatch)

    def explode():
        raise ValueError("could not convert string to float: 'n/a'")

    monkeypatch.setitem(eg._PROBES, "codex", explode)
    gauge = eg.engine_gas_gauge()
    assert set(gauge["engines"]) == set(eg.ENGINES)
    broken = gauge["engines"]["codex"]
    assert broken["usable"] is False and broken["state"] == "unavailable"
    assert "probe failed: ValueError" in broken["reason"]
    assert gauge["engines"]["claude"]["state"] == "ready"
    assert not eg.is_dispatchable_engine(broken)


def test_recommendation_survives_a_crashing_probe(monkeypatch):
    install(monkeypatch)
    monkeypatch.setitem(eg._PROBES, "nvidia", lambda: 1 / 0)
    result = eg.recommend_engine()
    assert result["recommended"]["brain"] == "codex"  # nvidia skipped, next in line
    assert "probe failed" in result["rationale"]


def test_unknown_engines_are_reported_not_raised(monkeypatch):
    install(monkeypatch)
    gauge = eg.engine_gas_gauge(("claude", "mystery"))
    assert gauge["engines"]["mystery"]["reason"] == "unknown engine"


@pytest.mark.parametrize("bad", ["lots", [], {"x": 1}, float("inf"), float("nan")])
def test_garbage_claude_utilization_reads_as_offline(monkeypatch, bad):
    monkeypatch.setattr(eg, "_claude_usage", lambda: {"five_hour": {"utilization": bad}})
    entry = eg._probe_claude()
    assert entry["usable"] is False and entry["state"] == "offline"


def test_garbage_weekly_utilization_does_not_hide_a_good_session(monkeypatch):
    monkeypatch.setattr(eg, "_claude_usage", lambda: {
        "five_hour": {"utilization": 10}, "seven_day": {"utilization": "n/a"},
    })
    assert eg._probe_claude()["state"] == "offline"


def test_claude_states_follow_the_documented_floors(monkeypatch):
    def probe(five, seven=None):
        data = {"five_hour": {"utilization": five, "resets_at": "t"}}
        if seven is not None:
            data["seven_day"] = {"utilization": seven}
        monkeypatch.setattr(eg, "_claude_usage", lambda: data)
        return eg._probe_claude()

    ready = probe(40, 20)
    assert (ready["state"], ready["gas"], ready["weekly_gas"], ready["usable"]) == ("ready", 60, 80, True)
    assert probe(100 - eg.CLAUDE_GAS_FLOOR + 1)["state"] == "out_of_gas"
    assert probe(100)["gas"] == 0
    assert probe(150)["gas"] == 0  # never negative
    degraded = probe(10, 100 - eg.CLAUDE_WEEKLY_DEGRADED_FLOOR + 1)
    assert degraded["state"] == "degraded" and degraded["usable"] is False
    monkeypatch.setattr(eg, "_claude_usage", lambda: None)
    assert eg._probe_claude()["state"] == "offline"


# --------------------------------------------------------------------- router
def test_a_preferred_engine_floats_to_the_front_when_suitable(monkeypatch):
    install(monkeypatch)
    result = eg.recommend_engine(prefer="claude")  # medium work, claude is in the order
    assert result["recommended"]["brain"] == "claude"
    assert "caller preferred claude" in result["rationale"]


def test_an_unsuitable_preference_is_ignored_and_explained(monkeypatch):
    install(monkeypatch)
    result = eg.recommend_engine(stakes="high", prefer="nvidia")
    assert result["recommended"]["brain"] == "claude"
    assert "not suitable for high work" in result["rationale"]
    ignored = eg.recommend_engine(prefer="no-such-engine")
    assert ignored["recommended"]["brain"] == "nvidia"  # unknown names are simply ignored


@pytest.mark.parametrize(
    "kwargs, profile, first",
    [
        ({"must_stay_local": True, "stakes": "high"}, "local-only", "local-agent"),
        ({"multi_file": True}, "high", "claude"),
        ({"needs_resume": True}, "high", "claude"),
        ({"small_chore": True}, "small", "nvidia"),
        ({"stakes": "low"}, "small", "nvidia"),
        ({"stakes": "LOW", "ambiguous": True}, "high", "claude"),
        ({}, "medium", "nvidia"),
    ],
)
def test_job_profiles_route_by_shape(monkeypatch, kwargs, profile, first):
    install(monkeypatch)
    result = eg.recommend_engine(**kwargs)
    assert result["suitability"]["profile"] == profile
    assert result["suitability"]["order"][0] == first


def test_weekly_cap_exhaustion_defers_to_the_weekly_reset(monkeypatch):
    install(monkeypatch, nvidia=(False, "offline"), codex=(False, "offline"),
            local_agent=(False, "offline"))
    degraded = eg._entry(
        "claude", usable=False, gas=60, weekly_gas=3, state="degraded", reason="weekly spent",
        detail={"resets_at": "daily", "weekly_resets_at": "next-week"},
    )
    monkeypatch.setitem(eg._PROBES, "claude", lambda: degraded)
    result = eg.recommend_engine(stakes="high")
    assert result["decision"] == "defer_until_reset"
    assert result["schedule"] == {"brain": "claude", "cap": "weekly", "resets_at": "next-week"}


def test_nothing_ready_for_small_work_is_blocked_not_deferred(monkeypatch):
    install(monkeypatch, claude=(False, "out_of_gas", 0), nvidia=(False, "offline"),
            codex=(False, "offline"), local_agent=(False, "offline"))
    result = eg.recommend_engine(small_chore=True)
    assert result["decision"] == "blocked" and result["recommended"] is None
    assert all(s["engine"] in eg.ENGINES for s in result["skipped"])


def test_reserve_claude_is_only_used_for_high_complexity_work(monkeypatch):
    reserve_gas = eg.CLAUDE_RESERVE_GAS_FLOOR
    install(monkeypatch, nvidia=(False, "offline"), codex=(False, "offline"),
            local_agent=(False, "offline"), claude=(True, "ready", reserve_gas))
    medium = eg.recommend_engine()
    assert medium["recommended"] is None and "reserve" in medium["skipped"][-1]["why"].lower()
    high = eg.recommend_engine(stakes="high")
    assert high["recommended"]["brain"] == "claude"
    assert high["decision"] == "dispatch_with_handoff" and high["handoff"]["required"] is True


def test_dispatchability_requires_both_usable_and_ready():
    assert eg.is_dispatchable_engine(eg._entry("x", usable=True, gas=None, state="ready", reason=""))
    assert not eg.is_dispatchable_engine(eg._entry("x", usable=True, gas=None, state="degraded", reason=""))
    assert not eg.is_dispatchable_engine(eg._entry("x", usable=False, gas=None, state="ready", reason=""))
    assert not eg.is_dispatchable_engine(None)


def test_fit_labels_match_the_job_profile():
    assert eg._fit_label("high", "claude", context_size="small") == "best"
    assert eg._fit_label("high", "nvidia", context_size="small") == "not-suitable"
    assert eg._fit_label("medium", "local-agent", context_size="large").startswith("last-resort")
    assert eg._fit_label("medium", "local-agent", context_size="small") == "not-suitable"
    assert eg._fit_label("local-only", "claude", context_size="small") == "excluded"
    assert eg._fit_label("???", "claude", context_size="small") == "unknown"


def test_iso_parsing_assumes_utc_for_naive_times():
    assert eg._parse_iso("") is None and eg._parse_iso("nope") is None
    naive = eg._parse_iso("2030-01-01T00:00:00")
    assert naive.utcoffset().total_seconds() == 0
    assert eg._parse_iso("2030-01-01T00:00:00Z") == naive


def test_recent_rate_limit_hits_count_only_recent_matching_failures(monkeypatch, tmp_path):
    import datetime
    import json

    now = datetime.datetime.now(datetime.timezone.utc)
    old = (now - datetime.timedelta(hours=12)).isoformat()
    fresh = now.isoformat()
    events = tmp_path / "events.jsonl"
    rows = [
        {"brain": "codex", "status": "failed", "finished_at": fresh, "result_tail": "429 rate limit exceeded"},
        {"brain": "codex", "status": "failed", "finished_at": old, "result_tail": "429 rate limit exceeded"},
        {"brain": "codex", "status": "finished", "finished_at": fresh, "result_tail": "rate limit"},
        {"brain": "claude", "status": "failed", "finished_at": fresh, "result_tail": "rate limit"},
        {"brain": "codex", "status": "failed", "finished_at": fresh, "result_tail": "syntax error"},
    ]
    events.write_text("\n".join(json.dumps(r) for r in rows) + "\nnot json\n", encoding="utf-8")
    monkeypatch.setattr(eg, "_EVENTS_PATH", events)
    assert eg._recent_rate_limit_hits("codex") == 1
    monkeypatch.setattr(eg, "_EVENTS_PATH", tmp_path / "missing.jsonl")
    assert eg._recent_rate_limit_hits("codex") == 0
