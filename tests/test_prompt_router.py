import asyncio
import json

import pytest

from modules import prompt_router
from modules.prompt_router import PromptRouter


PROFILES = {"codex": [{"model": "small", "description": "Low-cost routine work", "qualified": True},
    {"model": "large", "description": "Difficult work", "qualified": True},
    {"model": "unqualified", "description": "Pilot", "qualified": False}]}


def test_classifier_receives_context_and_only_qualified_candidates(monkeypatch):
    async def post(url, payload, **kwargs):
        assert url == "http://127.0.0.1:11434/v1/chat/completions"
        data = json.loads(payload["messages"][1]["content"])
        assert data["context"] == "User: fix the previous issue"
        assert [p["model"] for p in data["models"]] == ["small", "large"]
        assert "tools" not in payload
        assert kwargs["follow_redirects"] is False
        return {"choices": [{"message": {"content": '{"model":"large","reason":"Requires judgment"}'}}]}
    monkeypatch.setattr(prompt_router, "_http_post_json", post)
    router = PromptRouter(enabled=True, profiles=PROFILES, model="local-classifier")
    assert asyncio.run(router.select("codex", "continue", "User: fix the previous issue"))["model"] == "large"


def test_native_catalog_limits_candidates_and_rejects_absent_selection(monkeypatch):
    async def post(url, payload, **kwargs):
        data = json.loads(payload["messages"][1]["content"])
        assert [p["model"] for p in data["models"]] == ["small"]
        return {"choices": [{"message": {"content": '{"model":"large","reason":"Unavailable"}'}}]}
    monkeypatch.setattr(prompt_router, "_http_post_json", post)
    router = PromptRouter(enabled=True, profiles=PROFILES, model="local")
    assert asyncio.run(router.select("codex", "prompt", model_ids={"small"})) is None
    assert router.last["codex"]["status"] == "fallback"


def test_empty_native_catalog_never_calls_classifier(monkeypatch):
    async def post(*args, **kwargs):
        pytest.fail("No eligible models: classifier must not be called")
    monkeypatch.setattr(prompt_router, "_http_post_json", post)
    router = PromptRouter(enabled=True, profiles=PROFILES, model="local")
    assert asyncio.run(router.select("codex", "prompt", model_ids=set())) is None


def test_local_classifier_redirect_is_not_followed(monkeypatch):
    import threading
    import urllib.error
    from http.server import BaseHTTPRequestHandler, HTTPServer
    from modules.workers import _http_post_json
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost,::1")
    class Redirect(BaseHTTPRequestHandler):
        def do_POST(self):
            # Consume the body before closing: unread bytes can cause a TCP
            # reset on Windows instead of exposing the redirect response.
            self.rfile.read(int(self.headers.get("Content-Length", "0")))
            self.send_response(302)
            self.send_header("Location", "http://192.0.2.1/classify")
            self.send_header("Content-Length", "0")
            self.end_headers()
        def log_message(self, *args):
            pass
    server = HTTPServer(("127.0.0.1", 0), Redirect)
    thread = threading.Thread(target=lambda: server.serve_forever(poll_interval=0.01), daemon=True)
    thread.start()
    try:
        with pytest.raises(urllib.error.HTTPError) as error:
            asyncio.run(_http_post_json(f"http://127.0.0.1:{server.server_port}/classify",
                {"prompt": "test"}, timeout=2, api_key="", follow_redirects=False))
        assert error.value.code == 302
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=1)


@pytest.mark.parametrize("content", ['{"model":"unqualified","reason":"Pilot"}',
    '{"model":"unknown","reason":"Use me"}', 'not JSON',
    '{"model":"small","reason":""}', '{"model":"small","reason":"ok","tools":[]}'])
def test_invalid_selection_keeps_existing_model(monkeypatch, content):
    async def post(*args, **kwargs):
        return {"choices": [{"message": {"content": content}}]}
    monkeypatch.setattr(prompt_router, "_http_post_json", post)
    router = PromptRouter(enabled=True, profiles=PROFILES, model="local")
    assert asyncio.run(router.select("codex", "prompt")) is None
    assert router.last["codex"]["status"] == "fallback"


