import asyncio
import json
from types import SimpleNamespace

import pytest

import bridge
from modules.scheduled_tasks import ScheduledTasks, duration, timestamp


@pytest.fixture
def scheduler(tmp_path):
    now = [1800000000.0]
    started, messages = [], []
    busy = [False]
    instance = ScheduledTasks(tmp_path / "schedules.json", clock=lambda: now[0],
        send=lambda chat, text: messages.append((chat, text)),
        start=lambda chat, text: started.append((chat, text)) or True, busy=lambda: busy[0])
    return instance, now, started, messages, busy


def create(instance, command):
    instance.command(command)
    return next(reversed(instance.tasks))


def test_one_shot_survives_restart_and_dispatches_only_once(scheduler):
    instance, now, started, _, _ = scheduler
    key = create(instance, "/schedule in 2m Review the project")
    instance.tick(42)
    assert not started
    now[0] += 121
    reloaded = ScheduledTasks(instance.path, clock=lambda: now[0], send=instance.send,
                              start=instance.start, busy=instance.busy)
    reloaded.tick(42)
    reloaded.tick(42)
    assert len(started) == 1 and "Review the project" in started[0][1]
    assert reloaded.tasks[key]["state"] == "dispatched"
    assert json.loads(instance.path.read_text())["tasks"][key]["last_dispatch"] == now[0]


def test_busy_defers_and_recurring_missed_runs_do_not_burst(scheduler):
    instance, now, started, _, busy = scheduler
    key = create(instance, "/schedule every 1h Check status")
    now[0] += 3600 * 10 + 30
    busy[0] = True
    instance.tick(42)
    assert not started
    busy[0] = False
    instance.tick(42)
    instance.tick(42)
    assert len(started) == 1
    assert now[0] < instance.tasks[key]["next_run"] <= now[0] + 3600


def test_pause_resume_run_remove_and_list(scheduler):
    instance, now, started, _, _ = scheduler
    key = create(instance, "/schedule every 1h Inspect build")
    instance.command(f"/schedule pause {key}")
    now[0] += 7200
    instance.tick(42)
    assert not started and "paused" in instance.command("/schedule")
    instance.command(f"/schedule resume {key}")
    assert instance.tasks[key]["next_run"] == now[0] + 3600
    instance.command(f"/schedule run {key}")
    instance.tick(42)
    assert len(started) == 1
    instance.command(f"/schedule remove {key}")
    assert not instance.tasks


@pytest.mark.parametrize("value", ["0m", "1s", "forever", "-2h", "999999999999d", "367d"])
def test_invalid_durations(value):
    with pytest.raises(ValueError):
        duration(value)


def test_absolute_time_requires_offset_and_future(scheduler):
    instance, _, _, _, _ = scheduler
    with pytest.raises(ValueError, match="offset"):
        instance.command("/schedule at 2030-01-01T09:00 Review")
    with pytest.raises(ValueError, match="future"):
        instance.command("/schedule at 2000-01-01T09:00Z Review")
    key = create(instance, "/schedule at 2030-01-01T09:00-06:00 Review")
    assert instance.tasks[key]["next_run"] == timestamp("2030-01-01T15:00Z")


def test_corrupt_storage_preserved_and_disabled(scheduler):
    instance, _, started, _, _ = scheduler
    instance.path.write_text('{"version": 8}')
    broken = ScheduledTasks(instance.path, send=instance.send, start=instance.start, busy=instance.busy)
    assert broken.load_error
    broken.tick(42)
    with pytest.raises(ValueError):
        broken.command("/schedule in 1m task")
    assert not started and instance.path.read_text() == '{"version": 8}'


def test_write_failure_never_starts_or_changes_memory(scheduler, monkeypatch):
    instance, now, started, _, _ = scheduler
    key = create(instance, "/schedule in 1m task")
    now[0] += 61
    monkeypatch.setattr(type(instance.path), "replace", lambda *args: (_ for _ in ()).throw(OSError("disk full")))
    with pytest.raises(OSError):
        instance.tick(42)
    assert not started and instance.tasks[key]["state"] == "active"


def test_dispatch_failure_pauses_automatic_retries(scheduler):
    instance, now, started, messages, _ = scheduler
    key = create(instance, "/schedule every 1m task")
    instance.start = lambda *args: False
    now[0] += 61
    instance.tick(42)
    now[0] += 61
    instance.tick(42)
    assert not started and instance.tasks[key]["state"] == "failed"
    assert "failed to dispatch" in messages[-1][1]


def test_bridge_routes_schedule_command_and_executes_with_normal_turn(scheduler):
    instance, _, started, _, _ = scheduler
    app = bridge.Bridge.__new__(bridge.Bridge)
    records = []
    app.chat_mirror = SimpleNamespace(append=lambda *args, **kwargs: records.append((args, kwargs)))
    app.scheduled_tasks = instance
    app.telegram = SimpleNamespace(send=instance.send)
    asyncio.run(app._dispatch_inbound(42, "/schedule in 1m inspect files"))
    assert len(instance.tasks) == 1
    app._active_turn_task = None
    app._start_turn = instance.start
    assert app._start_scheduled_turn(42, "Scheduled task: inspect files")
    assert started == [(42, "Scheduled task: inspect files")]
    assert records[-1][1]["source"] == "schedule"


