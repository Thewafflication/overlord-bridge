"""Worker intake rules, process outcomes, the local agent loop, and its safety rails."""

import asyncio
import json
import urllib.error
from email.message import Message
from pathlib import Path

import pytest

from modules import workers
from modules.workers import (
    WorkerManager,
    WorkerReportStore,
    _extract_json_object,
    _extract_xmlish_tool_call,
    _is_answer_only_worker_task,
    _local_agent_command_denial,
    _local_agent_path_denial,
    _resolve_worker_relative_path,
    _under_allowed_root,
    _worker_file_args,
)


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    root = tmp_path / "projects"
    root.mkdir()
    monkeypatch.setattr(workers, "_ALLOWED_ROOTS", (root,))
    # Terminal reports try to type into a live shared Claude session; never here.
    monkeypatch.setattr(workers.shared_job, "notify", lambda text: False)
    return root


def make_manager(tmp_path, **kwargs):
    sent = []
    reports = []

    async def on_report(report):
        reports.append(report)

    manager = WorkerManager(
        send=lambda chat_id, text: sent.append(text),
        owner=42,
        dispatch_dir=tmp_path / "dispatch",
        report_dir=tmp_path / "reports",
        on_report=on_report,
        **kwargs,
    )
    return manager, sent, reports


def events(manager):
    path = manager.report_store.events_path
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def statuses(manager):
    return [event["status"] for event in events(manager)]


def run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------- allowed folders
def test_only_folders_inside_the_allowed_roots_are_accepted(isolated, tmp_path):
    project = isolated / "app"
    project.mkdir()
    assert _under_allowed_root(str(project)) == project.resolve()
    assert _under_allowed_root(str(isolated)) == isolated.resolve()
    assert _under_allowed_root(str(tmp_path)) is None
    assert _under_allowed_root(str(isolated / ".." / "elsewhere")) is None
    assert _under_allowed_root("") is None or _under_allowed_root("") != isolated


def test_sibling_directory_with_a_shared_prefix_is_not_inside_the_root(isolated):
    sibling = isolated.parent / (isolated.name + "-evil")
    sibling.mkdir()
    assert _under_allowed_root(str(sibling)) is None


# ------------------------------------------------------------------ intake
REJECTIONS = [
    ({"folder": "{missing}", "task": "t"}, "bad_folder"),
    ({"folder": "{project}", "task": "   "}, "empty_task"),
    ({"folder": "{project}", "task": "t", "brain": "gemini"}, "bad_brain"),
    ({"folder": "{project}", "task": "t", "brain": "codex", "approval_policy": "yolo"},
     "bad_codex_approval_policy"),
    ({"folder": "{project}", "task": "t", "brain": "codex", "sandbox": "none"},
     "bad_codex_sandbox"),
    ({"folder": "{project}", "task": "t", "brain": "local-agent", "files": ["../../etc/passwd"]},
     "bad_worker_files"),
    ({"folder": "{project}", "task": "t", "brain": "nvidia", "files": ["nope.py"]},
     "bad_worker_files"),
    ({"folder": "{project}", "task": "t", "brain": "nvidia", "files": 5},
     "bad_worker_files"),
]


@pytest.mark.parametrize("request_body, reason", REJECTIONS)
def test_bad_requests_are_rejected_loudly_and_never_started(
    isolated, tmp_path, monkeypatch, request_body, reason
):
    project = isolated / "app"
    project.mkdir()

    async def scenario():
        manager, sent, _ = make_manager(tmp_path)
        started = []
        monkeypatch.setattr(manager, "_run", lambda *a, **k: started.append(a))
        body = {
            k: (v.format(project=project, missing=isolated / "missing") if isinstance(v, str) else v)
            for k, v in request_body.items()
        }
        manager._accept({"name": "W", **body})
        assert started == [] and manager._running == {}
        assert len(sent) == 1 and sent[0].startswith("❌ [W]")
        assert events(manager)[-1]["reason"] == reason
        assert events(manager)[-1]["status"] == "rejected"

    run(scenario())


def test_a_second_worker_with_the_same_name_is_ignored_while_the_first_runs(
    isolated, tmp_path, monkeypatch
):
    project = isolated / "app"
    project.mkdir()

    async def scenario():
        manager, sent, _ = make_manager(tmp_path)
        gate = asyncio.Event()

        async def slow_run(*args, **kwargs):
            await gate.wait()

        monkeypatch.setattr(manager, "_run", slow_run)
        request = {"name": "W", "folder": str(project), "task": "t"}
        manager._accept(request)
        manager._accept(request)
        assert "already running" in sent[-1]
        assert statuses(manager) == ["accepted", "duplicate_ignored"]
        gate.set()
        await asyncio.gather(*manager._running.values())

    run(scenario())


