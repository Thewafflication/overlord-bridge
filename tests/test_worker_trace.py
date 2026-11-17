import json

import pytest

from modules.worker_trace import WorkerRequestTrace, MAX_FILE_BYTES


def records(trace):
    return [json.loads(path.read_text(encoding='utf-8')) for path in trace.paths if path.exists()]


def test_restart_retains_only_two_latest_attempts_and_ignores_late_response(tmp_path):
    trace = WorkerRequestTrace(tmp_path / 'reports', tmp_path / 'project', 'worker')
    first = trace.begin(model='model', payload={'messages': [{'content': 'source A'}]}, run='one', step=1)
    trace.finish(first, status=200, body={'choices': [{'message': {'content': 'decision A'}}]})
    trace = WorkerRequestTrace(tmp_path / 'reports', tmp_path / 'project', 'worker')
    second = trace.begin(model='model', payload={'messages': [{'content': 'source B'}]}, run='two', step=2)
    third = trace.begin(model='model', payload={'messages': [{'content': 'source C'}]}, run='two', step=3)
    trace.finish(first, status=200, body={'choices': [{'message': {'content': 'stale'}}]})
    trace.finish(third, status=200, body={'choices': [{'finish_reason': 'tool_calls', 'message': {
        'tool_calls': [{'function': {'name': 'read_file', 'arguments': '{"path":"source.c"}'}}]}}]})
    rows = records(trace)
    assert {row['capture_id'] for row in rows} == {second, third}
    assert next(row for row in rows if row['capture_id'] == second)['state'] == 'pending'
    response = next(row for row in rows if row['capture_id'] == third)['response']
    assert response['message']['tool_calls'][0]['function']['name'] == 'read_file'
    assert len(list(trace.directory.iterdir())) == 2


def test_redaction_and_transport_metadata_allowlist(tmp_path, monkeypatch):
    monkeypatch.setenv('TRACE_TEST_API_KEY', 'super-secret-value')
    trace = WorkerRequestTrace(tmp_path, tmp_path / 'project', 'worker')
    identity = trace.begin(model='model', run='run', step=5, payload={
        'messages': [{'role': 'user', 'content': 'api_key=super-secret-value'}],
        'headers': {'Authorization': 'Bearer forbidden'}, 'url': 'https://private.invalid',
        'api_key': 'forbidden'})
    trace.finish(identity, status=403, body={'error': {'message': 'secret provider URL'}})
    raw = trace.paths[0].read_text(encoding='utf-8')
    assert 'super-secret-value' not in raw and 'forbidden' not in raw
    assert 'private.invalid' not in raw and 'secret provider URL' not in raw
    assert records(trace)[0]['http_status'] == 403


def test_unicode_oversize_is_explicit_and_valid_json(tmp_path):
    trace = WorkerRequestTrace(tmp_path, tmp_path / 'project', 'worker')
    identity = trace.begin(model='model', run='run', step=1,
                           payload={'messages': [{'content': '猫' * 100_000}]})
    trace.finish(identity, status=200, body={'choices': [{'message': {'content': '猫' * 50_000}}]})
    row = records(trace)[0]
    assert row['request']['omitted'] and row['response']['omitted']
    assert all(path.stat().st_size < MAX_FILE_BYTES for path in trace.paths if path.exists())


def test_scopes_do_not_overwrite_other_workers_or_projects(tmp_path):
    traces = [WorkerRequestTrace(tmp_path, tmp_path / project, worker)
              for project, worker in [('one', 'A'), ('one', 'B'), ('two', 'A')]]
    for trace in traces:
        trace.begin(model='model', payload={}, run='run', step=1)
    assert len(list(traces[0].directory.glob('*.json'))) == 3


def test_linked_capture_directory_is_rejected(tmp_path):
    outside = tmp_path / 'outside'
    outside.mkdir()
    try:
        (tmp_path / 'requests').symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip('Directory symlink privilege unavailable')
    trace = WorkerRequestTrace(tmp_path, tmp_path / 'project', 'worker')
    with pytest.raises(ValueError, match='Linked'):
        trace.begin(model='model', payload={}, run='run', step=1)
    assert not list(outside.iterdir())