def test_commands_are_discoverable():
    from modules.telegram_handler import COMMANDS, COMMAND_DESCRIPTIONS
    assert "schedule" in COMMANDS
    assert COMMAND_DESCRIPTIONS["schedule"]
    assert "/schedule" in bridge.HELP_TEXT


def test_scheduled_work_waits_for_background_workers_too():
    app = bridge.Bridge.__new__(bridge.Bridge)
    app._active_turn_task = None
    app.workers = SimpleNamespace(_running={'Free-project': object()})
    app._start_turn = lambda *args: pytest.fail('must not start another scheduled turn')
    assert app._scheduled_work_is_active()
    assert not app._start_scheduled_turn(42, 'next scheduled project')
    app.workers._running.clear()
    assert not app._scheduled_work_is_active()


def test_scheduler_starts_actual_bridge_turn_and_waits_for_it(scheduler):
    instance, now, _, _, _ = scheduler

    async def scenario():
        app = bridge.Bridge.__new__(bridge.Bridge)
        app._active_turn_task = None
        app._write_console_status = lambda: None
        app.chat_mirror = SimpleNamespace(append=lambda *args, **kwargs: None)
        app.telegram = SimpleNamespace(send=instance.send)
        release = asyncio.Event()
        received = []

        async def turn(chat, text):
            received.append((chat, text))
            await release.wait()

        app._handle_turn = turn
        instance.start = app._start_scheduled_turn
        instance.busy = app._turn_is_active
        first = create(instance, "/schedule in 1m First task")
        second = create(instance, "/schedule in 1m Second task")
        now[0] += 61
        instance.tick(42)
        await asyncio.sleep(0)
        instance.tick(42)
        assert len(received) == 1 and "First task" in received[0][1]
        assert instance.tasks[first]["state"] == "dispatched"
        assert instance.tasks[second]["state"] == "active"
        release.set()
        await app._active_turn_task
        instance.tick(42)
        await app._active_turn_task
        assert len(received) == 2 and "Second task" in received[1][1]

    asyncio.run(scenario())


def test_watch_continues_after_poll_failure_and_cancels(scheduler, monkeypatch):
    instance, _, _, _, _ = scheduler
    calls = []

    def tick(chat):
        calls.append(chat)
        if len(calls) == 1:
            raise OSError("temporary storage failure")

    async def sleep(_):
        if len(calls) >= 2:
            raise asyncio.CancelledError

    instance.tick = tick
    monkeypatch.setattr("modules.scheduled_tasks.asyncio.sleep", sleep)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(instance.watch(42))
    assert calls == [42, 42]


@pytest.mark.parametrize('state', ['active','paused','dispatched','failed'])
def test_edit_preserves_schedule_identity_timing_state_and_restart(scheduler,state):
    instance,now,started,_,busy=scheduler
    key=create(instance,'/schedule every 2h Old worker instruction')
    instance.tasks[key]['state']=state
    instance.tasks[key]['last_dispatch']=now[0]-100
    before=dict(instance.tasks[key]);now[0]+=37;busy[0]=True
    prompt='/work project Repair the known failure.\nPreserve "quoted" arguments and commit only validated work.'
    response=instance.command(f'/schedule edit {key} {prompt}')
    assert 'timing and state unchanged' in response
    assert instance.tasks[key]=={**before,'prompt':prompt}
    assert len(instance.tasks)==1 and not started
    loaded=ScheduledTasks(instance.path,clock=lambda:now[0],send=instance.send,start=instance.start,busy=instance.busy)
    assert loaded.tasks==instance.tasks


def test_edit_changes_next_run_without_retargeting_active_work(scheduler):
    instance,now,started,_,busy=scheduler
    key=create(instance,'/schedule every 1h Original task')
    now[0]+=3600;instance.tick(42)
    assert started[0][1].split('\n',1)[1]=='Original task'
    before=dict(instance.tasks[key]);busy[0]=True
    instance.command(f'/schedule edit {key} Corrected concrete task')
    instance.tick(42)
    assert len(started)==1 and instance.tasks[key]=={**before,'prompt':'Corrected concrete task'}
    now[0]+=3600;busy[0]=False;instance.tick(42)
    assert [text.split('\n',1)[1] for _,text in started]==['Original task','Corrected concrete task']
    assert len(instance.tasks)==1


def test_invalid_edit_does_not_change_storage_or_memory(scheduler):
    instance,_,_,_,_=scheduler
    key=create(instance,'/schedule every 2h Existing task')
    before=instance.path.read_bytes();original=dict(instance.tasks[key])
    instance.command(f'/schedule edit {key}')
    instance.command(f'/schedule edit {key}   ')
    instance.handle(42,'/schedule edit missing New task')
    assert instance.tasks[key]==original and instance.path.read_bytes()==before


def test_failed_edit_keeps_prior_task_and_file(scheduler,monkeypatch):
    from pathlib import Path
    instance,_,_,_,_=scheduler
    key=create(instance,'/schedule every 2h Original task')
    before=instance.path.read_bytes();original=dict(instance.tasks[key])
    def fail_replace(self,target):
        raise OSError('fixture storage failure')
    monkeypatch.setattr(Path,'replace',fail_replace)
    with pytest.raises(OSError):
        instance.command(f'/schedule edit {key} Corrected task')
    assert instance.tasks[key]==original and instance.path.read_bytes()==before
