from modules.worker_progress import ProgressWatch
from modules.workers import WorkerReportStore


def test_repeated_results_cannot_be_renewed_by_plans_or_different_commands():
    watch = ProgressWatch()
    snapshot = {'available':True, 'current_head':'abc', 'files':[]}
    for window in range(4):
        for step in range(12):
            watch.observe('run_command', {'ok':True, 'command':f'git status variant{step}',
                'stdout':'unchanged', 'stderr':'', 'exit_code':0, 'duration':step})
            watch.observe('update_plan', {'plan':f'New paraphrase {window}-{step}'})
        stopped, summary = watch.checkpoint(snapshot)
        assert stopped == (window == 3)
    assert summary['repeated_windows'] == 3


def test_novel_read_only_evidence_and_silent_repository_changes_allow_progress():
    watch = ProgressWatch()
    for index in range(15):
        watch.observe('read_file', {'ok':True, 'path':f'file{index}', 'content':f'finding{index}'})
        assert not watch.checkpoint({'available':False})[0]
    # A shell can edit files without printing anything. Git evidence resets
    # the repeated-result windows even when no direct edit_file was called.
    for index in range(10):
        watch.observe('run_python', {'ok':True,'stdout':'','exit_code':0})
        assert not watch.checkpoint({'available':True,'files':[{'content':str(index)}]})[0]


def test_handoff_does_not_cross_folder_or_brain_and_clears_after_completion(tmp_path):
    store = WorkerReportStore(tmp_path, max_tail_chars=1000, max_events_bytes=100000)
    event = {'name':'Free-project','folder':'project','brain':'free','status':'stalled',
             'continuation':{'plan':{'next':'validate'}}}
    store.record(event)
    assert store.previous_continuation('Free-project','other') is None
    store.record(dict(event, status='accepted', continuation=None))
    assert store.previous_continuation('Free-project','project')['plan']['next'] == 'validate'
    store.record(dict(event, status='finished', continuation=None))
    assert store.previous_continuation('Free-project','project') is None
    store.record(dict(event, brain='claude'))
    assert store.previous_continuation('Free-project','project') is None
