import asyncio
import subprocess
import sys

import pytest

from modules.worker_index_guard import WorkerIndexGuard


def git(folder, *args):
    return subprocess.check_output(['git', '-C', str(folder), *args], text=True).strip()


@pytest.fixture
def project(tmp_path):
    git(tmp_path, 'init')
    git(tmp_path, 'config', 'user.name', 'Test')
    git(tmp_path, 'config', 'user.email', 'test@example.invalid')
    (tmp_path / 'seed').write_text('baseline')
    git(tmp_path, 'add', 'seed')
    git(tmp_path, 'commit', '-m', 'baseline')
    (tmp_path / 'owner.ps1').write_text('owner bytes')
    return tmp_path


def test_owner_staging_rejected_but_new_owned_file_commits(project):
    async def scenario():
        guard = WorkerIndexGuard()
        await guard.acquire(project, lambda p: True)
        for command in ['git add owner.ps1', 'git add .', 'git add -A',
                        'git commit -m message -- owner.ps1']:
            async with guard.command(project, 'run_command', {'command': command}) as error:
                assert error['error'] == 'owner_git_index_protected'
        (project / 'worker.txt').write_text('real new change')
        for command, args in [('git add worker.txt', ('add', 'worker.txt')),
                              ('git commit -m change', ('commit', '-m', 'change'))]:
            async with guard.command(project, 'run_command', {'command': command}) as error:
                assert error is None
                git(project, *args)
        assert git(project, 'status', '--porcelain') == '?? owner.ps1'
        assert (project / 'owner.ps1').read_text() == 'owner bytes'
    asyncio.run(scenario())


@pytest.mark.parametrize('tool,arguments', [
    ('run_python', {'code': 'subprocess git add'}),
    ('run_command', {'command': 'git add owner.ps1 && git commit -m wrong'}),
    ('run_command', {'command': 'cmd /c git add owner.ps1'}),
])
def test_indirect_cooperating_git_cannot_stage_owner_file(project, tool, arguments):
    async def scenario():
        guard = WorkerIndexGuard()
        await guard.acquire(project, lambda p: True)
        async with guard.command(project, tool, arguments) as error:
            if tool == 'run_command':
                assert error and 'separate git commit' in error['message']
            else:
                assert error is None
                proc = subprocess.run([sys.executable, '-c',
                    "import subprocess; raise SystemExit(subprocess.run(['git','add','owner.ps1']).returncode)"],
                    cwd=project, capture_output=True)
                assert proc.returncode != 0 and b'index.lock' in proc.stderr
        assert not (project / '.git/index.lock').exists()
        assert git(project, 'ls-files', '--cached') == 'seed'
    asyncio.run(scenario())


def test_foreign_lock_preserved_and_cancelled_action_releases_own_lock(project):
    async def scenario():
        guard = WorkerIndexGuard()
        await guard.acquire(project, lambda p: True)
        lock = project / '.git/index.lock'
        lock.write_text('external owner lock')
        async with guard.command(project, 'run_python', {}) as error:
            assert error
        assert lock.read_text() == 'external owner lock'
        lock.unlink()
        with pytest.raises(asyncio.CancelledError):
            async with guard.command(project, 'run_python', {}) as error:
                assert error is None
                raise asyncio.CancelledError()
        assert not lock.exists()
    asyncio.run(scenario())


def test_explicit_owner_publication_path_exempt_and_external_staging_blocks_commit(project):
    async def scenario():
        guard = WorkerIndexGuard()
        await guard.acquire(project, lambda p: True, ['owner.ps1'])
        assert not guard.protected
        guard = WorkerIndexGuard()
        await guard.acquire(project, lambda p: True)
        git(project, 'add', 'owner.ps1')
        async with guard.command(project, 'run_command', {'command': 'git commit -m wrong'}) as error:
            assert error
        assert 'owner.ps1' in git(project, 'diff', '--cached', '--name-only')
    asyncio.run(scenario())


@pytest.mark.parametrize('command', [
    'git commit -m "first"\ngit add owner.ps1',
    'git commit -m "first" && git add owner.ps1',
    'git commit -m "%TEMP%"',
    'git commit -m "$(git add owner.ps1)"',
])
def test_multiline_support_does_not_unlock_shell_boundaries_or_expansions(project, command):
    async def scenario():
        guard = WorkerIndexGuard()
        await guard.acquire(project, lambda p: True)
        async with guard.command(project, 'run_command', {'command': command}) as error:
            assert error and 'separate git commit' in error['message']
            assert not guard.lock_held
        assert git(project, 'ls-files', '--cached') == 'seed'
    asyncio.run(scenario())
