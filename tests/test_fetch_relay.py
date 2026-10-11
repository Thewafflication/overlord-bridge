"""The localhost-only headless-browser fetch relay and its helper scripts."""

import asyncio
import importlib.util
import json
from importlib.machinery import SourceFileLoader
from pathlib import Path

import pytest
from aiohttp.test_utils import TestClient, TestServer

ROOT = Path(__file__).resolve().parent.parent

pytestmark = pytest.mark.filterwarnings("ignore::aiohttp.web_exceptions.NotAppKeyWarning")

pytest.importorskip("playwright")
pytest.importorskip("playwright_stealth")
pytest.importorskip("trafilatura")

from modules import fetch_relay  # noqa: E402


def make_app(monkeypatch, *, render=None, extract="extracted text"):
    app = fetch_relay.build_app()
    app.on_startup.clear()  # never launch Chromium in tests
    app.on_cleanup.clear()
    app["browser"] = object()
    app["semaphore"] = asyncio.Semaphore(fetch_relay.MAX_CONCURRENCY)

    async def default_render(browser, url):
        return "<html><body>hi</body></html>", "A Title", url + "#final", 200

    monkeypatch.setattr(fetch_relay, "_render", render or default_render)
    monkeypatch.setattr(
        fetch_relay.trafilatura, "extract", lambda html, **kwargs: extract
    )
    return app


def with_client(app, scenario):
    async def run():
        async with TestClient(TestServer(app)) as client:
            return await scenario(client)

    return asyncio.run(run())


def test_healthz(monkeypatch):
    async def scenario(client):
        response = await client.get("/healthz")
        assert response.status == 200 and await response.text() == "ok"

    with_client(make_app(monkeypatch), scenario)


@pytest.mark.parametrize(
    "query",
    [
        "",
        "?url=",
        "?url=%20%20",
        "?url=ftp://example.com/x",
        "?url=file:///etc/passwd",
        "?url=javascript:alert(1)",
        "?url=http://",
        "?url=example.com",
        "?url=https://example.com&format=pdf",
    ],
)
def test_bad_requests_are_rejected_before_any_browsing(monkeypatch, query):
    rendered = []

    async def render(browser, url):
        rendered.append(url)

    async def scenario(client):
        response = await client.get("/fetch" + query)
        assert response.status == 400

    with_client(make_app(monkeypatch, render=render), scenario)
    assert rendered == []


def test_text_is_the_default_and_empty_extractions_say_so(monkeypatch):
    async def scenario(client):
        response = await client.get("/fetch", params={"url": "https://example.com/a"})
        assert response.status == 200 and response.content_type == "text/plain"
        assert await response.text() == "extracted text"

    with_client(make_app(monkeypatch), scenario)

    async def empty(client):
        response = await client.get("/fetch", params={"url": "https://example.com/a"})
        assert await response.text() == "(no readable text extracted)"

    with_client(make_app(monkeypatch, extract=None), empty)


def test_json_format_reports_metadata_and_optionally_html(monkeypatch):
    async def scenario(client):
        base = {"url": "https://example.com/a", "format": "JSON"}
        plain = await (await client.get("/fetch", params=base)).json()
        assert plain == {
            "url": "https://example.com/a", "final_url": "https://example.com/a#final",
            "status": 200, "title": "A Title", "text": "extracted text",
        }
        with_html = await (await client.get("/fetch", params={**base, "include_html": "YES"})).json()
        assert "hi" in with_html["html"]

    with_client(make_app(monkeypatch), scenario)


def test_html_format_is_capped(monkeypatch):
    monkeypatch.setattr(fetch_relay, "MAX_TEXT_CHARS", 1000)

    async def render(browser, url):
        return "x" * 10_000, "t", url, 200

    async def scenario(client):
        response = await client.get("/fetch", params={"url": "https://e.com", "format": "html"})
        assert response.content_type == "text/html"
        assert len(await response.text()) == 4000

    with_client(make_app(monkeypatch, render=render), scenario)


def test_text_output_is_capped(monkeypatch):
    monkeypatch.setattr(fetch_relay, "MAX_TEXT_CHARS", 1000)

    async def scenario(client):
        response = await client.get("/fetch", params={"url": "https://e.com"})
        assert len(await response.text()) == 1000

    with_client(make_app(monkeypatch, extract="y" * 5000), scenario)