def test_brain_aliases_normalize(isolated, tmp_path, monkeypatch):
    project = isolated / "app"
    project.mkdir()

    async def scenario():
        manager, _, _ = make_manager(tmp_path)
        seen = []

        async def record(name, folder, task, brain, *rest):
            seen.append(brain)

        monkeypatch.setattr(manager, "_run", record)
        for index, alias in enumerate(["NIM", "nvidia-nim", "local-agent", "Claude"]):
            manager._accept({"name": f"W{index}", "folder": str(project), "task": "t", "brain": alias})
        await asyncio.gather(*manager._running.values())
        assert seen == ["nvidia", "nvidia", "local-agent", "claude"]

    run(scenario())


# --------------------------------------------------------------- file hints
def test_file_hints_must_be_real_files_inside_the_worker_folder(isolated):
    folder = isolated / "app"
    (folder / "src").mkdir(parents=True)
    (folder / "src" / "a.py").write_text("x", encoding="utf-8")
    assert _worker_file_args(folder, None) == ([], None)
    assert _worker_file_args(folder, "") == ([], None)
    assert _worker_file_args(folder, "src/a.py") == (["src/a.py"], None)
    files, error = _worker_file_args(folder, ["src/a.py", "./src/a.py", "", str(folder / "src" / "a.py")])
    assert files == ["src/a.py"] and error is None  # deduplicated, blanks skipped
    assert _worker_file_args(folder, ["src"])[1] == "file_not_regular:src"
    assert _worker_file_args(folder, ["../x"])[1] == "file_outside_worker_folder:../x"
    assert _worker_file_args(folder, ["missing.py"])[1] == "file_not_found:missing.py"
    assert _worker_file_args(folder, {"a": 1})[1] == "files_must_be_string_or_list"


def test_relative_paths_cannot_escape_the_worker_folder(isolated):
    folder = isolated / "app"
    folder.mkdir()
    inside, error = _resolve_worker_relative_path(folder, "sub/file.txt")
    assert inside == (folder / "sub" / "file.txt").resolve() and error is None
    assert _resolve_worker_relative_path(folder, "")[1] == "empty_path"
    for escape in ("../other", "sub/../../other", str(isolated / "other")):
        assert _resolve_worker_relative_path(folder, escape)[1].startswith("path_outside_worker_folder")


# ----------------------------------------------------------- process outcomes
class FakeProc:
    def __init__(self, out=b"", err=b"", returncode=0, hang=False):
        self._out, self._err, self.returncode, self._hang = out, err, returncode, hang
        self.killed = False

    async def communicate(self):
        if self._hang:
            await asyncio.Event().wait()
        return self._out, self._err

    def kill(self):
        self.killed = True

    async def wait(self):
        return self.returncode


def patch_exec(monkeypatch, proc=None, error=None):
    calls = []

    async def fake_exec(*argv, **kwargs):
        calls.append((argv, kwargs))
        if error is not None:
            raise error
        return proc

    monkeypatch.setattr(workers.asyncio, "create_subprocess_exec", fake_exec)
    return calls


def start_and_wait(manager, folder, **overrides):
    request = {"name": "W", "folder": str(folder), "task": "do it", **overrides}

    async def scenario():
        manager._accept(request)
        await asyncio.gather(*manager._running.values())
        await asyncio.sleep(0)  # let on_report callbacks finish

    return scenario


def test_successful_worker_reports_output_and_session(isolated, tmp_path, monkeypatch):
    project = isolated / "app"
    project.mkdir()
    calls = patch_exec(monkeypatch, FakeProc(out=b"all committed\n"))
    manager, sent, reports = make_manager(tmp_path)
    run(start_and_wait(manager, project, session="sess-1")())
    argv, kwargs = calls[0]
    assert argv[0] == "claude" and kwargs["cwd"] == str(project.resolve())
    assert statuses(manager) == ["accepted", "started", "finished"]
    assert sent[-1].startswith("✅ [W] finished in app:") and "all committed" in sent[-1]
    assert "(session: sess-1)" in sent[-1]
    assert [r["status"] for r in reports] == ["finished"]
    assert manager._running == {}
    latest = json.loads((tmp_path / "reports" / "latest" / "W.json").read_text(encoding="utf-8"))
    assert latest["status"] == "finished" and latest["exit_code"] == 0


