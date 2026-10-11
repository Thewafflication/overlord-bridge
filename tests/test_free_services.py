import asyncio
from copy import deepcopy

import pytest

from modules.free_services import validate_free_model
from modules import workers


MODEL = "example/model:free"
CATALOG = {"data": [{"id": MODEL, "pricing": {"prompt": "0", "completion": "0"},
                     "supported_parameters": ["tools"]}]}


@pytest.mark.parametrize("price", ["0.1", "-1", "NaN", "Infinity", None, "bad"])
def test_rejects_nonzero_or_unknown_prices(price):
    catalog = deepcopy(CATALOG)
    catalog["data"][0]["pricing"]["completion"] = price
    with pytest.raises(ValueError):
        validate_free_model(catalog, MODEL)


@pytest.mark.parametrize("catalog,model", [({}, MODEL), (CATALOG, "example/model"),
    ({"data": []}, MODEL), ({"data": CATALOG["data"] * 2}, MODEL),
    ({"data": [{"id": MODEL, "pricing": {"prompt": "0", "completion": "0"}}]}, MODEL)])
def test_requires_unique_free_tool_model(catalog, model):
    with pytest.raises(ValueError):
        validate_free_model(catalog, model)


def test_worker_uses_free_price_guard_and_reports_result(tmp_path, monkeypatch):
    monkeypatch.setenv("OVERLORD_WORKER_OPENROUTER_ENABLED", "1")
    monkeypatch.setenv("OVERLORD_WORKER_OPENROUTER_API_KEY", "test-key")
    calls = []
    async def get(url, **kwargs):
        assert url == "https://openrouter.ai/api/v1/models"
        return CATALOG
    async def post(url, payload, **kwargs):
        calls.append(deepcopy(payload))
        assert url == "https://openrouter.ai/api/v1/chat/completions"
        if len(calls) == 1:
            return {"choices": [{"message": {"tool_calls": [{"id": "inspect",
                "function": {"name": "list_files", "arguments": "{}"}}]}}]}
        return {"choices": [{"message": {"content": "Finished inspection."}}]}
    monkeypatch.setattr(workers, "_http_get_json", get)
    monkeypatch.setattr(workers, "_http_post_json_retry", post)
    manager = workers.WorkerManager(send=lambda *args: None, owner=1, dispatch_dir=tmp_path)
    reports = []
    monkeypatch.setattr(manager, "_emit_report", reports.append)
    asyncio.run(manager._run_local_agent_worker(name="Free", folder=tmp_path,
        task="Inspect the project", session=None, resume=False, model=MODEL,
        files=[], brain="openrouter"))
    assert calls[0]["model"] == MODEL
    assert calls[0]["tools"]
    assert calls[0]["provider"] == {"allow_fallbacks": False,
        "require_parameters": True, "max_price": {"prompt": 0, "completion": 0}}
    assert len(calls) == 2
    assert calls[1]["provider"] == calls[0]["provider"]
    assert any(message["role"] == "tool" for message in calls[1]["messages"])
    assert reports[-1]["status"] == "finished"


def test_no_cloud_call_without_consent(tmp_path, monkeypatch):
    monkeypatch.delenv("OVERLORD_WORKER_OPENROUTER_ENABLED", raising=False)
    manager = workers.WorkerManager(send=lambda *args: None, owner=1, dispatch_dir=tmp_path)
    reports = []
    monkeypatch.setattr(manager, "_emit_report", reports.append)
    asyncio.run(manager._run_local_agent_worker(name="Free", folder=tmp_path,
        task="Inspect", session=None, resume=False, model=MODEL,
        files=[], brain="openrouter"))
    assert reports[-1]["status"] == "rejected"


@pytest.mark.parametrize("supported", ["tools", "tool_choice,tools", None, {"tools": True}, []])
def test_tool_support_must_be_an_explicit_list_entry(supported):
    catalog = deepcopy(CATALOG)
    catalog["data"][0]["supported_parameters"] = supported
    with pytest.raises(ValueError, match="tool support"):
        validate_free_model(catalog, MODEL)


def test_a_zero_priced_tool_model_is_admitted():
    validate_free_model(deepcopy(CATALOG), MODEL)
    catalog = deepcopy(CATALOG)
    catalog["data"][0]["pricing"] = {"prompt": 0, "completion": "0.0"}
    validate_free_model(catalog, MODEL)


@pytest.mark.parametrize("pricing", [None, "free", {"prompt": "0"}, {"completion": "0"}])
def test_missing_or_malformed_pricing_is_rejected(pricing):
    catalog = deepcopy(CATALOG)
    catalog["data"][0]["pricing"] = pricing
    with pytest.raises(ValueError, match="pricing"):
        validate_free_model(catalog, MODEL)


def test_provider_policy_forbids_fallbacks_and_any_spend():
    from modules.free_services import free_provider_policy

    policy = free_provider_policy()
    assert policy["allow_fallbacks"] is False
    assert policy["require_parameters"] is True
    assert policy["max_price"] == {"prompt": 0, "completion": 0}
    policy["max_price"]["prompt"] = 5
    assert free_provider_policy()["max_price"]["prompt"] == 0  # fresh dict every call