@pytest.mark.parametrize("base", ["https://example.com/v1", "http://example.com/v1",
    "http://user:password@127.0.0.1/v1", "http://127.0.0.1/v1?proxy=cloud"])
def test_classifier_cannot_send_prompts_to_cloud(base):
    router = PromptRouter(enabled=True, profiles=PROFILES, model="local", api_base=base)
    assert asyncio.run(router.select("codex", "private prompt")) is None


def test_disabled_manual_override_and_wrong_brain_do_not_call_provider():
    router = PromptRouter(enabled=False, profiles=PROFILES, model="local")
    assert asyncio.run(router.select("codex", "prompt")) is None
    router.enabled = True
    router.manual.add("codex")
    assert asyncio.run(router.select("codex", "prompt")) is None
    assert asyncio.run(router.select("claude", "prompt")) is None


def test_classifier_cancellation_does_not_run_user_turn(monkeypatch):
    async def post(*args, **kwargs):
        raise asyncio.CancelledError()
    monkeypatch.setattr(prompt_router, "_http_post_json", post)
    router = PromptRouter(enabled=True, profiles=PROFILES, model="local")
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(router.select("codex", "prompt"))


@pytest.mark.parametrize("brain_name", ["codex", "claude"])
@pytest.mark.parametrize("refuse", [False, True])
def test_bridge_routes_before_one_user_turn_without_reset(monkeypatch, brain_name, refuse):
    from test_bridge_turn_control import make_bridge
    from modules import shared_job
    from pathlib import Path

    class Brain:
        name = brain_name
        model = "small"
        session_id = "original-session"
        session_file = Path("unused")
        def __init__(self):
            self.queries = []
            self.changes = []
        async def set_model(self, model):
            self.changes.append(model)
            if refuse:
                return "unavailable"
            self.model = model
        async def routing_model_ids(self):
            return {"small", "large"}
        async def query(self, text):
            self.queries.append((self.model, text))
            yield "Answer"

    async def post(*args, **kwargs):
        return {"choices": [{"message": {"content": '{"model":"large","reason":"Complex task"}'}}]}
    monkeypatch.setattr(prompt_router, "_http_post_json", post)
    monkeypatch.setattr(shared_job, "live_job", lambda *args: None)
    async def scenario():
        brain = Brain()
        instance = make_bridge(brain)
        instance.prompt_router = PromptRouter(enabled=True,
            profiles={brain_name: PROFILES["codex"]}, model="local")
        await instance._handle_turn(42, "Please solve this")
        assert brain.changes == ["large"]
        assert brain.queries == [("small" if refuse else "large", "Please solve this")]
        assert brain.session_id == "original-session"
    asyncio.run(scenario())


def test_native_catalog_failure_preserves_model_and_runs_user_turn_once(monkeypatch):
    from test_bridge_turn_control import make_bridge, BlockingBrain
    async def scenario():
        brain = BlockingBrain()
        brain.name = "codex"
        queries = []
        async def catalog():
            raise TimeoutError("Native catalog unavailable")
        async def query(text):
            queries.append(text)
            yield "Answer"
        monkeypatch.setattr(brain, "routing_model_ids", catalog, raising=False)
        monkeypatch.setattr(brain, "query", query)
        instance = make_bridge(brain)
        instance.prompt_router = PromptRouter(enabled=True, profiles=PROFILES, model="local")
        await instance._handle_turn(42, "Continue work")
        assert queries == ["Continue work"]
        assert brain.model == "test-model"
        assert instance.prompt_router.last["codex"]["status"] == "fallback"
    asyncio.run(scenario())


def test_shared_claude_terminal_keeps_its_model(monkeypatch):
    from test_bridge_turn_control import make_bridge, BlockingBrain
    from modules import shared_job
    monkeypatch.setattr(shared_job, "live_job", lambda *args: object())
    async def scenario():
        brain = BlockingBrain()
        brain.name = "claude"
        brain.session_file = "unused"
        instance = make_bridge(brain)
        instance.prompt_router = PromptRouter(enabled=True, profiles={"claude": PROFILES["codex"]}, model="local")
        await instance._route_prompt(42, "prompt")
        assert instance.prompt_router.last["claude"]["status"] == "fallback"
        assert brain.model == "test-model"
    asyncio.run(scenario())