def test_render_failures_map_to_gateway_errors(monkeypatch):
    async def slow(browser, url):
        raise asyncio.TimeoutError

    async def broken(browser, url):
        raise RuntimeError("net::ERR_NAME_NOT_RESOLVED")

    async def scenario_timeout(client):
        response = await client.get("/fetch", params={"url": "https://e.com"})
        body = await response.json()
        assert response.status == 504 and body["error"] == "timeout fetching url"

    async def scenario_broken(client):
        response = await client.get("/fetch", params={"url": "https://e.com"})
        body = await response.json()
        assert response.status == 502 and "ERR_NAME_NOT_RESOLVED" in body["error"]

    with_client(make_app(monkeypatch, render=slow), scenario_timeout)
    with_client(make_app(monkeypatch, render=broken), scenario_broken)


def test_concurrency_is_bounded_by_the_semaphore(monkeypatch):
    state = {"now": 0, "peak": 0}

    async def render(browser, url):
        state["now"] += 1
        state["peak"] = max(state["peak"], state["now"])
        await asyncio.sleep(0.05)
        state["now"] -= 1
        return "<p>x</p>", "t", url, 200

    app = make_app(monkeypatch, render=render)
    app["semaphore"] = asyncio.Semaphore(2)

    async def scenario(client):
        responses = await asyncio.gather(
            *(client.get("/fetch", params={"url": f"https://e.com/{n}"}) for n in range(6))
        )
        assert [r.status for r in responses] == [200] * 6

    with_client(app, scenario)
    assert state["peak"] == 2


def load_fresh(monkeypatch, host):
    monkeypatch.setenv("FETCH_RELAY_HOST", host)
    spec = importlib.util.spec_from_file_location(
        "fetch_relay_under_test", ROOT / "modules" / "fetch_relay.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("host", ["0.0.0.0", "192.168.1.5", "example.com", "::"])
def test_relay_refuses_to_bind_anything_but_loopback(monkeypatch, host):
    with pytest.raises(SystemExit) as info:
        load_fresh(monkeypatch, host)
    assert "not loopback" in str(info.value)


@pytest.mark.parametrize("host", ["127.0.0.1", "::1", "localhost"])
def test_loopback_hosts_are_accepted(monkeypatch, host):
    assert load_fresh(monkeypatch, host).HOST == host


def test_blank_host_falls_back_to_loopback(monkeypatch):
    assert load_fresh(monkeypatch, "   ").HOST == "127.0.0.1"


def test_env_loader_never_overrides_and_reads_utf8(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_bytes(
        "﻿# comment\nRELAY_T_ONE=1\nRELAY_T_KEEP=new\nRELAY_T_NAME='Zoë ✓'\nnoequals\n".encode("utf-8")
    )
    monkeypatch.setenv("RELAY_T_KEEP", "original")
    monkeypatch.delenv("RELAY_T_ONE", raising=False)
    monkeypatch.delenv("RELAY_T_NAME", raising=False)
    fetch_relay.load_env(env)
    import os

    try:
        assert os.environ["RELAY_T_ONE"] == "1"
        assert os.environ["RELAY_T_KEEP"] == "original"
        assert os.environ["RELAY_T_NAME"] == "Zoë ✓"
    finally:
        os.environ.pop("RELAY_T_ONE", None)
        os.environ.pop("RELAY_T_NAME", None)
    fetch_relay.load_env(tmp_path / "missing")  # no file is fine


def test_email_script_env_loader_reads_utf8_and_bom(tmp_path, monkeypatch):
    loader = SourceFileLoader("overlord_email_under_test", str(ROOT / "overlord-email"))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    env = tmp_path / ".env"
    env.write_bytes("﻿GMAIL_USER_T=ben@example.com\nNOTE_T=café\n".encode("utf-8"))
    monkeypatch.delenv("GMAIL_USER_T", raising=False)
    monkeypatch.delenv("NOTE_T", raising=False)
    module._load_env(env)
    import os

    try:
        assert os.environ["GMAIL_USER_T"] == "ben@example.com"
        assert os.environ["NOTE_T"] == "café"
    finally:
        os.environ.pop("GMAIL_USER_T", None)
        os.environ.pop("NOTE_T", None)


def test_email_script_refuses_to_send_without_credentials(monkeypatch, tmp_path):
    loader = SourceFileLoader("overlord_email_creds_test", str(ROOT / "overlord-email"))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    monkeypatch.delenv("GMAIL_USER", raising=False)
    monkeypatch.delenv("GMAIL_APP_PASSWORD", raising=False)
    monkeypatch.setattr(module, "_load_env", lambda path: None)
    monkeypatch.setattr(module.sys, "argv", ["overlord-email", "--to", "a@b.c", "--subject", "s"])
    with pytest.raises(SystemExit) as info:
        module.main()
    assert "GMAIL_USER" in str(info.value)
