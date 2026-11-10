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
