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
    foreach ($session in @(Get-ChildItem -LiteralPath $From -Filter '.session.*' -File -ErrorAction SilentlyContinue)) {
        Copy-Item -LiteralPath $session.FullName -Destination (Join-Path $To $session.Name) -Force
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

$installRoot = Get-OverlordInstallRoot
$stateRoot = Join-Path $env:LOCALAPPDATA 'Overlord\state'

if ($Action -eq 'Remove') {
    Copy-PersistentState -From $installRoot -To $stateRoot
    $launcher = Join-Path $installRoot 'Install-WindowsLauncher.ps1'
    if (Test-Path -LiteralPath $launcher -PathType Leaf) {
        & $launcher -Uninstall
    }
    if (Test-Path -LiteralPath $installRoot) {
        Remove-Item -LiteralPath $installRoot -Recurse -Force
    }
    Write-Host "Removed Overlord. Preserved configuration and session pins in $stateRoot."
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

Copy-PersistentState -From $installRoot -To $stateRoot
$parent = Split-Path -Parent $installRoot
$leaf = Split-Path -Leaf $installRoot
$newRoot = Join-Path $parent "$leaf.new-$PID"
$backupRoot = Join-Path $parent "$leaf.backup-$PID"

try {
    New-Item -ItemType Directory -Force -Path $parent | Out-Null
    if (Test-Path -LiteralPath $newRoot) {
        Remove-Item -LiteralPath $newRoot -Recurse -Force
    }
    New-Item -ItemType Directory -Force -Path $newRoot | Out-Null
    Copy-Item -Path (Join-Path $SourceDirectory '*') -Destination $newRoot -Recurse -Force
    Copy-PersistentState -From $stateRoot -To $newRoot
    $envFile = Join-Path $newRoot '.env'
    if (-not (Test-Path -LiteralPath $envFile -PathType Leaf)) {
        Copy-Item -LiteralPath (Join-Path $newRoot '.env.example') -Destination $envFile
    }

    if (Test-Path -LiteralPath $installRoot) {
        Move-Item -LiteralPath $installRoot -Destination $backupRoot
    }
    Move-Item -LiteralPath $newRoot -Destination $installRoot

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

    $projectsRoot = Get-OverlordProjectsRoot
    & (Join-Path $installRoot 'Install-WindowsLauncher.ps1') -ProjectsRoot $projectsRoot
    if ($LASTEXITCODE -ne 0) {
        throw 'Start Menu launcher installation failed.'
    }

    if (Test-Path -LiteralPath $backupRoot) {
        Remove-Item -LiteralPath $backupRoot -Recurse -Force
    }
}
catch {
    if (Test-Path -LiteralPath $installRoot) {
        Remove-Item -LiteralPath $installRoot -Recurse -Force
    }
    if (Test-Path -LiteralPath $backupRoot) {
        Move-Item -LiteralPath $backupRoot -Destination $installRoot
    }
    throw
}
finally {
    if (Test-Path -LiteralPath $newRoot) {
        Remove-Item -LiteralPath $newRoot -Recurse -Force
    }
}

Write-Host "Installed Overlord $Version in $installRoot."
Write-Host 'Edit the installed .env file with TELEGRAM_BOT_TOKEN and OWNER_CHAT_ID before first launch.'