def test_worker_output_is_redacted_before_it_reaches_telegram_or_disk(isolated, tmp_path, monkeypatch):
    project = isolated / "app"
    project.mkdir()
    patch_exec(monkeypatch, FakeProc(out=b"deployed with OPENAI_API_KEY=sk-live-1234 ok\n"))
    manager, sent, _ = make_manager(tmp_path)
    run(start_and_wait(manager, project)())
    assert "sk-live-1234" not in sent[-1]
    assert "sk-live-1234" not in manager.report_store.events_path.read_text(encoding="utf-8")


def test_nonzero_exit_is_a_failure_with_stderr(isolated, tmp_path, monkeypatch):
    project = isolated / "app"
    project.mkdir()
    patch_exec(monkeypatch, FakeProc(err=b"boom", returncode=3))
    manager, sent, _ = make_manager(tmp_path)
    run(start_and_wait(manager, project)())
    assert statuses(manager)[-1] == "failed"
    assert "failed in app (exit 3)" in sent[-1] and "boom" in sent[-1]


def test_signal_death_is_reported_as_interruption_not_failure(isolated, tmp_path, monkeypatch):
    project = isolated / "app"
    project.mkdir()
    patch_exec(monkeypatch, FakeProc(returncode=-15))
    manager, sent, _ = make_manager(tmp_path, is_shutting_down=lambda: True)
    run(start_and_wait(manager, project)())
    assert statuses(manager)[-1] == "interrupted"
    assert "INTERRUPTED" in sent[-1] and "restarting" in sent[-1]


def test_a_worker_over_the_time_cap_is_killed_and_resumable(isolated, tmp_path, monkeypatch):
    project = isolated / "app"
    project.mkdir()
    proc = FakeProc(hang=True)
    patch_exec(monkeypatch, proc)
    manager, sent, _ = make_manager(tmp_path, timeout=0.05)
    run(start_and_wait(manager, project)())
    assert proc.killed
    assert statuses(manager)[-1] == "timed_out"
    assert "was killed" in sent[-1] and "resume" in sent[-1]


def test_missing_cli_is_a_start_failure(isolated, tmp_path, monkeypatch):
    project = isolated / "app"
    project.mkdir()
    patch_exec(monkeypatch, error=FileNotFoundError("claude"))
    manager, sent, _ = make_manager(tmp_path)
    run(start_and_wait(manager, project)())
    assert statuses(manager)[-1] == "start_failed" and "could not start" in sent[-1]
    assert manager._running == {}


def test_unexpected_launch_errors_are_reported_as_crashes(isolated, tmp_path, monkeypatch):
    project = isolated / "app"
    project.mkdir()
    patch_exec(monkeypatch, error=PermissionError("denied"))
    manager, sent, _ = make_manager(tmp_path)
    run(start_and_wait(manager, project)())
    assert statuses(manager)[-1] == "crashed" and "crashed: denied" in sent[-1]


def test_codex_worker_reports_the_real_session_id(isolated, tmp_path, monkeypatch):
    project = isolated / "app"
    project.mkdir()
    calls = patch_exec(
        monkeypatch, FakeProc(out=b"session id: 0199abcd-1234-7000-8000-abcdef012345\nok")
    )
    manager, sent, _ = make_manager(tmp_path, codex_bin="codex")
    run(start_and_wait(manager, project, brain="codex", sandbox="workspace-write")())
    assert calls[0][0][:3] == ("codex", "--sandbox", "workspace-write")
    last = events(manager)[-1]
    assert last["real_codex_session_id"] == "0199abcd-1234-7000-8000-abcdef012345"
    assert "(session: 0199abcd-1234-7000-8000-abcdef012345)" in sent[-1]


# ------------------------------------------------------------- report store
def test_report_store_bounds_tails_rotates_and_names_files_safely(tmp_path):
    store = WorkerReportStore(tmp_path / "r", max_tail_chars=50, max_events_bytes=300)
    store.record({"name": "../../evil name", "status": "finished", "result_tail": "z" * 500})
    latest = list((tmp_path / "r" / "latest").glob("*.json"))
    assert [p.name for p in latest] == ["evil_name.json"]
    event = json.loads(latest[0].read_text(encoding="utf-8"))
    assert event["result_truncated"] is True and "omitted" in event["result_tail"]
    for n in range(10):
        store.record({"name": "w", "status": "started", "n": n, "result_tail": "x"})
    assert (tmp_path / "r" / "events.1.jsonl").exists()
    assert (tmp_path / "r" / "events.jsonl").stat().st_size <= 600
    assert not (tmp_path / "evil name.json").exists()


