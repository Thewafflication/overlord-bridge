"""Free models working on projects: /work, the shared pool, and operator approval."""

import asyncio
import json
import urllib.error
from types import SimpleNamespace

import pytest

import bridge
from modules import free_brain, workers
from modules.free_brain import FreeBrain, FreeUnavailable, ModelSpec, UsageLimiter
from modules.free_work import (
    FreeWork,
    list_projects,
    normalize_mode,
    resolve_project,
)
from modules.workers import WorkerManager

NV = ModelSpec("nvidia", "openai/gpt-oss-20b")
NV2 = ModelSpec("nvidia", "meta/llama-3.3-70b-instruct")
OR = ModelSpec("openrouter", "vendor/model:free")


def run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    root = tmp_path / "projects"
    root.mkdir()
    monkeypatch.setattr(workers, "_ALLOWED_ROOTS", (root,))
    monkeypatch.setattr(workers.shared_job, "notify", lambda text: False)
    return root


# --------------------------------------------------------------- projects
def test_projects_are_listed_once_with_git_repos_marked(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    for d in (a / "Alpha", a / "beta", a / ".hidden", b / "alpha", b / "Gamma"):
        d.mkdir(parents=True)
    (a / "Alpha" / ".git").mkdir()
    (a / "afile.txt").write_text("x", encoding="utf-8")
    found = list_projects([a, b, tmp_path / "missing"])
    assert [(n, g) for n, _, g in found] == [("Alpha", True), ("beta", False), ("Gamma", False)]
    assert found[0][1] == a / "Alpha"  # the first root wins a name clash


def test_project_names_resolve_case_insensitively_and_cannot_escape(tmp_path):
    root = tmp_path / "root"
    (root / "My-App").mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    assert resolve_project("my-app", [root]) == root / "My-App"
    assert resolve_project(' "My-App" ', [root]) == root / "My-App"
    assert resolve_project(str(outside), [root]) == outside  # absolute: the worker re-checks roots
    for bad in ("", "..", ".", "../outside", "My-App/..", "sub/dir", "nope", str(tmp_path / "gone")):
        assert resolve_project(bad, [root]) is None, bad


def test_approval_modes_fall_back_to_the_strict_default():
    assert [normalize_mode(m) for m in ("ALL", "commands", " none ", "bogus", None, "")] == [
        "all", "commands", "none", "all", "all", "all"]


# --------------------------------------------------------------- /work
class FakeWorkers:
    def __init__(self):
        self._running = {}
        self.accepted = []

    def _accept(self, data):
        self.accepted.append(data)
        if data["folder"].endswith("reject"):
            return
        self._running[data["name"]] = SimpleNamespace(cancel=lambda n=data["name"]: self.cancelled.append(n))

    cancelled = []


def make_work(tmp_path, **kwargs):
    root = tmp_path / "root"
    for name in ("app", "tool", "reject"):
        (root / name).mkdir(parents=True, exist_ok=True)
    messages = []
    workers_ = FakeWorkers()
    workers_.cancelled = []
    work = FreeWork(send=lambda chat, text: messages.append(text), roots=lambda: [root],
                    workers=workers_, gate=kwargs.pop("gate", None), pool=kwargs.pop("pool", None),
                    **kwargs)
    return work, workers_, messages, root


def test_work_with_no_arguments_lists_projects(tmp_path):
    work, _, messages, _ = make_work(tmp_path)
    run(work.handle(42, "/work"))
    run(work.handle(42, "/work list"))
    assert "● app" not in messages[0] and "○ app" in messages[0] and "/work <project> <task>" in messages[0]
    assert messages[0] == messages[1]


def test_work_starts_a_free_worker_and_says_what_it_will_ask(tmp_path):
    work, workers_, messages, root = make_work(tmp_path, approval="commands")
    run(work.handle(42, "/work APP fix the flaky test\nand add a regression test"))
    assert workers_.accepted == [{"name": "Free-app", "folder": str(root / "app"),
                                  "task": "fix the flaky test\nand add a regression test",
                                  "brain": "free"}]
    assert "Free-app started" in messages[-1] and "asks you before: commands" in messages[-1]
    run(work.handle(42, "/work app another task"))
    assert "already running" in messages[-1] and len(workers_.accepted) == 1


@pytest.mark.parametrize("text, expected", [
    ("/work app", "Usage: /work <project> <task>"),
    ("/work app    ", "Usage: /work <project> <task>"),
    ("/work ghost do it", "Unknown project"),
    ("/work ../x do it", "Unknown project"),
])
def test_bad_work_requests_explain_themselves(tmp_path, text, expected):
    work, workers_, messages, _ = make_work(tmp_path)
    run(work.handle(42, text))
    assert expected in messages[-1] and workers_.accepted == []


def test_a_rejected_dispatch_is_not_announced_as_started(tmp_path):
    work, workers_, messages, _ = make_work(tmp_path)
    run(work.handle(42, "/work reject do it"))
    assert workers_.accepted and messages == []  # the worker manager already told the owner


def test_status_and_stop_only_touch_free_workers(tmp_path):
    work, workers_, messages, _ = make_work(tmp_path)
    run(work.handle(42, "/work status"))
    assert messages[-1] == "No free-model workers are running."
    workers_._running.update({"Free-app": SimpleNamespace(cancel=lambda: workers_.cancelled.append("Free-app")),
                              "Free-tool": SimpleNamespace(cancel=lambda: workers_.cancelled.append("Free-tool")),
                              "Chorus": SimpleNamespace(cancel=lambda: workers_.cancelled.append("Chorus"))})
    run(work.handle(42, "/work status"))
    assert "Free-app" in messages[-1] and "Chorus" not in messages[-1]
    run(work.handle(42, "/work stop app"))
    assert workers_.cancelled == ["Free-app"]
    run(work.handle(42, "/work stop"))
    assert sorted(workers_.cancelled) == ["Free-app", "Free-app", "Free-tool"]
    run(work.handle(42, "/work stop ghost"))
    assert "No free-model worker is running for ghost" in messages[-1]


# ------------------------------------------------------------- approval
def test_natural_review_dispatches_the_listed_local_project(tmp_path, monkeypatch):
    work, manager, messages, root = make_work(tmp_path)
    project = root / "the_silver_searcher"
    project.mkdir()
    brain = FreeBrain(session_file=tmp_path / "pin", models=[NV], keys={"nvidia": "k"},
                      limiter=UsageLimiter(None, {"nvidia": (20, 0)}))
    calls = []

    async def complete(history, tools):
        calls.append((history, tools))
        return {"content": "", "tool_calls": [{"function": {
            "name": "start_project_work", "arguments": json.dumps({
                "project": project.name,
                "task": "Review the local checkout; report file/line findings without edits."})}}]}, NV, []

    monkeypatch.setattr(brain, "complete", complete)

    async def review():
        return [chunk async for chunk in brain.query(
            "Code review the silver searcher please", project_work=work, chat_id=42)]

    result = run(review())
    assert manager.accepted[0]["folder"] == str(project)
    assert "without edits" in manager.accepted[0]["task"]
    assert project.name in calls[0][1][0]["function"]["parameters"]["properties"]["project"]["enum"]
    assert "text-only" not in calls[0][0][0]["content"]
    assert "started" in result[0]
    assert brain._history[-1]["content"] == result[0]


def test_chat_dispatch_rejects_unlisted_paths_and_bad_arguments(tmp_path):
    work, manager, _, _ = make_work(tmp_path)
    for arguments in ('{}', 'null', '{', json.dumps({"project": str(tmp_path), "task": "review"})):
        result = work.execute_chat_tool(42, {"function": {
            "name": "start_project_work", "arguments": arguments}})
        assert "Invalid" in result
    assert manager.accepted == []


class Gate:
    def __init__(self, allow=True):
        self.allow, self.requests = allow, []

    async def request(self, title, detail, candidates, *, context=None):
        self.requests.append((title, detail, candidates, context))
        return self.allow


def test_commands_and_writes_ask_the_operator_in_the_default_mode(tmp_path):
    gate = Gate(True)
    work, *_ = make_work(tmp_path, gate=gate)
    assert run(work.approve(tmp_path, "run_command", {"command": "pytest -q"})) is None
    assert run(work.approve(tmp_path, "write_file", {"path": "src/a.py", "content": "x" * 500})) is None
    (run_title, run_detail, run_candidates, _), (write_title, write_detail, write_candidates, ctx) = gate.requests
    assert run_title == "Free worker: run command" and "pytest -q" in run_detail
    assert write_title == "Free worker: write file" and "(500 chars)" in write_detail
    assert write_detail.endswith("…") and write_candidates == ["src/a.py"]
    assert ctx["paths"] == ["src/a.py"] and ctx["request"]["content"] == "x" * 500


def test_denials_are_reported_with_a_reason(tmp_path):
    work, *_ = make_work(tmp_path, gate=Gate(False))
    assert run(work.approve(tmp_path, "run_command", {"command": "make"})) == "denied_by_operator"


@pytest.mark.parametrize("mode, tool, asks", [
    ("all", "write_file", True), ("all", "run_command", True),
    ("commands", "write_file", False), ("commands", "run_command", True),
    ("none", "write_file", False), ("none", "run_command", False),
])
def test_modes_decide_what_needs_approval(tmp_path, mode, tool, asks):
    gate = Gate(False)
    work, *_ = make_work(tmp_path, gate=gate, approval=mode)
    request = {"command": "make"} if tool == "run_command" else {"path": "a", "content": "b"}
    result = run(work.approve(tmp_path, tool, request))
    assert (result == "denied_by_operator") is asks and bool(gate.requests) is asks


# ------------------------------------------------- workers using the pool
def final_result(text, **extra):
    return {"content": json.dumps({"final": text, "outcome": "finished"}), **extra}


def scripted_pool(replies):
    queue = list(replies)
    seen = []

    async def complete(messages, tools):
        seen.append((json.loads(json.dumps(messages)), tools))
        message = dict(queue.pop(0))
        message["_free_model"] = message.pop("_model", "nvidia:test")
        return message

    return complete, seen


def call(name, arguments, call_id="c1"):
    return {"content": "", "tool_calls": [{"id": call_id, "function": {
        "name": name, "arguments": json.dumps(arguments)}}]}


def manager(tmp_path, completer, approver=None, **kwargs):
    sent, reports = [], []

    async def on_report(report):
        reports.append(report)

    mgr = WorkerManager(send=lambda chat, text: sent.append(text), owner=42,
                        dispatch_dir=tmp_path / "dq", report_dir=tmp_path / "rep",
                        free_completer=completer, tool_approver=approver, on_report=on_report, **kwargs)
    return mgr, sent, reports


def start(mgr, folder, **extra):
    async def scenario():
        mgr._accept({"name": "Free-app", "folder": str(folder), "task": "implement the feature",
                     "brain": "free", **extra})
        await asyncio.gather(*mgr._running.values())
        await asyncio.sleep(0)

    run(scenario())


def events(mgr):
    return [json.loads(l) for l in mgr.report_store.events_path.read_text(encoding="utf-8").splitlines()]


def test_default_free_worker_continues_past_thirty_steps(isolated, tmp_path):
    project = isolated / "long-task"
    project.mkdir()
    completer, seen = scripted_pool([
        *[call("read_file", {"path": f"file-{step}.py"}, f"call-{step}") for step in range(35)],
        final_result('Task completed after checking all files.'),
    ])
    mgr, sent, _ = manager(tmp_path, completer)
    assert mgr.free_max_steps == 0
    start(mgr, project)
    assert len(seen) == 36
    assert events(mgr)[-1]["status"] == "finished"
    assert "Task completed" in sent[-1]


def test_explicit_free_step_limit_is_reported_as_incomplete(isolated, tmp_path):
    project = isolated / "limited-task"
    project.mkdir()
    completer, seen = scripted_pool([
        call("read_file", {"path": f"file-{step}.py"}, f"call-{step}") for step in range(4)
    ])
    mgr, sent, _ = manager(tmp_path, completer, free_max_steps=4)
    start(mgr, project)
    assert len(seen) == 4
    assert events(mgr)[-1]["status"] == "incomplete"
    assert events(mgr)[-1]["exit_code"] != 0
    assert "Stopped before completion" in sent[-1]


def test_unlimited_free_worker_remains_cancellable(isolated, tmp_path):
    project = isolated / "cancel-task"
    project.mkdir()
    calls = []
    async def complete(messages, tools):
        calls.append(1)
        return call("read_file", {"path": f"file-{len(calls)}.py"}, f"call-{len(calls)}")
    mgr, _, _ = manager(tmp_path, complete)
    async def scenario():
        mgr._accept({"name": "Free-app", "folder": str(project), "task": "review", "brain": "free"})
        task = mgr._running["Free-app"]
        while len(calls) < 35:
            await asyncio.sleep(0)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        assert task.cancelled()
        assert "Free-app" not in mgr._running
    run(scenario())


def test_worker_announces_specific_actions_before_executing(isolated, tmp_path, monkeypatch):
    project = isolated / "visible-work"
    project.mkdir()
    monkeypatch.setenv("TEST_PROGRESS_SECRET_KEY", "private-progress-value")
    command = call("run_command", {"command": "git status"})
    command["content"] = "I will check the working tree before making changes. private-progress-value"
    completer, _ = scripted_pool([
        command,
        call("write_file", {"path": "src/example.py", "content": "x = 1"}, "c2"),
        final_result('Implemented the change.'),
    ])
    mgr, sent, _ = manager(tmp_path, completer)
    executed = []
    async def execute(folder, tool, arguments):
        assert any(worker in message for message in sent
                   for worker in ["Run git status" if tool == "run_command" else "Write src/example.py"])
        executed.append(tool)
        return {"ok": True, "exit_code": 0} if tool == "run_command" else {"ok": True}
    monkeypatch.setattr(mgr, "_local_agent_execute_tool", execute)
    start(mgr, project)
    assert executed == ["run_command", "write_file"]
    assert any("check the working tree" in message for message in sent)
    assert any("exit code 0" in message for message in sent)
    assert any("Working on:" in message for message in sent)
    updates = [message for message in sent if message.startswith("🛠")]
    assert any("[redacted]" in message for message in updates)
    assert not any("private-progress-value" in message for message in updates)
    assert "\\nWaiting" not in updates[0]


def test_fast_read_activity_is_batched_instead_of_spamming(isolated, tmp_path):
    project = isolated / "quick-reads"
    project.mkdir()
    completer, _ = scripted_pool([
        *[call("read_file", {"path": f"file-{step}.py"}, f"call-{step}") for step in range(20)],
        final_result('Review complete.'),
    ])
    mgr, sent, _ = manager(tmp_path, completer)
    start(mgr, project)
    updates = [message for message in sent if message.startswith("🛠")]
    assert len(updates) < 5
    assert "Review complete" in sent[-1]


def test_a_free_worker_edits_files_after_the_operator_approves(isolated, tmp_path):
    project = isolated / "app"
    project.mkdir()
    approvals = []

    async def approver(folder, tool, request):
        approvals.append((tool, request))
        return None

    completer, seen = scripted_pool([
        call("write_file", {"path": "feature.py", "content": "print('hi')"}),
        call("list_files", {}, "c2"),
        final_result("Added feature.py", _model="openrouter:vendor/m:free"),
    ])
    mgr, sent, reports = manager(tmp_path, completer, approver)
    start(mgr, project)
    assert (project / "feature.py").read_text(encoding="utf-8") == "print('hi')"
    assert approvals == [("write_file", {"path": "feature.py", "content": "print('hi')"})]  # list_files: no prompt
    assert events(mgr)[-1]["status"] == "finished"
    assert "Added feature.py" in sent[-1]
    assert events(mgr)[-1]["effective_local_agent_model"] == "nvidia:test, openrouter:vendor/m:free"
    assert seen[0][1] and seen[0][1][0]["type"] == "function"  # tools were offered
    assert reports and reports[-1]["brain"] == "free"


def test_a_refused_write_never_touches_the_disk_and_the_model_is_told(isolated, tmp_path):
    project = isolated / "app"
    project.mkdir()

    async def approver(folder, tool, request):
        return "denied_by_operator"

    completer, seen = scripted_pool([
        call("write_file", {"path": "feature.py", "content": "x"}),
        {"content": json.dumps({"final": "I could not write the file.", "outcome": "blocked"})},
    ])
    mgr, sent, _ = manager(tmp_path, completer, approver)
    start(mgr, project)
    assert not (project / "feature.py").exists()
    tool_reply = [m for m in seen[1][0] if m["role"] == "tool"][0]["content"]
    assert "denied_by_operator" in tool_reply and "content" not in json.loads(tool_reply)


def test_actions_the_rules_already_forbid_never_reach_the_operator(isolated, tmp_path):
    project = isolated / "app"
    project.mkdir()
    asked = []

    async def approver(folder, tool, request):
        asked.append(request)
        return None

    completer, _ = scripted_pool([
        call("write_file", {"path": ".env", "content": "KEY=1"}, "c1"),
        call("write_file", {"path": "../escape.txt", "content": "x"}, "c2"),
        call("run_command", {"command": "cat ~/.ssh/id_rsa"}, "c3"),
        call("run_command", {"command": "sudo reboot"}, "c4"),
        final_result('done'),
    ])
    mgr, _, _ = manager(tmp_path, completer, approver)
    start(mgr, project)
    assert asked == []
    assert not (project / ".env").exists() and not (isolated / "escape.txt").exists()


def test_reads_and_listings_never_prompt(isolated, tmp_path):
    project = isolated / "app"
    project.mkdir()
    (project / "a.txt").write_text("hello", encoding="utf-8")
    asked = []

    async def approver(folder, tool, request):
        asked.append(tool)

    completer, seen = scripted_pool([call("read_file", {"path": "a.txt"}), final_result('ok')])
    mgr, _, _ = manager(tmp_path, completer, approver)
    start(mgr, project)
    assert asked == [] and "hello" in json.dumps(seen[1][0])


def test_commands_are_approved_then_run_inside_the_project(isolated, tmp_path):
    project = isolated / "app"
    project.mkdir()
    asked = []

    async def approver(folder, tool, request):
        asked.append((tool, request["command"], folder))

    completer, seen = scripted_pool([call("run_command", {"command": "python -c \"print(6*7)\""}),
                                     final_result('42')])
    mgr, *_ = manager(tmp_path, completer, approver)
    start(mgr, project)
    assert asked and asked[0][0] == "run_command" and asked[0][2] == project.resolve()
    assert "42" in json.dumps(seen[1][0])


def test_the_free_brain_can_be_named_a_few_ways_and_needs_a_pool(isolated, tmp_path):
    project = isolated / "app"
    project.mkdir()
    completer, _ = scripted_pool([final_result('ok')])
    mgr, sent, _ = manager(tmp_path, completer)
    start(mgr, project, brain="Free-Model")
    assert events(mgr)[-1]["brain"] == "free" and events(mgr)[-1]["status"] == "finished"
    lonely, sent, _ = manager(tmp_path / "x", None)
    start(lonely, project)
    assert events(lonely)[-1]["reason"] == "free_pool_unavailable" and "not configured" in sent[-1]


def test_pool_exhaustion_is_reported_as_a_crash_with_the_reason(isolated, tmp_path):
    project = isolated / "app"
    project.mkdir()

    async def exhausted(messages, tools):
        raise FreeUnavailable(["nvidia:x (rate limited, retry in 1m)"], 60)

    mgr, sent, _ = manager(tmp_path, exhausted)
    start(mgr, project)
    assert events(mgr)[-1]["status"] == "crashed" and "Next model free in about 60s" in sent[-1]


def test_extra_roots_let_workers_use_projects_outside_the_default_zones(isolated, tmp_path):
    outside = tmp_path / "repos" / "app"
    outside.mkdir(parents=True)
    completer, _ = scripted_pool([final_result('ok')])
    refused, sent, _ = manager(tmp_path, completer)
    start(refused, outside)
    assert "bad/missing folder" in sent[-1]
    allowed, sent, _ = manager(tmp_path / "y", completer, extra_roots=(tmp_path / "repos",))
    completer2, _ = scripted_pool([final_result('ok')])
    allowed.free_completer = completer2
    start(allowed, outside)
    assert events(allowed)[-1]["status"] == "finished"
    sibling = tmp_path / "repos-evil"
    sibling.mkdir()
    assert workers._under_allowed_root(str(sibling), (tmp_path / "repos",)) is None


# ----------------------------------------------------------- the model pool
def reply(message):
    return 200, {}, {"choices": [{"message": message}]}


def make_pool(tmp_path, monkeypatch, responses, models=(NV, NV2), **kwargs):
    queue, calls, sleeps = list(responses), [], []

    async def fake_post(url, payload, api_key, timeout):
        calls.append(payload)
        item = queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    async def fake_sleep(seconds):
        sleeps.append(seconds)

    monkeypatch.setattr(free_brain, "_post", fake_post)
    limiter = UsageLimiter(None, kwargs.pop("limits", {"nvidia": (20, 0)}), kwargs.pop("clock", lambda: 1_800_000_000.0))
    pool = FreeBrain(session_file=tmp_path / "pin", models=list(models), keys={"nvidia": "k", "openrouter": "k"},
                     limiter=limiter, sleep=fake_sleep, **kwargs)
    pool.calls, pool.sleeps = calls, sleeps
    return pool


TOOLS = [{"type": "function", "function": {"name": "list_files", "parameters": {"type": "object"}}}]


def test_tool_calls_come_back_intact_and_tools_are_sent(tmp_path, monkeypatch):
    call_msg = {"role": "assistant", "content": None,
                "tool_calls": [{"id": "c9", "function": {"name": "list_files", "arguments": "{}"}}]}
    pool = make_pool(tmp_path, monkeypatch, [reply(call_msg)])
    message, spec, skipped = run(pool.complete([{"role": "user", "content": "go"}], TOOLS))
    assert spec == NV and skipped == []
    assert message["tool_calls"][0]["id"] == "c9" and message["content"] == ""
    sent = pool.calls[0]
    assert sent["tools"] == TOOLS and sent["tool_choice"] == "auto"
    assert sent["temperature"] == 1.0  # the model's published sampling wins over our default


def test_the_pool_falls_back_between_models_for_agent_turns(tmp_path, monkeypatch):
    pool = make_pool(tmp_path, monkeypatch, [(429, {"retry-after": "30"}, {}), reply({"content": "from llama"})])
    message, spec, skipped = run(pool.complete([{"role": "user", "content": "go"}], TOOLS))
    assert spec == NV2 and message["content"] == "from llama" and "rate limited" in skipped[0]


def test_patience_waits_out_a_short_rate_limit_and_then_succeeds(tmp_path, monkeypatch):
    clock = [1_800_000_000.0]
    pool = make_pool(tmp_path, monkeypatch, [reply({"content": "after the wait"})], models=(NV,),
                     limits={"nvidia": (1, 0)}, clock=lambda: clock[0], max_wait=0)
    pool.limiter.record(NV)

    async def fake_sleep(seconds):
        pool.sleeps.append(seconds)
        clock[0] += seconds + 1

    pool._sleep = fake_sleep
    message, spec, _ = run(pool.complete([{"role": "user", "content": "go"}], None, patience=120))
    assert message["content"] == "after the wait" and pool.sleeps and pool.sleeps[0] > 50


def test_without_enough_patience_the_pool_gives_up_with_a_reason(tmp_path, monkeypatch):
    pool = make_pool(tmp_path, monkeypatch, [], models=(NV,), limits={"nvidia": (1, 0)}, max_wait=0)
    pool.limiter.record(NV)
    for patience in (0, 10):
        with pytest.raises(FreeUnavailable) as info:
            run(pool.complete([{"role": "user", "content": "go"}], None, patience=patience))
        assert "1/min limit" in str(info.value) and info.value.soonest > 50
    assert pool.sleeps == []


def test_with_no_usable_model_it_fails_immediately(tmp_path, monkeypatch):
    pool = make_pool(tmp_path, monkeypatch, [], models=())
    with pytest.raises(FreeUnavailable):
        run(pool.complete([{"role": "user", "content": "go"}], None, patience=60))


def test_openrouter_models_must_advertise_tools_for_agent_work_only(tmp_path, monkeypatch):
    catalog = {"data": [{"id": OR.model, "pricing": {"prompt": "0", "completion": "0"},
                         "supported_parameters": ["max_tokens"]}]}

    async def fake_get(url, *, timeout, api_key):
        return catalog

    monkeypatch.setattr(free_brain, "_http_get_json", fake_get)
    pool = make_pool(tmp_path, monkeypatch, [reply({"content": "chat is fine"})], models=(OR,),
                     openrouter_enabled=True, limits={"openrouter": (10, 10)})
    message, _, _ = run(pool.complete([{"role": "user", "content": "hi"}], None))
    assert message["content"] == "chat is fine"
    with pytest.raises(FreeUnavailable) as info:
        run(pool.complete([{"role": "user", "content": "work"}], TOOLS))
    assert "not admitted as free" in str(info.value) and len(pool.calls) == 1


def test_chat_history_is_untouched_by_agent_turns(tmp_path, monkeypatch):
    pool = make_pool(tmp_path, monkeypatch, [reply({"content": "agent step"})])
    run(pool.complete([{"role": "user", "content": "work"}], TOOLS))
    assert pool._history == [] and pool.session_id is None


# -------------------------------------------------------------- the bridge
def test_the_bridge_shares_the_active_free_brain_or_builds_a_standby(monkeypatch):
    built = []

    class Standby:
        name = "free"

        async def connect(self):
            built.append("connected")

    monkeypatch.setattr(bridge, "build_brain", lambda gate, name: Standby())
    instance = bridge.Bridge.__new__(bridge.Bridge)
    instance.gate = None
    instance.brain = SimpleNamespace(name="free")
    assert run(instance._free_pool()) is instance.brain and built == []
    instance.brain = SimpleNamespace(name="claude")
    first = run(instance._free_pool())
    assert run(instance._free_pool()) is first and built == ["connected"]  # one standby, reused


def test_work_is_routed_from_the_main_loop():
    instance = bridge.Bridge.__new__(bridge.Bridge)
    seen = []

    async def handle(chat_id, text):
        seen.append((chat_id, text))

    instance.free_work = SimpleNamespace(handle=handle)
    instance.telegram = SimpleNamespace(send=lambda *a: None)
    run(instance._dispatch_inbound(42, "/work app do it"))
    assert seen == [(42, "/work app do it")]


def test_project_roots_use_the_workspace_unless_it_is_the_whole_home(tmp_path, monkeypatch):
    monkeypatch.setattr(bridge, "PROJECT_ROOTS", "")
    monkeypatch.setattr(bridge, "PROJECT_FOLDERS", "")
    repos = tmp_path / "repos"
    repos.mkdir()
    zone = tmp_path / "zone"
    zone.mkdir()
    monkeypatch.setattr(bridge, "_ALLOWED_ROOTS", (zone, tmp_path / "missing"))
    monkeypatch.setattr(bridge, "PROJECTS_ROOT", "")
    monkeypatch.setattr(bridge, "CWD", str(repos))
    assert bridge.project_roots() == [repos, zone]
    assert bridge.worker_extra_roots() == (repos,)
    monkeypatch.setattr(bridge, "CWD", str(bridge.Path.home()))
    assert bridge.project_roots() == [zone]
    assert bridge.worker_extra_roots() == ()
    monkeypatch.setattr(bridge, "PROJECTS_ROOT", str(repos))
    assert bridge.project_roots() == [repos, zone]


def test_the_help_text_lists_work_and_the_telegram_layer_forwards_it():
    from modules import telegram_handler

    assert "/work" in bridge.HELP_TEXT and "work" in telegram_handler.COMMANDS


def test_empty_worker_response_recovers_after_unknown_search(isolated, tmp_path):
    project = isolated / 'recovery'
    project.mkdir()
    (project / 'source.py').write_text('pending request\n')
    completer, seen = scripted_pool([
        call('unavailable_search', {'query': 'pending'}),
        {'content': ''},
        call('search_file', {'path': 'source.py', 'query': 'pending'}),
        final_result('Inspected the pending request on line 1; no changes required.'),
    ])
    mgr, sent, _ = manager(tmp_path, completer)
    start(mgr, project)
    assert events(mgr)[-1]['status'] == 'finished'
    assert len(seen) == 4
    assert 'no changes required' in sent[-1]
    assert any('task is still active' in str(m) for m in seen[2][0])


def test_repeated_empty_worker_responses_are_incomplete(isolated, tmp_path):
    project = isolated / 'empty'
    project.mkdir()
    completer, seen = scripted_pool([{'content': ''}] * 3)
    mgr, sent, _ = manager(tmp_path, completer)
    start(mgr, project)
    assert len(seen) == 3
    assert events(mgr)[-1]['status'] == 'incomplete'
    assert events(mgr)[-1]['exit_code'] == 1
    assert 'Stopped before completion' in sent[-1] and '✅ Finished' not in sent[-1]


def test_empty_json_final_is_not_success(isolated, tmp_path):
    project = isolated / 'empty-final'
    project.mkdir()
    completer, _ = scripted_pool([{'content': '{"final": ""}'}])
    mgr, sent, _ = manager(tmp_path, completer)
    start(mgr, project)
    assert events(mgr)[-1]['status'] == 'incomplete'


def test_plan_only_worker_ending_returns_to_tools_before_completion(isolated, tmp_path):
    project = isolated / 'unfinished-plan'
    project.mkdir()
    completer, seen = scripted_pool([
        {'content': "Now I'll implement the feature."},
        call('write_file', {'path': 'feature.py', 'content': 'implemented = True'}),
        final_result('Implemented feature.py'),
    ])
    mgr, sent, _ = manager(tmp_path, completer)
    start(mgr, project)
    assert (project / 'feature.py').read_text() == 'implemented = True'
    assert events(mgr)[-1]['status'] == 'finished'
    assert any('Completion checkpoint' in str(m) for m in seen[1][0])


def test_worker_ignoring_completion_checkpoint_is_incomplete(isolated, tmp_path):
    project = isolated / 'ignored-checkpoint'
    project.mkdir()
    completer, seen = scripted_pool([
        {'content': "I'll implement it now."},
        {'content': "I'll start by editing."},
    ])
    mgr, sent, _ = manager(tmp_path, completer)
    start(mgr, project)
    assert len(seen) == 2 and events(mgr)[-1]['status'] == 'incomplete'
    assert '✅ Finished' not in sent[-1]


@pytest.mark.parametrize('mode, asks', [('all', True), ('commands', False), ('none', False)])
def test_edit_tool_uses_write_approval_policy_and_preview(tmp_path, mode, asks):
    gate = Gate(False)
    work, *_ = make_work(tmp_path, gate=gate, approval=mode)
    result = run(work.approve(tmp_path, 'edit_file', {'path': 'large.py', 'old_text': 'old', 'new_text': 'new'}))
    assert (result == 'denied_by_operator') is asks
    if asks:
        title, detail, candidates, context = gate.requests[0]
        assert title == 'Free worker: edit file'
        assert 'old' in detail and 'new' in detail and candidates == ['large.py']
        assert context['paths'] == ['large.py']
    else:
        assert not gate.requests


@pytest.mark.parametrize('message', [
    {'content': 'Now I will implement the feature'},
    {'content': '', 'tool_calls': [{'id': 'cut-off', 'function': {'name': 'write_file', 'arguments': '{"path":'}}]},
])
def test_truncated_agent_responses_are_discarded_before_fallback(tmp_path, monkeypatch, message):
    truncated = reply(message)
    truncated[2]['choices'][0]['finish_reason'] = 'length'
    pool = make_pool(tmp_path, monkeypatch, [truncated, reply({'content': 'valid fallback'})])
    result, spec, skipped = run(pool.complete([{'role': 'user', 'content': 'implement it'}], TOOLS))
    assert spec == NV2 and result['content'] == 'valid fallback'
    assert not result.get('tool_calls') and 'truncated' in skipped[0]


def test_worker_response_override_is_per_request_and_preserves_chat_budget(tmp_path, monkeypatch):
    pool = make_pool(tmp_path, monkeypatch, [reply({'content': 'worker'}), reply({'content': 'chat'})])
    run(pool.complete([{'role': 'user', 'content': 'work'}], TOOLS, max_tokens=8192))
    run(pool.complete([{'role': 'user', 'content': 'chat'}]))
    assert pool.calls[0]['max_tokens'] == 4096  # GPT-OSS published model cap
    assert pool.calls[1]['max_tokens'] == pool.max_tokens == 2048
    assert pool._payload(OR, [], TOOLS, max_tokens=8192)['max_tokens'] == 8192
    assert pool._payload(OR, [])['max_tokens'] == 2048


def test_project_work_passes_its_budget_without_mutating_shared_pool(tmp_path):
    calls = []
    async def complete(messages, tools, **kwargs):
        calls.append(kwargs)
        return {'content': 'worker'}, NV, []
    async def pool():
        return SimpleNamespace(complete=complete)
    work, *_ = make_work(tmp_path, pool=pool, response_tokens=12000)
    result = run(work.complete([], TOOLS))
    assert result['_free_model'] == NV.key
    assert calls == [{'patience': 120.0, 'max_tokens': 12000}]
