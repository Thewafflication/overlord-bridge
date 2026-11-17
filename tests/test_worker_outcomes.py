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


def test_partial_progress_is_measured_without_claiming_acceptance():
    event = {'event_id': 'partial', 'brain': 'free', 'name': 'worker', 'status': 'incomplete',
             'progress_diagnostics': {'partial_progress': {'confirmed_file_mutations': 2,
                 'distinct_successful_command_results': 3, 'new_failure_diagnostics': 1},
                 'model_reported_completed_steps': 2}}
    legacy = {'event_id': 'legacy', 'brain': 'free', 'name': 'old', 'status': 'stalled'}
    summary = summarize([event, event, legacy])
    assert summary['terminal_runs'] == 2
    assert summary['partial_progress_measured_runs'] == 1
    assert summary['runs_with_confirmed_mutations'] == 1
    assert summary['partial_progress']['confirmed_file_mutations'] == 2
    assert summary['partial_progress']['distinct_successful_command_results'] == 3
    assert summary['model_reported_completed_steps'] == 2
    assert summary['verified_acceptance_runs'] == 0
    assert summary['unique_verified_tasks'] == []


def lifecycle_event(identity, status, session='session', at='2026-11-16T10:00:00Z', **extra):
    return dict(dict(event_id=identity, brain='free', name='worker', folder='/project',
                     session=session, status=status, timestamp=at), **extra)


def test_unreported_starts_are_visible_without_inventing_crashes():
    start = lifecycle_event('start', 'started')
    result = summarize([start, start])
    assert result['terminal_runs'] == 0
    coverage = result['run_coverage']
    assert coverage['started_runs'] == 1
    assert coverage['resolved_started_runs'] == 0
    assert coverage['unresolved_started_runs'] == 1
    assert coverage['started_cohort_verified_rate'] == 0
    assert coverage['unresolved_retained_starts'][0]['event_id'] == 'start'
    assert result['status_counts'] == {}


def test_skipped_run_resolves_start_without_claiming_delivery():
    result = summarize([lifecycle_event('start', 'started'),
                        lifecycle_event('skip', 'skipped', at='2026-11-16T10:01:00Z')])
    assert result['status_counts'] == {'skipped': 1}
    assert result['run_coverage']['resolved_started_runs'] == 1
    assert result['run_coverage']['unresolved_started_runs'] == 0
    assert result['verified_acceptance_runs'] == 0


def test_start_cohort_and_terminal_cohort_are_separate_and_rotation_order_independent():
    start = lifecycle_event('start', 'started', started_at='2026-11-16T05:00:00-05:00')
    end = lifecycle_event('end', 'finished', at='2026-11-16T11:00:00Z',
                          started_at='2026-11-16T10:00:00Z',
                          project_task_id='task', acceptance={'passed': True})
    old = lifecycle_event('old', 'started', session='old', at='2026-11-15T10:00:00Z')
    result = summarize(iter([end, old, start, end]), since='2026-11-16T10:00:00Z')
    coverage = result['run_coverage']
    assert coverage['started_runs'] == coverage['resolved_started_runs'] == 1
    assert coverage['verified_started_runs'] == 1
    assert coverage['started_cohort_verified_rate'] == 1
    assert [e['event_id'] for e in coverage['unresolved_retained_starts']] == ['old']
    later = summarize([end, start], since='2026-11-16T10:30:00Z')
    assert later['terminal_runs'] == 1
    assert later['run_coverage']['started_runs'] == 0
    assert later['run_coverage']['started_cohort_verified_rate'] is None


def test_reused_session_and_cross_project_runs_do_not_resolve_each_other():
    first = lifecycle_event('first', 'started')
    second = lifecycle_event('second', 'started', at='2026-11-16T12:00:00Z')
    # An interruption without started_at resolves the preceding attempt only.
    end = lifecycle_event('end', 'interrupted', at='2026-11-16T12:01:00Z')
    unrelated = lifecycle_event('other', 'finished', folder='/other',
                                 at='2026-11-16T10:01:00Z')
    coverage = summarize([end, unrelated, second, first])['run_coverage']
    assert coverage['started_runs'] == 2
    assert coverage['resolved_started_runs'] == 1
    assert [e['event_id'] for e in coverage['unresolved_retained_starts']] == ['first']


def test_terminal_without_retained_start_and_accepted_only_are_not_started_runs():
    coverage = summarize([lifecycle_event('accepted', 'accepted'),
                          lifecycle_event('end', 'finished')])['run_coverage']
    assert coverage['started_runs'] == 0
    assert coverage['unresolved_retained_starts'] == []


def test_incomplete_with_passed_acceptance_is_not_verified_in_started_cohort():
    coverage = summarize([lifecycle_event('start', 'started'),
        lifecycle_event('end', 'incomplete', at='2026-11-16T10:01:00Z',
                        project_task_id='task', acceptance={'passed': True})])['run_coverage']
    assert coverage['resolved_started_runs'] == 1
    assert coverage['verified_started_runs'] == 0


def test_explicit_start_time_resolves_older_attempt_and_missing_session_stays_unresolved():
    first = lifecycle_event('first', 'started')
    second = lifecycle_event('second', 'started', at='2026-11-16T12:00:00Z')
    end = lifecycle_event('end', 'finished', at='2026-11-16T12:01:00Z',
                          started_at='2026-11-16T10:00:00Z')
    unknown = lifecycle_event('unknown', 'started', session=None)
    unknown_end = lifecycle_event('unknown-end', 'finished', session=None)
    coverage = summarize([first, second, end, unknown, unknown_end])['run_coverage']
    assert coverage['resolved_started_runs'] == 1
    assert {e['event_id'] for e in coverage['unresolved_retained_starts']} == {'second', 'unknown'}


def test_outcome_cli_reads_rotated_start_and_current_skipped_result(tmp_path):
    import json
    import subprocess
    import sys
    start = lifecycle_event('start', 'started')
    end = lifecycle_event('end', 'skipped', at='2026-11-16T10:01:00Z')
    (tmp_path / 'events.1.jsonl').write_text(json.dumps(start) + '\n', encoding='utf-8')
    (tmp_path / 'events.jsonl').write_text(json.dumps(end) + '\n', encoding='utf-8')
    output = tmp_path / 'summary.json'
    completed = subprocess.run([sys.executable, '-m', 'modules.worker_outcomes',
        '--reports', str(tmp_path), '--since', '2026-11-16T10:00:00Z',
        '--output', str(output)], capture_output=True, text=True, check=True)
    result = json.loads(output.read_text(encoding='utf-8'))
    assert json.loads(completed.stdout) == result
    assert result['status_counts'] == {'skipped': 1}
    assert result['run_coverage']['resolved_started_runs'] == 1
    assert result['run_coverage']['unresolved_retained_starts'] == []