def test_report_store_with_rotation_disabled_keeps_growing(tmp_path):
    store = WorkerReportStore(tmp_path / "r", max_tail_chars=10, max_events_bytes=0)
    for _ in range(20):
        store.record({"name": "w", "status": "started"})
    assert not (tmp_path / "r" / "events.1.jsonl").exists()
    assert len((tmp_path / "r" / "events.jsonl").read_text(encoding="utf-8").splitlines()) == 20


# ------------------------------------------------------ local agent safety
@pytest.mark.parametrize(
    "command",
    [
        "cat ~/.ssh/id_rsa",
        "type C:\\Users\\me\\.aws\\credentials",
        "sudo rm -rf build",
        "ls; su root",
        "rm -rf /",
        "cd / && ls",
        "find / -name '*.pem'",
        "mkfs.ext4 /dev/sda1",
        "shutdown now",
        "cat .env",
        "cat .env.production",
        "python app.py && cat ./.env",
    ],
)
def test_dangerous_commands_are_refused_for_local_agents(isolated, command):
    assert _local_agent_command_denial(command, isolated) is not None


@pytest.mark.parametrize(
    "command",
    ["git status", "pytest -q tests", "cat .env.example", "python -m http.server", "rg TODO src"],
)
def test_ordinary_commands_are_allowed(isolated, command):
    assert _local_agent_command_denial(command, isolated) is None


def test_commands_may_not_wander_into_the_home_directory(isolated):
    home = str(Path.home()).replace("\\", "/")
    assert _local_agent_command_denial(f"ls {home}/Documents", isolated) is not None


def test_path_rules_for_local_agent_reads_and_writes(isolated):
    folder = isolated / "app"
    folder.mkdir()
    ok = folder / "src" / "main.py"
    assert _local_agent_path_denial(ok, folder, write=True) is None
    assert _local_agent_path_denial(folder / ".env", folder, write=False) == "path_references_secret_env_file"
    assert _local_agent_path_denial(folder / ".env.local", folder, write=False) == "path_references_secret_env_file"
    assert _local_agent_path_denial(folder / ".env.example", folder, write=False) is None
    assert _local_agent_path_denial(folder / "node_modules" / "x.js", folder, write=False) == "path_in_ignored_directory"
    assert _local_agent_path_denial(folder / ".git" / "config", folder, write=False) == "path_in_ignored_directory"
    assert _local_agent_path_denial(folder / "data" / "processed" / "a.csv", folder, write=False) == "path_in_generated_data"
    assert _local_agent_path_denial(folder / "idx.faiss", folder, write=True) == "write_to_generated_artifact_denied"
    assert _local_agent_path_denial(folder / "idx.faiss", folder, write=False) is None
    assert _local_agent_path_denial(isolated / "other" / "a.py", folder, write=False) == "path_outside_worker_folder"
    assert "offlimits" in _local_agent_path_denial(folder / ".ssh" / "config", folder, write=False)


def execute(tool, arguments, folder):
    manager = WorkerManager(send=lambda *a: None, owner=1, dispatch_dir=folder.parent / "dq")
    return run(manager._local_agent_execute_tool(folder, tool, arguments))


def test_agent_tools_read_write_and_list_inside_the_folder_only(isolated):
    folder = isolated / "app"
    folder.mkdir()
    assert execute("write_file", {"path": "pkg/mod.py", "content": "print('é')"}, folder)["ok"]
    assert (folder / "pkg" / "mod.py").read_text(encoding="utf-8") == "print('é')"
    read = execute("read_file", {"path": "pkg/mod.py"}, folder)
    assert read["content"] == "print('é')" and read["path"] == "pkg/mod.py"
    assert execute("list_files", {}, folder)["files"] == ["pkg/mod.py"]
    assert execute("read", {"path": "pkg/mod.py", "max_chars": 3}, folder)["truncated"] is True
    for tool, args in (
        ("write_file", {"path": "../escape.txt", "content": "x"}),
        ("read_file", {"path": "../../etc/passwd"}),
        ("write_file", {"path": ".env", "content": "KEY=1"}),
        ("write_file", {"path": "ok.txt", "content": 5}),
        ("read_file", {"path": "nope.txt"}),
        ("explode", {}),
        ("run_command", {}),
        ("run_command", {"command": "sudo reboot"}),
    ):
        assert execute(tool, args, folder)["ok"] is False, (tool, args)
    assert not (isolated / "escape.txt").exists() and not (folder / ".env").exists()


