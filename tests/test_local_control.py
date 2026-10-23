import asyncio
import json
import time
import uuid
from pathlib import Path
from types import SimpleNamespace

import bridge
from modules import local_control
from tests.test_bridge_turn_control import BlockingBrain, make_bridge


async def start_server(tmp_path, handler):
    shutdown = asyncio.Event()
    task = asyncio.create_task(local_control.serve(tmp_path, handler, shutdown, poll_interval=0.01))
    service = tmp_path / "local-control/service.json"
    for _ in range(100):
        if service.exists():
            return shutdown, task, json.loads(service.read_text())
        await asyncio.sleep(0.01)
    raise AssertionError("control service not ready")


def test_local_stop_acknowledges_worker_cleanup_and_leaves_bridge_running(tmp_path):
    async def scenario():
        instance = make_bridge(BlockingBrain())
        cleaned = asyncio.Event()
        async def worker():
            try:
                await asyncio.Event().wait()
            finally:
                await asyncio.sleep(0.03)
                cleaned.set()
        worker_task = asyncio.create_task(worker())
        instance.workers = SimpleNamespace(_running={"Free-project": worker_task})
        await asyncio.sleep(0)
        shutdown, server, _ = await start_server(tmp_path, instance._local_control_action)
        try:
            before = await asyncio.to_thread(local_control.request, tmp_path, "status", 2)
            assert before['ok'] and before['state']['workers'] == ['Free-project']
            result = await asyncio.to_thread(local_control.request, tmp_path, "stop", 2)
            assert result['ok'] and result['stopped'] and result['state']['idle']
            assert cleaned.is_set() and worker_task.done() and not shutdown.is_set()
            assert not server.done()
        finally:
            shutdown.set()
            await server
        assert not (tmp_path / 'local-control/service.json').exists()
    asyncio.run(scenario())


def test_local_stop_does_not_claim_success_when_cleanup_is_pending(tmp_path, monkeypatch):
    async def scenario():
        instance = make_bridge(BlockingBrain())
        release = asyncio.Event()
        async def worker():
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                await release.wait()
        task = asyncio.create_task(worker())
        instance.workers = SimpleNamespace(_running={'pending': task})
        await asyncio.sleep(0)
        monkeypatch.setattr(bridge, 'STOP_CLEANUP_TIMEOUT', 0.02)
        shutdown, server, _ = await start_server(tmp_path, instance._local_control_action)
        try:
            result = await asyncio.to_thread(local_control.request, tmp_path, 'stop', 2)
            assert result['ok'] is False and result['stopped'] is False
            assert result['error'] == 'cleanup_pending' and result['state']['workers'] == ['pending']
            release.set()
            await task
            status = await asyncio.to_thread(local_control.request, tmp_path, 'status', 2)
            assert status['state']['idle']
        finally:
            release.set()
            shutdown.set()
            await server
    asyncio.run(scenario())


def test_expired_stale_and_unsupported_requests_never_execute(tmp_path):
    async def scenario():
        called = []
        async def handler(action):
            called.append(action)
            return {'ok': True}
        shutdown, server, service = await start_server(tmp_path, handler)
        root = tmp_path / 'local-control'
        try:
            cases = [(service['instance'], time.time() - 1, 'stop', 'expired_control_request'),
                     ('old-instance', time.time() + 5, 'stop', 'stale_bridge_instance'),
                     (service['instance'], time.time() + 5, 'run_command', 'invalid_control_request')]
            for instance, expiry, action, error in cases:
                identity = uuid.uuid4().hex
                local_control._write(root / 'requests' / (identity + '.json'), {
                    'id': identity, 'instance': instance, 'expires_at': expiry, 'action': action})
                reply = root / 'responses' / (identity + '.json')
                for _ in range(100):
                    if reply.exists():
                        break
                    await asyncio.sleep(0.01)
                assert json.loads(reply.read_text())['error'] == error
            assert not called
        finally:
            shutdown.set()
            await server
    asyncio.run(scenario())


def test_control_timeout_is_failure_and_removes_unprocessed_request(tmp_path):
    root = tmp_path / 'local-control'
    local_control._write(root / 'service.json', {'protocol': 1, 'instance': 'dead-service'})
    result = local_control.request(tmp_path, 'stop', 0.1)
    assert result['ok'] is False and result['error'] == 'control_timeout'
    assert not list((root / 'requests').glob('*.json'))


def test_control_unavailable_and_invalid_action_do_not_start_a_brain(tmp_path):
    assert local_control.request(tmp_path, 'status')['error'] == 'control_unavailable'
    assert local_control.request(tmp_path, 'execute')['error'] == 'invalid_control_request'
    assert local_control.main(['status', '--run-dir', str(tmp_path)]) == 2


def test_local_stop_cleans_up_real_worker_command_tree(tmp_path):
    from tests.test_workers_runtime import make_manager
    async def scenario():
        project = tmp_path / 'command'
        project.mkdir()
        manager, _, _ = make_manager(tmp_path)
        code = ("import subprocess, sys, time\n"
                "from pathlib import Path\n"
                "subprocess.Popen([sys.executable, '-c', \"import time; from pathlib import Path; time.sleep(2); Path('orphan.txt').write_text('alive')\"])\n"
                "Path('ready.txt').write_text('started')\n"
                "time.sleep(60)\n")
        task = asyncio.create_task(manager._local_agent_execute_tool(project, 'run_python', {'code': code}))
        instance = make_bridge(BlockingBrain())
        instance.workers = SimpleNamespace(_running={'command-test': task})
        shutdown, server, _ = await start_server(tmp_path, instance._local_control_action)
        try:
            for _ in range(300):
                if (project / 'ready.txt').exists():
                    break
                await asyncio.sleep(0.01)
            assert (project / 'ready.txt').exists()
            result = await asyncio.to_thread(local_control.request, tmp_path, 'stop', 15)
            assert result['ok'] and result['state']['idle'] and task.cancelled()
            await asyncio.sleep(2.2)
            assert not (project / 'orphan.txt').exists()
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            shutdown.set()
            await server
    asyncio.run(scenario())


def test_local_stop_also_interrupts_foreground_turn(tmp_path):
    async def scenario():
        brain = BlockingBrain()
        instance = make_bridge(brain)
        instance._start_turn(42, 'control-test')
        await brain.started.wait()
        shutdown, server, _ = await start_server(tmp_path, instance._local_control_action)
        try:
            result = await asyncio.to_thread(local_control.request, tmp_path, 'stop', 2)
            assert result['ok'] and result['state']['idle'] and brain.cancelled.is_set()
        finally:
            shutdown.set()
            await server
    asyncio.run(scenario())


def test_replayed_request_id_does_not_stop_new_work_twice(tmp_path):
    async def scenario():
        calls = []
        async def handler(action):
            calls.append(action)
            return {'ok': True, 'stopped': True}
        shutdown, server, service = await start_server(tmp_path, handler)
        identity = uuid.uuid4().hex
        path = tmp_path / 'local-control/requests' / (identity + '.json')
        payload = {'id': identity, 'instance': service['instance'], 'action': 'stop', 'expires_at': time.time() + 5}
        try:
            for _ in range(2):
                local_control._write(path, payload)
                for _ in range(100):
                    if not path.exists():
                        break
                    await asyncio.sleep(0.01)
                assert not path.exists()
            assert calls == ['stop']
        finally:
            shutdown.set()
            await server
    asyncio.run(scenario())
