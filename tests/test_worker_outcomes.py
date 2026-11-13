from modules.worker_outcomes import summarize


def test_outcomes_do_not_count_claims_or_failed_checks_as_verified():
    def row(identity, status, acceptance=None, task=None):
        return {'event_id': identity, 'brain': 'free', 'name': 'Free-fixture', 'status': status,
                'timestamp': '2026-11-10T12:00:00Z', 'project_task_id': task, 'acceptance': acceptance}
    good = row('a', 'finished', {'passed': True}, 'task-1')
    good['acceptance_baseline'] = {'passed': False}
    data = [good, good, row('b', 'finished'), row('c', 'incomplete', {'passed': True}, 'task-2'),
            row('d', 'finished', {'passed': False}, 'task-3'), row('e', 'finished', {'passed': True}, 'task-1')]
    result = summarize(data)
    assert result['terminal_runs'] == 5
    assert result['preflight_runs'] == 1 and result['initially_failing_contracts'] == 1
    assert result['verified_acceptance_runs'] == 2
    assert result['unique_verified_tasks'] == ['task-1']
    assert result['unverified_finished_runs'] == 2
    assert result['verified_rate'] == 0.4
    assert summarize(data, '2026-11-11')['terminal_runs'] == 0


def test_cohort_compares_instants_and_includes_exact_boundary():
    def row(identity, at):
        return {'event_id': identity, 'brain': 'free', 'name': 'fixture',
                'status': 'finished', 'timestamp': at}
    events = [row('exact', '2026-11-10T17:00:00-05:00'),
              row('before', '2026-11-11T00:30:00+03:00'),
              row('after', '2026-11-10T16:30:00-06:00')]
    for cutoff in ('2026-11-10T22:00:00Z', '2026-11-10T16:00:00-06:00'):
        assert summarize(events, cutoff)['terminal_runs'] == 2
    assert summarize([row('legacy', '2026-11-10T22:00:00')],
                     '2026-11-10T22:00:00Z')['terminal_runs'] == 1


def test_cohort_rejects_invalid_cutoff_even_without_events():
    import pytest
    with pytest.raises(ValueError, match='cohort timestamp'):
        summarize([], 'yesterday')


def test_cohort_rejects_missing_or_malformed_terminal_time():
    import pytest
    for timestamp in ('', 'not-a-time', 123):
        event = {'brain': 'free', 'event_id': 'bad', 'status': 'finished',
                 'timestamp': timestamp}
        with pytest.raises(ValueError, match='cohort timestamp'):
            summarize([event], '2026-11-10')
    # Unfiltered accounting remains usable for legacy events without timestamps.
    assert summarize([event])['terminal_runs'] == 1


def test_event_reader_rejects_missing_directory_and_missing_journals(tmp_path):
    import pytest
    from modules.worker_outcomes import read_events
    with pytest.raises(FileNotFoundError, match='directory does not exist'):
        list(read_events(tmp_path / 'missing'))
    with pytest.raises(FileNotFoundError, match='no event journals'):
        list(read_events(tmp_path))


def test_event_reader_accepts_empty_journal_and_reads_rotations(tmp_path):
    import json
    from modules.worker_outcomes import read_events
    (tmp_path / 'events.jsonl').write_text('', encoding='utf-8')
    assert list(read_events(tmp_path)) == []
    (tmp_path / 'events.1.jsonl').write_text(json.dumps({'event_id': 'old'}) + '\n', encoding='utf-8')
    (tmp_path / 'events.jsonl').write_text('\n' + json.dumps({'event_id': 'new'}) + '\n', encoding='utf-8')
    assert [e['event_id'] for e in read_events(tmp_path)] == ['old', 'new']
