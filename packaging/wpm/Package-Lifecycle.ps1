[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('Install', 'Remove')]
    [string]$Action,

    [string]$SourceDirectory,
    [string]$Version = 'unknown'
)

$ErrorActionPreference = 'Stop'

function Get-OverlordInstallRoot {
    if ($env:OVERLORD_INSTALL_DIR) {
        return [IO.Path]::GetFullPath($env:OVERLORD_INSTALL_DIR)
    }
    if (-not $env:LOCALAPPDATA) {
        throw 'LOCALAPPDATA is not available for the per-user Overlord installation.'
    }
    return Join-Path $env:LOCALAPPDATA 'Programs\Overlord'
}

function Get-OverlordProjectsRoot {
    if ($env:OVERLORD_PROJECTS_ROOT) {
        return [IO.Path]::GetFullPath($env:OVERLORD_PROJECTS_ROOT)
    }
    $candidate = Join-Path $env:USERPROFILE 'source\repos'
    if (Test-Path -LiteralPath $candidate -PathType Container) {
        return $candidate
    }
    return $env:USERPROFILE
}

function Copy-PersistentState {
    param(
        [Parameter(Mandatory = $true)]
        [string]$From,
        [Parameter(Mandatory = $true)]
        [string]$To
    )

    if (-not (Test-Path -LiteralPath $From -PathType Container)) {
        return
    }
    New-Item -ItemType Directory -Force -Path $To | Out-Null
    foreach ($name in @('.env', 'AGENTS.md', 'roster.json')) {
        $source = Join-Path $From $name
        if (Test-Path -LiteralPath $source -PathType Leaf) {
            Copy-Item -LiteralPath $source -Destination (Join-Path $To $name) -Force
        }
    }
    foreach ($session in @(Get-ChildItem -LiteralPath $From -Filter '.session.*' -File -Force -ErrorAction SilentlyContinue)) {
        Copy-Item -LiteralPath $session.FullName -Destination (Join-Path $To $session.Name) -Force
    }
    # Latest reports contain the worker/session mapping needed for resumption;
    # event history and its rotation belong to the same persistent store.
    $reports = Join-Path $From 'worker_reports'
    if (Test-Path -LiteralPath $reports -PathType Container) {
        $entries = @(Get-Item -LiteralPath $reports -Force) +
            @(Get-ChildItem -LiteralPath $reports -Recurse -Force)
        foreach ($entry in $entries) {
            if ($entry.Attributes -band [IO.FileAttributes]::ReparsePoint) {
                throw 'Refusing linked worker report state; the existing installation was not replaced.'
            }
        }
        Copy-Item -LiteralPath $reports -Destination $To -Recurse -Force
    }
}

function Assert-Python312 {
    $python = Get-Command python.exe -CommandType Application -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if (-not $python) {
        throw 'Python 3.12 or newer is required. Install Python, then retry the WPM package.'
    }
    $versionText = (& $python.Source --version 2>&1) -join ''
    if ($LASTEXITCODE -ne 0 -or $versionText -notmatch '^Python (\d+)\.(\d+)') {
        throw "Could not determine the installed Python version: $versionText"
    }
    if ([int]$Matches[1] -lt 3 -or
        ([int]$Matches[1] -eq 3 -and [int]$Matches[2] -lt 12)) {
        throw "Python 3.12 or newer is required; found $versionText."
    }
    return $python.Source
}

function Stop-InstalledOverlord {
    param([string]$Root)
    $processes = @(Get-CimInstance Win32_Process)
    $owned = @{}
    $wasRunning = $false
    foreach ($process in $processes) {
        if ($process.ProcessId -eq $PID) { continue }
        foreach ($script in @('bridge.py', 'tools\overlord_console.py', 'tools\overlord_setup.py', 'run-windows.ps1')) {
            $path = Join-Path $Root $script
            $pattern = '(?i)(?:^|[\s"])' + [regex]::Escape($path) + '(?=$|[\s"])'
            if ($process.CommandLine -match $pattern) {
                $owned[[int]$process.ProcessId] = $true
                if ($script -eq 'bridge.py') { $wasRunning = $true }
            }
        }
    }
    # Include worker/brain descendants so they cannot keep the old install locked.
    do {
        $added = $false
        foreach ($process in $processes) {
            if ($process.ProcessId -ne $PID -and $owned.ContainsKey([int]$process.ParentProcessId) -and
                -not $owned.ContainsKey([int]$process.ProcessId)) {
                $owned[[int]$process.ProcessId] = $true
                $added = $true
            }
        }
    } while ($added)
    foreach ($processId in $owned.Keys) {
        Stop-Process -Id $processId -Force -ErrorAction SilentlyContinue
    }
    foreach ($processId in $owned.Keys) {
        Wait-Process -Id $processId -Timeout 15 -ErrorAction SilentlyContinue
        if (Get-Process -Id $processId -ErrorAction SilentlyContinue) {
            throw "Could not stop Overlord process $processId. Installation was not replaced."
        }
    }
    return $wasRunning
}