def test_list_files_skips_bulky_and_secret_paths_and_honours_the_limit(isolated):
    folder = isolated / "app"
    for name in ("a.py", "b.py", "c.py", ".env", "node_modules/x.js", ".git/HEAD"):
        target = folder / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("x", encoding="utf-8")
    listed = execute("list_files", {}, folder)
    assert listed["files"] == ["a.py", "b.py", "c.py"] and listed["truncated"] is False
    limited = execute("list_files", {"max_files": 2}, folder)
    assert len(limited["files"]) == 2 and limited["truncated"] is True


# ------------------------------------------------------------ agent loop
def script_model(monkeypatch, *replies):
    queue = list(replies)
    seen = []

    async def post(url, payload, *, timeout, api_key, attempts=3):
        seen.append(json.loads(json.dumps(payload)))
        return {"choices": [{"message": queue.pop(0)}]}

    monkeypatch.setattr(workers, "_http_post_json_retry", post)
    return seen


def tool_call(name, arguments, call_id="c1"):
    return {"tool_calls": [{"id": call_id, "function": {"name": name, "arguments": json.dumps(arguments)}}]}


def run_agent(isolated, tmp_path, monkeypatch, replies, **kwargs):
    project = isolated / "app"
    project.mkdir(exist_ok=True)
    seen = script_model(monkeypatch, *replies)
    manager, sent, _ = make_manager(tmp_path, nvidia_api_key="k", **kwargs)
    run(start_and_wait(manager, project, brain="nvidia", task="please fix the failing build")())
    return manager, sent, seen, project


def test_agent_loop_executes_tool_calls_then_reports_the_final_answer(isolated, tmp_path, monkeypatch):
    manager, sent, seen, project = run_agent(
        isolated, tmp_path, monkeypatch,
        [
            tool_call("write_file", {"path": "fix.txt", "content": "patched"}),
            {"content": "Patched fix.txt and verified."},
        ],
    )
    assert (project / "fix.txt").read_text(encoding="utf-8") == "patched"
    assert statuses(manager)[-1] == "finished"
    assert "Patched fix.txt and verified." in sent[-1]
    second_turn = seen[1]["messages"]
    assert second_turn[-1]["role"] == "tool" and second_turn[-1]["tool_call_id"] == "c1"
    assert seen[0]["tools"] and seen[0]["model"] == "openai/gpt-oss-120b"


def test_agent_accepts_json_tool_calls_written_in_prose(isolated, tmp_path, monkeypatch):
    manager, sent, seen, project = run_agent(
        isolated, tmp_path, monkeypatch,
        [
            {"content": '```json\n{"tool": "write_file", "arguments": {"path": "a.txt", "content": "A"}}\n```'},
            {"content": '{"final": "wrote a.txt"}'},
        ],
    )
    assert (project / "a.txt").read_text(encoding="utf-8") == "A"
    assert "wrote a.txt" in sent[-1]


def test_agent_stops_repeating_the_same_call_and_coaches_after_a_denial(isolated, tmp_path, monkeypatch):
    repeat = tool_call("read_file", {"path": ".env"})
    manager, sent, seen, _ = run_agent(
        isolated, tmp_path, monkeypatch, [repeat, repeat, repeat, {"content": "gave up"}],
    )
    transcript = sent[-1]
    assert "path_references_secret_env_file" in transcript
    assert "duplicate_tool_call_blocked" in transcript
    coaching = [m for m in seen[-1]["messages"] if m["role"] == "user" and "off-limits" in m["content"]]
    assert coaching


def test_agent_gives_up_after_the_step_budget(isolated, tmp_path, monkeypatch):
    replies = [tool_call("list_files", {"max_files": n + 1}, call_id=f"c{n}") for n in range(4)]
    manager, sent, seen, _ = run_agent(isolated, tmp_path, monkeypatch, replies, nvidia_max_steps=4)
    assert "Stopped after 4 nvidia agent steps." in sent[-1]
    assert len(seen) == 4


def test_agent_without_credentials_crashes_cleanly_before_any_request(isolated, tmp_path, monkeypatch):
    project = isolated / "app"
    project.mkdir()
    seen = script_model(monkeypatch)
    manager, sent, _ = make_manager(tmp_path, nvidia_api_key="")
    run(start_and_wait(manager, project, brain="nvidia")())
    assert seen == [] and statuses(manager)[-1] == "crashed"
    assert "NVIDIA_API_KEY" in sent[-1]


