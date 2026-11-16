import asyncio
import json
from pathlib import Path
import sqlite3

import pytest

from modules import worker_memory, workers
from modules.worker_memory import ProjectMemory, source_hash
from modules.worker_progress import ProgressWatch


def store(tmp_path, name='project'):
    project = tmp_path / name
    project.mkdir(exist_ok=True)
    allowed = lambda p: p.resolve().is_relative_to(project.resolve()) and p.name != '.env'
    return ProjectMemory(tmp_path / 'reports', project, allowed)


def record_source(memory, text='needle source\n' * 1000):
    (memory.project / 'source.py').write_text(text, encoding='utf-8')
    result = {'ok': True, 'path': 'source.py', 'content': text,
              'source_sha256': source_hash(text), 'start_line': 1, 'next_line': None}
    identity = memory.record('read_file', {'path': 'source.py'}, result, run='run-1', step=4)
    return identity, text


def test_memory_survives_restart_with_search_paging_and_source_freshness(tmp_path):
    memory = store(tmp_path)
    identity, text = record_source(memory)
    restarted = store(tmp_path)
    result = restarted.search('needle')
    assert result['stored_entries'] == 1 and result['entries'][0]['id'] == identity
    assert result['entries'][0]['freshness'] == 'not_checked'
    pages, offset = [], 0
    while True:
        page = restarted.read(identity, offset, 701)
        assert page['freshness'] == 'unchanged'
        assert page['run'] == 'run-1' and page['step'] == 4
        assert len(page['content']) <= 701
        pages.append(page['content'])
        offset = page['next_offset']
        if offset is None:
            break
    assert json.loads(''.join(pages))['result']['content'] == text
    (memory.project / 'source.py').write_text('updated source', encoding='utf-8')
    assert restarted.read(identity)['freshness'] == 'changed'
    (memory.project / 'source.py').unlink()
    assert restarted.read(identity)['freshness'] == 'unavailable'


def test_project_scope_policy_and_symlink_cannot_expose_other_memory(tmp_path):
    a, b = store(tmp_path, 'a'), store(tmp_path, 'b')
    identity, _ = record_source(a)
    assert b.search()['entries'] == []
    assert not b.read(identity)['ok']
    a.allowed = lambda p: False
    assert a.search()['entries'] == []
    assert not a.read(identity)['ok']


def test_memory_redacts_and_labels_historical_commands_and_assessments(tmp_path, monkeypatch):
    memory = store(tmp_path)
    secret = 'not-a-real-secret-123456'
    monkeypatch.setenv('OVL_TEST_API_KEY', secret)
    command = memory.record('run_command', {'command': 'echo ' + secret},
                            {'ok': True, 'exit_code': 0, 'stdout': secret, 'stderr': ''})
    assessment = memory.record('update_plan', {}, {'ok': True, 'plan': {'explanation': 'unverified finding'}})
    page = memory.read(command, max_chars=6000)
    assert page['kind'] == 'command' and page['freshness'] == 'historical'
    assert secret not in json.dumps(page) and '[redacted]' in page['content']
    assert memory.read(assessment)['kind'] == 'assessment'
    assert memory.record('memory_read', {}, page) is None
    memory.record('update_plan', {}, {'ok': True, 'plan': {'plan': [
        {'step': 'Repair the observed compiler failure', 'status': 'in_progress'}]}})
    assert 'Repair the observed compiler failure' in memory.index()
    assert len(memory.index()) < 1500


def test_dedup_and_bounded_retention_are_disclosed(tmp_path, monkeypatch):
    monkeypatch.setattr(worker_memory, 'MAX_ENTRIES', 2)
    memory = store(tmp_path)
    identity, _ = record_source(memory, 'original')
    again, _ = record_source(memory, 'original')
    assert identity == again and memory.search()['stored_entries'] == 1
    for n in range(4):
        memory.record('run_command', {'command': str(n)}, {'ok': True, 'stdout': str(n)})
    result = memory.search()
    assert result['stored_entries'] == 2 and result['evicted_entries'] == 3
    assert not memory.read(identity)['ok']


def test_corrupt_memory_is_explicit_and_never_replaces_current_result(tmp_path):
    memory = store(tmp_path)
    memory.directory.mkdir(parents=True)
    memory.path.write_bytes(b'corrupt memory file')
    with pytest.raises(sqlite3.DatabaseError):
        memory.search()
    manager = workers.WorkerManager(send=lambda *a: None, owner=42,
                                   dispatch_dir=tmp_path / 'dispatch', report_dir=tmp_path / 'reports')
    result = asyncio.run(manager._archive_memory(memory.project, 'run_command', {},
                                                {'ok': False, 'exit_code': 7, 'stderr': 'actual error'}))
    assert result['exit_code'] == 7 and result['stderr'] == 'actual error'
    assert result['memory_warning']
    read = asyncio.run(manager._local_agent_execute_tool(memory.project, 'memory_search', {}))
    assert read['error'] == 'project_memory_unavailable'


def test_linked_storage_is_rejected(tmp_path):
    memory = store(tmp_path)
    memory.directory.mkdir(parents=True)
    target = tmp_path / 'other.sqlite3'
    target.write_text('do not touch')
    try:
        memory.path.symlink_to(target)
    except OSError:
        pytest.skip('Symlink creation unavailable')
    with pytest.raises(ValueError, match='Linked'):
        memory.search()
    assert target.read_text() == 'do not touch'


def test_linked_parent_is_rejected_before_creating_storage(tmp_path, monkeypatch):
    memory = store(tmp_path)
    original = Path.is_symlink
    monkeypatch.setattr(Path, 'is_symlink', lambda p: p == memory.directory.parent or original(p))
    with pytest.raises(ValueError, match='Linked'):
        memory.search()
    assert not memory.directory.exists()


def test_recall_does_not_inflate_progress_and_paging_survives_compaction():
    watch = ProgressWatch()
    for tool in ('memory_read', 'memory_search'):
        watch.observe(tool, {'ok': True, 'content': 'known evidence'})
    assert watch.diagnostics()['actions_since_checkpoint'] == 0
    assert watch.diagnostics()['partial_progress']['new_successful_observations'] == 0
    result = {'ok': True, 'tool': 'memory_read', 'id': 'saved', 'content': '雪"\n' * 3000,
              'offset': 200, 'next_offset': 9200, 'total_chars': 20000, 'freshness': 'changed'}
    bounded = json.loads(workers._local_agent_json_result(result, 1700))
    assert bounded['id'] == 'saved' and bounded['freshness'] == 'changed'
    assert bounded['next_offset'] == 200 + len(bounded['content'])
    assert len(json.dumps(bounded, ensure_ascii=False)) <= 1700
    for prefix in ('Tool result for memory_read:\n', 'Tool result (memory_read):\n'):
        compacted = workers._compact_source_exchange([
            {'role': 'user', 'content': prefix + json.dumps(result)}], 100)[0]
        page = json.loads(compacted['content'][len(prefix):])
        assert page['next_offset'] == 300 and len(page['content']) == 100


def test_cancellation_finishes_owned_memory_io_before_idle_acknowledgement():
    import threading
    entered, release = threading.Event(), threading.Event()
    completed = []
    def write():
        entered.set()
        assert release.wait(3)
        completed.append(True)
    async def scenario():
        pending = asyncio.create_task(workers._memory_io(write))
        assert await asyncio.to_thread(entered.wait, 2)
        pending.cancel()
        await asyncio.sleep(.01)
        assert not pending.done()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await pending
        assert completed == [True]
    asyncio.run(scenario())
