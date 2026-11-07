import pytest
from modules.windows_scripts import explicit_powershell_files, POWERSHELL_FILE


@pytest.mark.parametrize('command,expected', [
    (r'.\script.ps1 -Offline', POWERSHELL_FILE + r'".\script.ps1" -Offline'),
    (r'cd C:\project && .\tools\Get-LatexRuntime.ps1 -Offline 2>&1',
     'cd C:\\project && ' + POWERSHELL_FILE + r'".\tools\Get-LatexRuntime.ps1" -Offline 2>&1'),
    (r'echo before & call "a b.PS1" x || .\fallback.ps1',
     'echo before & call ' + POWERSHELL_FILE + '"a b.PS1" x || ' + POWERSHELL_FILE + r'".\fallback.ps1"'),
    ('(.\\a.ps1) | findstr x\n@call b.ps1',
     '(' + POWERSHELL_FILE + r'".\a.ps1") | findstr x' + '\n@call ' + POWERSHELL_FILE + '"b.ps1"'),
    ('2> "report.ps1" a.ps1', '2> "report.ps1" ' + POWERSHELL_FILE + '"a.ps1"'),
    ('script^ with^ spaces.ps1 x', POWERSHELL_FILE + '"script with spaces.ps1" x'),
])
def test_rewrites_only_cmd_script_heads_and_keeps_operators(command, expected):
    assert explicit_powershell_files(command) == expected


@pytest.mark.parametrize('command', [
    'echo "script.ps1 && other.ps1"',
    'type script.ps1 > copied.ps1',
    'python -c "print(\'script.ps1 && x.ps1\')"',
    'powershell.exe -NoProfile -File script.ps1',
    'pwsh -Command "& ./script.ps1"',
    'echo script.ps1 ^& other.ps1',
    'notepad script.ps1',
])
def test_script_mentions_and_explicit_programs_are_not_rewritten(command):
    assert explicit_powershell_files(command) == command


@pytest.mark.parametrize('command', [
    'if exist script.ps1 script.ps1',
    'for %f in (script.ps1) do %f',
    'start "" script.ps1',
    'cmd /c "cd . && script.ps1"',
    '"script.ps1',
])
def test_ambiguous_nested_or_control_syntax_is_not_executed(command):
    with pytest.raises(ValueError):
        explicit_powershell_files(command)