def test_model_failures_are_reported_as_crashes(isolated, tmp_path, monkeypatch):
    project = isolated / "app"
    project.mkdir()

    async def post(*args, **kwargs):
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr(workers, "_http_post_json_retry", post)
    manager, sent, _ = make_manager(tmp_path, nvidia_api_key="k")
    run(start_and_wait(manager, project, brain="nvidia")())
    assert statuses(manager)[-1] == "crashed" and "connection refused" in sent[-1]


# --------------------------------------------------------------- HTTP retry
def http_error(code, retry_after=None):
    headers = Message()
    if retry_after is not None:
        headers["Retry-After"] = str(retry_after)
    return urllib.error.HTTPError("http://x", code, "err", headers, None)


def retry_harness(monkeypatch, outcomes):
    delays, calls = [], []

    async def post(url, payload, *, timeout, api_key, follow_redirects=True):
        calls.append(url)
        outcome = outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    async def sleep(delay):
        delays.append(delay)

    monkeypatch.setattr(workers, "_http_post_json", post)
    monkeypatch.setattr(workers.asyncio, "sleep", sleep)
    return calls, delays


def test_rate_limited_requests_wait_and_retry(monkeypatch):
    calls, delays = retry_harness(monkeypatch, [http_error(429, 7), http_error(503), {"ok": 1}])
    assert run(workers._http_post_json_retry("u", {}, timeout=1, api_key="k")) == {"ok": 1}
    assert len(calls) == 3 and delays == [7.0, 10.0]


def test_retry_after_is_clamped_and_client_errors_are_final(monkeypatch):
    calls, delays = retry_harness(monkeypatch, [http_error(429, 9999), {"ok": 1}])
    run(workers._http_post_json_retry("u", {}, timeout=1, api_key="k"))
    assert delays == [120.0]
    calls, delays = retry_harness(monkeypatch, [http_error(400)])
    with pytest.raises(urllib.error.HTTPError):
        run(workers._http_post_json_retry("u", {}, timeout=1, api_key="k"))
    assert len(calls) == 1 and delays == []


def test_persistent_server_errors_surface_after_the_last_attempt(monkeypatch):
    calls, delays = retry_harness(monkeypatch, [http_error(502)] * 3)
    with pytest.raises(urllib.error.HTTPError):
        run(workers._http_post_json_retry("u", {}, timeout=1, api_key="k"))
    assert len(calls) == 3 and len(delays) == 2


def test_timeouts_are_retried_then_raised(monkeypatch):
    calls, _ = retry_harness(monkeypatch, [TimeoutError(), TimeoutError(), TimeoutError()])
    with pytest.raises(TimeoutError):
        run(workers._http_post_json_retry("u", {}, timeout=1, api_key="k"))
    assert len(calls) == 3


# ------------------------------------------------------------ text helpers
def test_json_objects_are_found_in_prose_and_fences():
    assert _extract_json_object('{"a": 1}') == {"a": 1}
    assert _extract_json_object('Sure!\n```json\n{"a": 2}\n```\nDone') == {"a": 2}
    assert _extract_json_object('I will call {"tool": "x"} now') == {"tool": "x"}
    assert _extract_json_object("[1, 2]") is None
    assert _extract_json_object("no json here") is None
    assert _extract_json_object("{broken") is None


def test_xml_style_tool_calls_are_parsed():
    call = _extract_xmlish_tool_call(
        "<tool_call><function=write_file><path>a.py</path>"
        "<content>\nprint(1)\n</content></function></tool_call>"
    )
    assert call == {"tool": "write_file", "arguments": {"path": "a.py", "content": "print(1)"}}
    assert _extract_xmlish_tool_call("plain text") is None


@pytest.mark.parametrize(
    "task, files, expected",
    [
        ("write a limerick about spam", None, True),
        ("Write a haiku", None, True),
        ("answer only: what is 2+2", None, True),
        ("do not inspect files, just say hi", None, True),
        ("write a poem about the repo", None, False),
        ("write a joke for README.md", None, False),
        ("write a limerick", ["a.py"], False),
        ("fix the failing test", None, False),
        ("", None, False),
    ],
)
def test_answer_only_detection(task, files, expected):
    assert _is_answer_only_worker_task(task, files) is expected
