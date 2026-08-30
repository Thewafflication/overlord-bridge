import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import modules.codex_brain as cb  # noqa: E402


def test_codex_brain_records_rate_limits_cache(monkeypatch, tmp_path):
    cache = tmp_path / "codex_usage.json"
    monkeypatch.setattr(cb, "CODEX_USAGE_CACHE", cache)

    cb._record_codex_usage_cache_from_message(
        {
            "method": "event_msg",
            "params": {
                "payload": {
                    "type": "token_count",
                    "rate_limits": {
                        "plan_type": "plus",
                        "primary": {
                            "used_percent": 12.0,
                            "window_minutes": 300,
                            "resets_at": 9999992000,
                        },
                        "secondary": {
                            "used_percent": 34.0,
                            "window_minutes": 10080,
                            "resets_at": 9999993000,
                        },
                    },
                }
            },
        }
    )

    usage = json.loads(cache.read_text(encoding="utf-8"))
    assert usage["session"]["used"] == 12.0
    assert usage["session"]["gas"] == 88
    assert usage["weekly"]["used"] == 34.0
    assert usage["weekly"]["gas"] == 66
    assert usage["plan_type"] == "plus"
    assert usage["source"] == "codex_app_server"


def test_codex_brain_records_weekly_only_cache(monkeypatch, tmp_path):
    cache = tmp_path / "codex_usage.json"
    monkeypatch.setattr(cb, "CODEX_USAGE_CACHE", cache)

    cb._record_codex_usage_cache_from_message(
        {
            "payload": {
                "rate_limits": {
                    "primary": {
                        "used_percent": 6.0,
                        "window_minutes": 10080,
                        "resets_at": 9999993000,
                    },
                    "secondary": None,
                }
            }
        }
    )

    usage = json.loads(cache.read_text(encoding="utf-8"))
    assert usage["session"] is None
    assert usage["weekly"]["used"] == 6.0


def test_codex_usage_accepts_current_camel_case_rate_limits():
    usage = cb._codex_usage_from_rate_limits(
        {
            "planType": "plus",
            "primary": {
                "usedPercent": 21,
                "windowDurationMins": 300,
                "resetsAt": 9999992000,
            },
            "secondary": {
                "usedPercent": 43,
                "windowDurationMins": 10080,
                "resetsAt": 9999993000,
            },
        }
    )
    assert usage is not None
    assert usage["session"]["gas"] == 79
    assert usage["weekly"]["gas"] == 57
    assert usage["plan_type"] == "plus"


def test_codex_status_uses_resolved_model_and_live_limits(monkeypatch, tmp_path):
    monkeypatch.setattr(cb, "CODEX_USAGE_CACHE", tmp_path / "codex_usage.json")
    brain = cb.CodexBrain(
        gate=object(),
        cwd=str(tmp_path),
        model=None,
        session_file=tmp_path / ".session.codex",
        developer_instructions="",
    )
    brain._thread_id = "thread-1"
    brain._active_model = "gpt-resolved"
    brain._model_provider = "openai"

    async def fake_request(method, params):
        assert method == cb.M_ACCOUNT_RATE_LIMITS_READ
        assert params is None
        return {
            "rateLimits": {
                "planType": "plus",
                "primary": {"usedPercent": 8, "windowDurationMins": 300},
                "secondary": {"usedPercent": 19, "windowDurationMins": 10080},
            }
        }

    monkeypatch.setattr(brain, "_request", fake_request)
    status = asyncio.run(brain.status())

    assert status["model"] == "gpt-resolved"
    assert status["model_provider"] == "openai"
    assert status["usage"]["session"]["gas"] == 92
    assert status["usage"]["weekly"]["gas"] == 81


def test_codex_tracks_current_thread_token_usage(tmp_path):
    brain = cb.CodexBrain(
        gate=object(),
        cwd=str(tmp_path),
        model="gpt-test",
        session_file=tmp_path / ".session.codex",
        developer_instructions="",
    )
    brain._handle_notification(
        "thread/tokenUsage/updated",
        {
            "tokenUsage": {
                "total": {"inputTokens": 900, "outputTokens": 100, "totalTokens": 1000},
                "last": {"inputTokens": 180, "outputTokens": 20, "totalTokens": 200},
                "modelContextWindow": 10000,
            }
        },
    )
    assert brain._thread_token_usage["totalTokens"] == 1000
    assert brain._thread_token_usage["lastTotalTokens"] == 200
    assert brain._thread_token_usage["modelContextWindow"] == 10000


def test_codex_user_input_request_uses_telegram_choices(tmp_path):
    class FakeTelegram:
        def __init__(self):
            self.messages = []

        def send(self, owner, text):
            self.messages.append((owner, text))

    class FakeGate:
        owner = 42

        def __init__(self):
            self.telegram = FakeTelegram()
            self.choices = []

        async def choose(self, prompt, options):
            self.choices.append((prompt, options))
            return "SQLite"

    gate = FakeGate()
    brain = cb.CodexBrain(
        gate=gate,
        cwd=str(tmp_path),
        model="gpt-test",
        session_file=tmp_path / ".session.codex",
        developer_instructions="",
    )

    response = asyncio.run(
        brain._request_user_input(
            {
                "questions": [
                    {
                        "id": "database",
                        "header": "Database",
                        "question": "Which database should we use?",
                        "options": [
                            {"label": "Postgres", "description": "Server"},
                            {"label": "SQLite", "description": "Embedded"},
                        ],
                    }
                ]
            }
        )
    )

    assert response == {"answers": {"database": {"answers": ["SQLite"]}}}
    assert gate.choices[0][1][1] == ("SQLite", "Embedded")