function Start-InstalledOverlord {
    param([string]$Root, [string]$Workspace)
    $launcher = Join-Path $Root 'run-windows.ps1'
    Start-Process -FilePath (Get-Command pwsh.exe -ErrorAction Stop).Source -WindowStyle Hidden `
        -WorkingDirectory $Workspace -ArgumentList @(
            '-NoProfile', '-ExecutionPolicy', 'Bypass', '-WindowStyle', 'Hidden',
            '-File', ('"{0}"' -f $launcher), '-WorkingDirectory', ('"{0}"' -f $Workspace)
        ) | Out-Null
}

$installRoot = Get-OverlordInstallRoot
$installRoot = [IO.Path]::GetFullPath($installRoot).TrimEnd([IO.Path]::DirectorySeparatorChar)
$parent = Split-Path -Parent $installRoot
if (-not $parent -or $installRoot -eq [IO.Path]::GetPathRoot($installRoot) -or
    $installRoot -eq $env:USERPROFILE -or $installRoot -eq $env:LOCALAPPDATA) {
    throw "Refusing unsafe installation target: $installRoot"
}
$stateRoot = Join-Path $env:LOCALAPPDATA 'Overlord\state'

if ($Action -eq 'Remove') {
    $null = Stop-InstalledOverlord -Root $installRoot
    Copy-PersistentState -From $installRoot -To $stateRoot
    $launcher = Join-Path $installRoot 'Install-WindowsLauncher.ps1'
    if (Test-Path -LiteralPath $launcher -PathType Leaf) {
        & $launcher -Uninstall
    }
    if (Test-Path -LiteralPath $installRoot) {
        Remove-Item -LiteralPath $installRoot -Recurse -Force
    }
    Write-Host "Removed Overlord. Preserved configuration, session pins and worker reports in $stateRoot."
    return
}

if (-not $SourceDirectory -or
    -not (Test-Path -LiteralPath $SourceDirectory -PathType Container)) {
    throw "The Overlord package payload is missing: $SourceDirectory"
}
if (-not (Get-Command pwsh.exe -CommandType Application -ErrorAction SilentlyContinue)) {
    throw 'PowerShell 7 (pwsh.exe) is required for the Overlord Windows launcher.'
}
$python = Assert-Python312

$leaf = Split-Path -Leaf $installRoot
$newRoot = Join-Path $parent "$leaf.new-$PID"
$backupRoot = Join-Path $parent "$leaf.backup-$PID"
# Resolve and validate every recursive cleanup/move target before touching it.
foreach ($target in @($newRoot, $backupRoot)) {
    if ((Split-Path -Parent ([IO.Path]::GetFullPath($target))) -ne $parent -or
        (Test-Path -LiteralPath $target)) {
        throw "Unsafe or occupied staging target: $target"
    }
}
$wasRunning = Stop-InstalledOverlord -Root $installRoot
$swapped = $false
$backedUp = $false
$projectsRoot = Get-OverlordProjectsRoot

try {
    Copy-PersistentState -From $installRoot -To $stateRoot
    New-Item -ItemType Directory -Force -Path $parent | Out-Null
    New-Item -ItemType Directory -Force -Path $newRoot | Out-Null
    Copy-Item -Path (Join-Path $SourceDirectory '*') -Destination $newRoot -Recurse -Force
    Copy-PersistentState -From $stateRoot -To $newRoot
    $envFile = Join-Path $newRoot '.env'
    if (-not (Test-Path -LiteralPath $envFile -PathType Leaf)) {
        Copy-Item -LiteralPath (Join-Path $newRoot '.env.example') -Destination $envFile
    }

    if (Test-Path -LiteralPath $installRoot) {
        Move-Item -LiteralPath $installRoot -Destination $backupRoot
        $backedUp = $true
    }
    Move-Item -LiteralPath $newRoot -Destination $installRoot
    $swapped = $true

    $venv = Join-Path $installRoot '.venv'
    & $python -m venv $venv
    if ($LASTEXITCODE -ne 0) {
        throw 'Python virtual-environment creation failed.'
    }
    $venvPython = Join-Path $venv 'Scripts\python.exe'
    & $venvPython -m pip install --disable-pip-version-check -r (Join-Path $installRoot 'requirements.txt')
    if ($LASTEXITCODE -ne 0) {
        throw 'Overlord dependency installation failed.'
    }

    & (Join-Path $installRoot 'Install-WindowsLauncher.ps1') -ProjectsRoot $projectsRoot
    if ($LASTEXITCODE -ne 0) {
        throw 'Start Menu launcher installation failed.'
    }

    if (Test-Path -LiteralPath $backupRoot) {
        Remove-Item -LiteralPath $backupRoot -Recurse -Force
    }
}
catch {
    if ($swapped -and (Test-Path -LiteralPath $installRoot)) {
        Remove-Item -LiteralPath $installRoot -Recurse -Force
    }
    if ($backedUp -and (Test-Path -LiteralPath $backupRoot)) {
        Move-Item -LiteralPath $backupRoot -Destination $installRoot
    }
    if ($wasRunning -and (Test-Path -LiteralPath (Join-Path $installRoot 'run-windows.ps1'))) {
        Start-InstalledOverlord -Root $installRoot -Workspace $projectsRoot
    }
    throw
}
finally {
    if (Test-Path -LiteralPath $newRoot) {
        Remove-Item -LiteralPath $newRoot -Recurse -Force
    }
}

if ($wasRunning) {
    Start-InstalledOverlord -Root $installRoot -Workspace $projectsRoot
    Write-Host 'Restarted the previously running Overlord.'
}
Write-Host "Installed Overlord $Version in $installRoot."
Write-Host 'Edit the installed .env file with TELEGRAM_BOT_TOKEN and OWNER_CHAT_ID before first launch.'
