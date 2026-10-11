"""Overlord MCP server: input validation, unit-file safety, and the JSON-RPC loop."""

import io
import json
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent / "plugins" / "overlord" / "scripts"
sys.path.insert(0, str(SCRIPTS))

import overlord_mcp as om  # noqa: E402
from modules.brain import OFFLIMITS_FRAGMENTS  # noqa: E402
import engine_gauge as eg  # noqa: E402


@pytest.fixture(autouse=True)
def ready_gauge(monkeypatch):
    """Every engine is up, so dispatch tests exercise validation, not the gas guard."""
    probes = {
        name: (lambda n=name: eg._entry(n, usable=True, gas=None, state="ready", reason="ok"))
        for name in eg.ENGINES
    }
    monkeypatch.setattr(eg, "_PROBES", probes)
    monkeypatch.setattr(om, "_gauge_module", lambda: eg)


# ------------------------------------------------------------------ dispatch
@pytest.mark.parametrize(
    "session",
    ["../evil", "..", "a/b", "a\\b", ".hidden", "", "x" * 129, "with space", "C:\\x"],
)
def test_session_ids_cannot_name_a_path(monkeypatch, tmp_path, session):
    dispatch = tmp_path / "dispatch"
    monkeypatch.setattr(om, "DISPATCH_DIR", dispatch)
    result = om.dispatch_overlord_worker(
        "W", str(tmp_path), "do the thing", brain="claude", session=session
    )
    assert result["ok"] is False and result["dispatched"] is False
    assert not dispatch.exists()
    assert not list(tmp_path.rglob("*.json"))


@pytest.mark.parametrize("session", ["3f2b8c1e-9a4d-4b7e-8c55-0123456789ab", "run_1.v2-final"])
def test_ordinary_session_ids_are_accepted(monkeypatch, tmp_path, session):
    monkeypatch.setattr(om, "DISPATCH_DIR", tmp_path / "dispatch")
    result = om.dispatch_overlord_worker(
        "W", str(tmp_path), "do the thing", brain="claude", session=session
    )
    assert result["ok"] is True and result["session"] == session
    written = tmp_path / "dispatch" / f"{session}.json"
    payload = json.loads(written.read_text(encoding="utf-8"))
    assert payload["task"] == "do the thing" and payload["session"] == session


def test_invalid_session_is_rejected_before_any_handoff_or_timer(monkeypatch, tmp_path):
    timers = []
    monkeypatch.setattr(om, "DISPATCH_DIR", tmp_path / "dispatch")
    monkeypatch.setattr(om, "schedule_resume_after_cap", lambda **kw: timers.append(kw))
    project = tmp_path / "project"
    result = om.dispatch_overlord_worker(
        "W", str(project), "task", brain="auto", session="../x",
        stakes="high", ambiguous=True,
    )
    assert result["ok"] is False
    assert timers == [] and not project.exists()


def test_generated_session_ids_are_valid(monkeypatch, tmp_path):
    monkeypatch.setattr(om, "DISPATCH_DIR", tmp_path / "dispatch")
    result = om.dispatch_overlord_worker("W", str(tmp_path), "task", brain="claude")
    assert om._SAFE_SESSION.fullmatch(result["session"])


# --------------------------------------------------------------------- email
def test_off_limits_fragments_stay_in_step_with_the_bridge_gate():
    assert set(OFFLIMITS_FRAGMENTS) <= set(om._OFFLIMITS_FRAGMENTS)


@pytest.mark.parametrize(
    "attachment",
    [
        "~/.ssh/id_ed25519",
        "C:\\Users\\me\\.aws\\credentials",
        "/home/me/.gnupg/pubring.kbx",
        "notes/id_rsa.pub",
        ".env",
        "project/.env.production",
        "../overlord-bridge/.env",
    ],
)
def test_secrets_cannot_be_attached_to_an_email(monkeypatch, attachment):
    calls = []
    monkeypatch.setattr(om, "_run", lambda argv, **kw: calls.append(argv))
    result = om.send_overlord_email(["a@example.com"], "s", "b", attachments=[attachment])
    assert result["ok"] is False and "off-limits" in result["stderr"]
    assert calls == []


