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


def test_one_rotating_new_result_cannot_renew_eleven_repeated_results():
    watch = ProgressWatch()
    snapshot = {'available':True, 'current_head':'abc', 'files':[]}
    for window in range(4):
        for _ in range(11):
            watch.observe('read_file', {'ok':True,'path':'docs/adoption.md','content':'same facts'})
        watch.observe('run_command', {'ok':True,'stdout':f'new metadata variant {window}','exit_code':0})
        stopped, _ = watch.checkpoint(snapshot)
        assert stopped == (window == 3)


def test_rotating_failures_do_not_renew_discovery_and_diagnostics_survive():
    watch = ProgressWatch()
    for window in range(4):
        for index in range(12):
            watch.observe('run_command', {'ok':False,'stderr':f'failure {window}-{index}','exit_code':1})
        stopped, summary = watch.checkpoint({'available':False})
        assert stopped == (window == 3)
    assert summary['new_diagnostics'] == 12 and summary['new_observations'] == 0
    assert watch.diagnostics()['last_checkpoint'] == summary


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


def test_relative_absolute_and_dot_aliases_are_one_observation(tmp_path):
    watch = ProgressWatch(tmp_path)
    snapshot = {'available': True, 'current_head': 'abc', 'files': []}
    for window in range(4):
        for path in ['generated/mpd.h', str(tmp_path / 'generated/mpd.h'),
                     './generated/mpd.h', 'generated/../generated/mpd.h'] * 3:
            watch.observe('read_file', {'ok': True, 'path': path, 'content': 'same header'})
        stopped, summary = watch.checkpoint(snapshot)
        assert summary['new_observations'] == (1 if window == 0 else 0)
        assert stopped == (window == 3)


def test_different_files_and_changed_contents_remain_new_evidence(tmp_path):
    watch = ProgressWatch(tmp_path)
    for path, content in [('a.h', 'header'), ('b.h', 'header'), ('a.h', 'new header')]:
        watch.observe('read_file', {'ok': True, 'path': path, 'content': content})
    _, summary = watch.checkpoint({'available': False})
    assert summary['new_observations'] == 3


def test_full_observation_cache_cannot_renew_windows_forever():
    watch = ProgressWatch()
    for index in range(4096):
        watch.observe('run_command', {'ok': True, 'stdout': str(index)})
    snapshot = {'available': False}
    watch.checkpoint(snapshot)
    for window in range(3):
        for index in range(12):
            watch.observe('run_command', {'ok': True, 'stdout': str(4096 + index)})
        stopped, summary = watch.checkpoint(snapshot)
        assert stopped == (window == 2)
        assert summary['new_observations'] == 0
    assert len(watch.seen) == 4096
