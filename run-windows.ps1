[CmdletBinding(PositionalBinding = $false)]
param(
    [switch]$Install,
    [switch]$Check,
    [switch]$Help,
    [string]$WorkingDirectory,
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$RemainingArguments
)

$ErrorActionPreference = "Stop"
$LaunchDirectory = (Get-Location).Path
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
# A dev checkout has a .git directory; a deployed/managed install is a plain copy.
$IsManagedInstall = -not (Test-Path -LiteralPath (Join-Path $ProjectRoot ".git"))
$InstallMode = if ($IsManagedInstall) { "managed (deployed copy)" } else { "dev (source checkout)" }
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$Requirements = Join-Path $ProjectRoot "requirements.txt"
$EnvFile = Join-Path $ProjectRoot ".env"
$EnvExample = Join-Path $ProjectRoot ".env.example"
$InstructionsFile = Join-Path $ProjectRoot "AGENTS.md"
$InstructionsExample = Join-Path $ProjectRoot "AGENTS.example.md"

if ($Help -or $RemainingArguments -contains '/?') {
    Write-Host "Usage: .\run-windows.ps1 [-Install] [-Check] [-WorkingDirectory PATH]"
    Write-Host ""
    Write-Host "  -Install                Create/update .venv dependencies before starting."
    Write-Host "  -Check                  Validate and show configuration without starting."
    Write-Host "  -WorkingDirectory PATH  Agent workspace (default: the launch directory)."
    return
}
if ($RemainingArguments.Count -gt 0) {
    throw "Unknown argument(s): $($RemainingArguments -join ' ')"
}

if ($Install -or -not (Test-Path -LiteralPath $Python)) {
    if (-not (Test-Path -LiteralPath $Python)) {
        python -m venv (Join-Path $ProjectRoot ".venv")
    }
    & $Python -m pip install -r $Requirements
}

if (-not (Test-Path -LiteralPath $EnvFile)) {
    Copy-Item -LiteralPath $EnvExample -Destination $EnvFile
    Write-Host "Created $EnvFile"
    Write-Host "Add TELEGRAM_BOT_TOKEN and OWNER_CHAT_ID, set OVERLORD_BRAIN=codex, then run this script again."
    exit 1
}

if (-not (Test-Path -LiteralPath $InstructionsFile)) {
    Copy-Item -LiteralPath $InstructionsExample -Destination $InstructionsFile
    Write-Host "Created $InstructionsFile from the sanitized example. Review it when convenient."
}

$Required = @("TELEGRAM_BOT_TOKEN", "OWNER_CHAT_ID")
$Configured = @{}
foreach ($Line in Get-Content -LiteralPath $EnvFile) {
    if ($Line -match '^\s*([A-Z][A-Z0-9_]*)\s*=\s*(.*?)\s*$') {
        $Configured[$Matches[1]] = $Matches[2].Trim('"', "'")
    }
}
$Missing = @($Required | Where-Object { -not $Configured[$_] })
if ($Missing.Count -gt 0) {
    throw "Set $($Missing -join ' and ') in $EnvFile before starting the bridge."
}

if ($Configured["OVERLORD_CODEX_APP_SERVER_PROXY"] -match '^(1|true|yes|on)$') {
    throw "OVERLORD_CODEX_APP_SERVER_PROXY uses Unix sockets and must remain false on Windows."
}

if (-not $WorkingDirectory) {
    $WorkingDirectory = if ($env:OVERLORD_CWD) {
        $env:OVERLORD_CWD
    } elseif ($Configured["OVERLORD_CWD"]) {
        $Configured["OVERLORD_CWD"]
    } else {
        $LaunchDirectory
    }
}
if (-not [IO.Path]::IsPathRooted($WorkingDirectory)) {
    $WorkingDirectory = Join-Path $LaunchDirectory $WorkingDirectory
}
$WorkingDirectory = [IO.Path]::GetFullPath($WorkingDirectory)
if (-not (Test-Path -LiteralPath $WorkingDirectory -PathType Container)) {
    throw "Working directory does not exist: $WorkingDirectory"
}
$env:OVERLORD_CWD = $WorkingDirectory

$BrainSetting = if ($Configured["OVERLORD_BRAIN"]) {
    $Configured["OVERLORD_BRAIN"]
} else {
    "claude"
}
if ($BrainSetting -eq "codex") {
    $CodexSetting = $env:OVERLORD_CODEX_BIN
    if (-not $CodexSetting) {
        $CodexSetting = if ($Configured["OVERLORD_CODEX_BIN"]) {
            $Configured["OVERLORD_CODEX_BIN"]
        } else {
            "codex"
        }
    }

    $CodexPath = $null
    if ([IO.Path]::IsPathRooted($CodexSetting) -and
        (Test-Path -LiteralPath $CodexSetting -PathType Leaf)) {
        $CodexPath = [IO.Path]::GetFullPath($CodexSetting)
    } else {
        $CodexCommand = Get-Command $CodexSetting -CommandType Application -ErrorAction SilentlyContinue |
            Select-Object -First 1
        if ($CodexCommand) {
            $CodexPath = $CodexCommand.Path
        }
    }

    # Codex Desktop ships a native executable in a versioned directory which
    # may be added only to the app's PATH, not to ordinary PowerShell sessions.
    if (-not $CodexPath -and $env:LOCALAPPDATA) {
        $BundledCodexRoot = Join-Path $env:LOCALAPPDATA "OpenAI\Codex\bin"
        $BundledCodex = @(Get-ChildItem -LiteralPath $BundledCodexRoot -Filter codex.exe -File -Recurse -ErrorAction SilentlyContinue |
                Sort-Object LastWriteTime -Descending)[0]
        if ($BundledCodex) {
            $CodexPath = $BundledCodex.FullName
        }
    }
    if (-not $CodexPath) {
        throw "Codex CLI not found. Install Codex Desktop/CLI or set OVERLORD_CODEX_BIN in $EnvFile."
    }
    $env:OVERLORD_CODEX_BIN = $CodexPath
}

$Sandbox = if ($env:OVERLORD_CODEX_SANDBOX) {
    $env:OVERLORD_CODEX_SANDBOX
} elseif ($Configured["OVERLORD_CODEX_SANDBOX"]) {
    $Configured["OVERLORD_CODEX_SANDBOX"]
} else {
    "read-only"
}
Write-Host "Install:   $InstallMode"
Write-Host "Workspace: $WorkingDirectory"
Write-Host "Sandbox:   $Sandbox"
if ($env:OVERLORD_CODEX_BIN) {
    Write-Host "Codex:     $env:OVERLORD_CODEX_BIN"
}

if ($Check) {
    Write-Host "Configuration is valid."
    return
}

& $Python (Join-Path $ProjectRoot "bridge.py")
