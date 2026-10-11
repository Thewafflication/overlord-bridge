import asyncio

import pytest

from test_codex_request_pump import make_brain


def test_catalog_pagination_uses_inference_model_and_excludes_hidden(tmp_path, monkeypatch):
    brain, _ = make_brain(tmp_path)
    calls = []
    async def request(method, params):
        calls.append((method, params))
        if params["cursor"] is None:
            return {"data": [{"id": "picker-id", "model": "small", "hidden": False},
                             {"model": "hidden", "hidden": True}], "nextCursor": "page2"}
        return {"data": [{"model": "large", "hidden": False}], "nextCursor": None}
    monkeypatch.setattr(brain, "_request", request)
    assert asyncio.run(brain.routing_model_ids()) == {"small", "large"}
    assert calls == [("model/list", {"cursor": None, "limit": 100, "includeHidden": False}),
                     ("model/list", {"cursor": "page2", "limit": 100, "includeHidden": False})]


@pytest.mark.parametrize("page", [
    {"data": None}, {"data": [None]},
    {"data": [{"model": "small", "hidden": "false"}]},
    {"data": [{"model": "", "hidden": False}]},
    {"data": [{"model": "same", "hidden": False}] * 2},
    {"data": [], "nextCursor": "repeat"},
    {"data": [], "nextCursor": 1},
])
def test_invalid_or_cyclic_catalog_fails_closed(tmp_path, monkeypatch, page):
    brain, _ = make_brain(tmp_path)
    async def request(*args):
        return page
    monkeypatch.setattr(brain, "_request", request)
    with pytest.raises(ValueError):
        asyncio.run(brain.routing_model_ids())


def test_catalog_cancellation_propagates(tmp_path, monkeypatch):
    brain, _ = make_brain(tmp_path)
    async def request(*args):
        raise asyncio.CancelledError()
    monkeypatch.setattr(brain, "_request", request)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(brain.routing_model_ids())
