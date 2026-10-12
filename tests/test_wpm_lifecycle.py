"""Execute the lifecycle process helpers with isolated process/launcher mocks."""
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PWSH = shutil.which("pwsh")


def run_script(tmp_path, body):
    if not PWSH:
        pytest.skip("PowerShell 7 is required")
    script = tmp_path / "check.ps1"
    script.write_text(r'''param([string]$Source, [string]$Root, [string]$Python)
$ErrorActionPreference = 'Stop'
$ast = [System.Management.Automation.Language.Parser]::ParseFile($Source, [ref]$null, [ref]$null)
foreach ($fn in $ast.FindAll({param($node) $node -is [System.Management.Automation.Language.FunctionDefinitionAst]}, $false)) {
    Invoke-Expression $fn.Extent.Text
}
''' + body, encoding="utf-8")
    result = subprocess.run([PWSH, "-NoProfile", "-File", str(script),
                             "-Source", str(ROOT / "packaging/wpm/Package-Lifecycle.ps1"),
                             "-Root", str(tmp_path / "Overlord"), "-Python", sys.executable],
                            capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


def test_stop_targets_only_installation_processes_and_descendants(tmp_path):
    result = run_script(tmp_path, r'''
function Get-CimInstance {
    @(
        [pscustomobject]@{ProcessId=101; ParentProcessId=1; CommandLine=('python "{0}"' -f (Join-Path $Root 'bridge.py'))},
        [pscustomobject]@{ProcessId=102; ParentProcessId=101; CommandLine='claude agent'},
        [pscustomobject]@{ProcessId=103; ParentProcessId=102; CommandLine='worker command'},
        [pscustomobject]@{ProcessId=104; ParentProcessId=1; CommandLine=('pythonw "{0}"' -f (Join-Path $Root 'tools/overlord_console.py'))},
        [pscustomobject]@{ProcessId=105; ParentProcessId=1; CommandLine=('python "{0}.other"' -f (Join-Path $Root 'bridge.py'))},
        [pscustomobject]@{ProcessId=106; ParentProcessId=1; CommandLine='python elsewhere/bridge.py'}
    )
}
$script:stopped = @()
function Stop-Process { param($Id, [switch]$Force, $ErrorAction) $script:stopped += $Id }
function Wait-Process { param($Id, $Timeout, $ErrorAction) }
function Get-Process { param($Id, $ErrorAction) }
$running = Stop-InstalledOverlord -Root $Root
@{running=$running; stopped=@($script:stopped | Sort-Object)} | ConvertTo-Json -Compress
''')
    assert result == {"running": True, "stopped": [101, 102, 103, 104]}


def test_stale_console_does_not_count_as_running_bridge(tmp_path):
    result = run_script(tmp_path, r'''
function Get-CimInstance {
    [pscustomobject]@{ProcessId=104; ParentProcessId=1; CommandLine=('pythonw "{0}"' -f (Join-Path $Root 'tools/overlord_console.py'))}
}
function Stop-Process { param($Id, [switch]$Force, $ErrorAction) }
function Wait-Process { param($Id, $Timeout, $ErrorAction) }
function Get-Process { param($Id, $ErrorAction) }
@{running=(Stop-InstalledOverlord -Root $Root)} | ConvertTo-Json -Compress
''')
    assert result == {"running": False}


def test_restart_launches_hidden_with_quoted_paths(tmp_path):
    result = run_script(tmp_path, r'''
function Get-Command { param($Name, $ErrorAction) [pscustomobject]@{Source='pwsh.exe'} }
function Start-Process {
    param($FilePath, $WindowStyle, $WorkingDirectory, $ArgumentList)
    $script:launch = @{file=$FilePath; style=$WindowStyle; cwd=$WorkingDirectory; args=$ArgumentList}
}
Start-InstalledOverlord -Root $Root -Workspace (Join-Path $Root 'Projects With Spaces')
$script:launch | ConvertTo-Json -Compress
''')
    assert result["style"] == "Hidden"
    assert result["file"] == "pwsh.exe"
    assert result["args"][-1] == '"' + result["cwd"] + '"'
    assert "run-windows.ps1" in result["args"][-3]


@pytest.mark.parametrize("running", [True, False])
def test_staging_failure_preserves_previous_install_and_restarts_only_if_running(tmp_path, running):
    install = tmp_path / "Overlord"
    install.mkdir()
    (install / "marker").write_text("original install")
    (install / "run-windows.ps1").write_text("# launcher")
    payload = tmp_path / "payload"
    payload.mkdir()
    body = r'''
$env:OVERLORD_INSTALL_DIR = $Root
$env:LOCALAPPDATA = Split-Path -Parent $Root
$env:OVERLORD_PROJECTS_ROOT = $env:LOCALAPPDATA
$global:lifecycleTestRunning = RUNNING_VALUE
function Get-Command {
    param($Name, $CommandType, $ErrorAction)
    [pscustomobject]@{Source=$(if ($Name -eq 'python.exe') { $Python } else { 'pwsh.exe' })}
}
function Get-CimInstance {
    if ($global:lifecycleTestRunning) {
        [pscustomobject]@{ProcessId=101; ParentProcessId=1; CommandLine=('python "{0}"' -f (Join-Path $Root 'bridge.py'))}
    }
}
function Stop-Process { param($Id, [switch]$Force, $ErrorAction) }
function Wait-Process { param($Id, $Timeout, $ErrorAction) }
function Get-Process { param($Id, $ErrorAction) }
function Copy-Item { throw 'simulated staging copy failure' }
$global:lifecycleTestRestarts = 0
function Start-Process {
    param($FilePath, $WindowStyle, $WorkingDirectory, $ArgumentList)
    $global:lifecycleTestRestarts++
}
try {
    & $Source -Action Install -SourceDirectory (Join-Path $env:LOCALAPPDATA 'payload')
    throw 'Expected install failure'
} catch {
    if ($_.Exception.Message -ne 'simulated staging copy failure') { throw }
}
@{preserved=(Test-Path -LiteralPath (Join-Path $Root 'marker')); restarts=$global:lifecycleTestRestarts} | ConvertTo-Json -Compress
'''.replace("RUNNING_VALUE", "$true" if running else "$false")
    result = run_script(tmp_path, body)
    assert result == {"preserved": True, "restarts": int(running)}
    assert (install / "marker").read_text() == "original install"


def test_failure_after_directory_swap_restores_previous_install(tmp_path):
    install = tmp_path / "Overlord"
    install.mkdir()
    (install / "marker").write_text("original install")
    (install / "run-windows.ps1").write_text("# launcher")
    payload = tmp_path / "payload"
    payload.mkdir()
    (payload / ".env.example").write_text("# isolated test configuration")
    # A missing requirements file forces failure after the directory swap.
    result = run_script(tmp_path, r'''
$env:OVERLORD_INSTALL_DIR = $Root
$env:LOCALAPPDATA = Split-Path -Parent $Root
$env:OVERLORD_PROJECTS_ROOT = $env:LOCALAPPDATA
function Get-Command {
    param($Name, $CommandType, $ErrorAction)
    [pscustomobject]@{Source=$(if ($Name -eq 'python.exe') { $Python } else { 'pwsh.exe' })}
}
function Get-CimInstance { @() }
try {
    & $Source -Action Install -SourceDirectory (Join-Path $env:LOCALAPPDATA 'payload')
    throw 'Expected install failure'
} catch {
    if ($_.Exception.Message -eq 'Expected install failure') { throw }
}
@{preserved=(Test-Path -LiteralPath (Join-Path $Root 'marker')); backups=@(Get-ChildItem -LiteralPath (Split-Path -Parent $Root) -Filter 'Overlord.backup-*').Count} | ConvertTo-Json -Compress
''')
    assert result == {"preserved": True, "backups": 0}
    assert (install / "marker").read_text() == "original install"