def test_ordinary_attachments_and_env_examples_are_still_sent(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(om, "_run", lambda argv, **kw: calls.append(argv) or {"ok": True})
    report = tmp_path / "report.pdf"
    report.write_bytes(b"%PDF")
    result = om.send_overlord_email(
        ["a@example.com", "b@example.com"], "Subject", "Body",
        attachments=[str(report), ".env.example"],
    )
    assert result == {"ok": True}
    argv = calls[0]
    assert argv.count("--to") == 2 and argv.count("--attach") == 2
    assert argv[argv.index("--subject") + 1] == "Subject"


def test_blocked_attachment_prevents_the_whole_send(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(om, "_run", lambda argv, **kw: calls.append(argv))
    fine = tmp_path / "fine.txt"
    fine.write_text("x")
    result = om.send_overlord_email(
        ["a@example.com"], "s", "b", attachments=[str(fine), "~/.ssh/id_rsa"]
    )
    assert result["ok"] is False and calls == []


# ------------------------------------------------------------ resume timers
def fake_home(monkeypatch, tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setattr(om, "SCHEDULED_DIR", tmp_path / "scheduled")
    monkeypatch.setattr(om, "_run", lambda argv, **kw: {"ok": True, "stdout": "", "stderr": ""})
    return home


def test_resume_name_cannot_inject_unit_directives(monkeypatch, tmp_path):
    home = fake_home(monkeypatch, tmp_path)
    result = om.schedule_resume_after_cap(
        str(tmp_path), "task", name="x\n[Service]\nExecStart=/bin/evil\r%n", delay_seconds=120
    )
    assert result["ok"] is True
    unit_dir = home / ".config" / "systemd" / "user"
    service = (unit_dir / result["unit"].replace(".timer", ".service")).read_text(encoding="utf-8")
    timer = (unit_dir / result["unit"]).read_text(encoding="utf-8")
    exec_lines = [ln for ln in service.splitlines() if ln.startswith("ExecStart=")]
    assert len(exec_lines) == 1 and "/bin/evil" not in exec_lines[0]
    # The injected text survives only as inert words on the Description line.
    assert [ln for ln in service.splitlines() if ln == "[Service]"] == ["[Service]"]
    for text in (service, timer):
        description = [ln for ln in text.splitlines() if ln.startswith("Description=")]
        assert len(description) == 1
        assert "%n" not in description[0].replace("%%n", "")
    assert "OnCalendar=" in timer and "Persistent=true" in timer


def test_resume_delay_has_a_one_minute_floor_and_bad_times_are_rejected(monkeypatch, tmp_path):
    fake_home(monkeypatch, tmp_path)
    soon = om.schedule_resume_after_cap(str(tmp_path), "task", delay_seconds=5)
    assert soon["delay_seconds"] == 60
    bad = om.schedule_resume_after_cap(str(tmp_path), "task", resume_at="next tuesday-ish")
    assert bad["ok"] is False and "unparseable" in bad["error"]


def test_resume_reads_the_live_reset_time_when_not_overridden(monkeypatch, tmp_path):
    fake_home(monkeypatch, tmp_path)
    monkeypatch.setattr(om, "_cap_reset", lambda cap="session": {
        "ok": True, "cap": "five_hour", "utilization": 99,
        "resets_at": "2999-01-01T00:00:00Z",
    })
    result = om.schedule_resume_after_cap(str(tmp_path), "task", after_reset_seconds=0)
    assert result["ok"] is True and result["delay_seconds"] > 3600
    monkeypatch.setattr(om, "_cap_reset", lambda cap="session": {"ok": False, "error": "no cache"})
    failed = om.schedule_resume_after_cap(str(tmp_path), "task")
    assert failed["ok"] is False and "no cache" in failed["error"]


def test_cap_reset_picks_the_requested_window(monkeypatch):
    usage = {
        "five_hour": {"utilization": 10, "resets_at": "a"},
        "seven_day": {"utilization": 70, "resets_at": "b"},
    }
    monkeypatch.setattr(om, "_usage_json", lambda max_age=120: usage)
    assert om._cap_reset("session")["resets_at"] == "a"
    for weekly in ("weekly", "7d", "week", "seven_day"):
        assert om._cap_reset(weekly)["resets_at"] == "b"
    monkeypatch.setattr(om, "_usage_json", lambda max_age=120: None)
    assert om._cap_reset()["ok"] is False


def test_time_helpers():
    assert om._parse_iso("2030-01-01T00:00:00Z").year == 2030
    assert om._parse_iso("garbage") is None
    assert om._seconds_until(om._parse_iso("1999-01-01T00:00:00Z")) == 0.0


# ---------------------------------------------------------------- capabilities
def test_capability_search_requires_every_keyword(monkeypatch, tmp_path):
    catalog = tmp_path / "CAPABILITIES.md"
    catalog.write_text(
        "# Caps\n\n"
        "- `gas`: show the gauge\n  More about engines.\n\n"
        "- `email`: send a note\n  Uses Gmail.\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(om, "CAPABILITIES_PATH", catalog)
    assert [b["title"] for b in om.list_overlord_capabilities()] == ["gas", "email"]
    assert [b["title"] for b in om.find_overlord_capabilities("gmail NOTE")] == ["email"]
    assert om.find_overlord_capabilities("gmail gauge") == []
    assert len(om.find_overlord_capabilities("   ")) == 2


# ------------------------------------------------------------------ net_ssh
def test_net_ssh_is_refused_outside_the_home_root(monkeypatch, tmp_path):
    monkeypatch.delenv("OVERLORD_NET_SSH_ALLOW", raising=False)
    monkeypatch.chdir(tmp_path)
    result = om.net_ssh("connect", host="192.168.1.10")
    assert result["ok"] is False and "Overlord-only" in result["error"]


def test_net_ssh_targets_are_sanitized_and_secret_paths_refused(monkeypatch, tmp_path):
    monkeypatch.setenv("OVERLORD_NET_SSH_ALLOW", "1")
    monkeypatch.setattr(om, "NET_SSH_SOCK_DIR", tmp_path / "ssh")
    assert om._net_ssh_target("box", "root") == "root@box"
    assert om._net_ssh_target(" box ", None) == "box"
    assert om._net_ssh_target(None, "root") == ""
    assert om._net_ssh_sock("root@box/../x").name == "cm-root@box_.._x.sock"
    refused = om.net_ssh("connect", host="evil/.ssh/id_rsa")
    assert refused["ok"] is False and "off-limits" in refused["error"]
    assert "host is required" in om.net_ssh("run", command="ls")["error"]
    assert "unknown action" in om.net_ssh("explode", host="box")["error"]


def test_net_ssh_run_needs_a_command_and_an_open_session(monkeypatch, tmp_path):
    monkeypatch.setenv("OVERLORD_NET_SSH_ALLOW", "1")
    monkeypatch.setattr(om, "NET_SSH_SOCK_DIR", tmp_path / "ssh")
    monkeypatch.setattr(om, "NET_SSH_LOG", tmp_path / "audit.log")
    assert "command is required" in om.net_ssh("run", host="box", command="  ")["error"]
    result = om.net_ssh("run", host="box", command="uptime")
    assert result["ok"] is False and result["connected"] is False
    status = om.net_ssh("status")
    assert status["ok"] is True and status["connected_to"] == []


# ---------------------------------------------------------------- JSON-RPC
def collect_output(monkeypatch):
    out = io.StringIO()
    monkeypatch.setattr(om.sys, "stdout", out)
    return out


def replies(out):
    return [json.loads(line) for line in out.getvalue().splitlines()]


def test_initialize_lists_tools_and_unknown_methods_are_errors(monkeypatch):
    out = collect_output(monkeypatch)
    om._handle_request({"id": 1, "method": "initialize", "params": {"protocolVersion": "x"}})
    om._handle_request({"id": 2, "method": "tools/list"})
    om._handle_request({"id": 3, "method": "nope"})
    om._handle_request({"method": "notifications/initialized"})
    om._handle_request({"method": "nope"})  # unknown notification: silently ignored
    first, second, third = replies(out)
    assert first["result"]["protocolVersion"] == "x"
    assert {t["name"] for t in second["result"]["tools"]} == set(om.TOOLS)
    assert third["error"]["code"] == -32601


def test_tool_failures_come_back_as_mcp_errors_not_crashes(monkeypatch):
    out = collect_output(monkeypatch)
    om._handle_request({"id": 1, "method": "tools/call", "params": {"name": "ghost"}})
    om._handle_request({"id": 2, "method": "tools/call", "params": {
        "name": "find_overlord_capabilities", "arguments": {"wrong": 1}}})
    om._handle_request({"id": 3, "method": "tools/call", "params": ["not", "a", "dict"]})
    for reply in replies(out):
        assert reply["result"]["isError"] is True


def test_every_tool_declares_a_schema_matching_its_signature():
    import inspect

    for name, (fn, meta) in om.TOOLS.items():
        schema = meta["inputSchema"]
        params = inspect.signature(fn).parameters
        if any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values()):
            continue  # forwards **kwargs to the engine router
        assert set(schema["properties"]) <= set(params), name
        for required in schema.get("required", []):
            assert required in params and params[required].default is inspect.Parameter.empty, name


def test_main_survives_malformed_and_non_object_lines(monkeypatch):
    out = collect_output(monkeypatch)
    lines = ["", "{broken", "[1, 2]", "42", json.dumps({"id": 9, "method": "tools/list"})]
    monkeypatch.setattr(om.sys, "stdin", io.StringIO("\n".join(lines) + "\n"))
    om.main()
    parse_error, array_error, number_error, listing = replies(out)
    assert parse_error["error"]["code"] == -32700
    assert array_error["error"]["code"] == -32600
    assert number_error["error"]["code"] == -32600
    assert listing["id"] == 9 and listing["result"]["tools"]
