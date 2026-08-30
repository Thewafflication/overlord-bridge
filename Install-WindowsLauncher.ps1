[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [string]$ProjectsRoot,
    [switch]$Uninstall,
    [switch]$ClaudePathOnly
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
if (-not $ProjectsRoot) {
    $ProjectsRoot = Split-Path -Parent $ProjectRoot
}
$ProjectsRoot = [IO.Path]::GetFullPath($ProjectsRoot)

$StartMenuFolder = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\Overlord"
$ShortcutPath = Join-Path $StartMenuFolder "Overlord.lnk"
$GlobalInstructions = Join-Path $ProjectsRoot "AGENTS.md"
$InstructionTemplate = Join-Path $ProjectRoot "AGENTS.windows.md"
$EnvFile = Join-Path $ProjectRoot ".env"
$IconPath = Join-Path $ProjectRoot "assets\overlord.ico"
$LauncherPath = Join-Path $ProjectRoot "run-windows.ps1"
$ClaudeExe = Join-Path $ProjectRoot ".venv\Lib\site-packages\claude_agent_sdk\_bundled\claude.exe"

function Add-UserPathEntry {
    param([string]$Directory)
    $Current = [Environment]::GetEnvironmentVariable("Path", "User")
    $Entries = @($Current -split ';' | Where-Object { $_.Trim() })
    $Target = [IO.Path]::GetFullPath($Directory).TrimEnd('\')
    $Exists = $false
    foreach ($Entry in $Entries) {
        try {
            $Candidate = [IO.Path]::GetFullPath(
                [Environment]::ExpandEnvironmentVariables($Entry)
            ).TrimEnd('\')
            if ($Candidate -ieq $Target) {
                $Exists = $true
                break
            }
        } catch {
            # Preserve malformed/legacy PATH entries; they simply cannot match.
        }
    }
    if (-not $Exists) {
        $Updated = (@($Entries) + $Directory) -join ';'
        [Environment]::SetEnvironmentVariable("Path", $Updated, "User")
        Write-Host "Added Claude CLI to the user PATH: $Directory"
    } else {
        Write-Host "Claude CLI is already on the user PATH: $Directory"
    }
    if (($env:Path -split ';') -inotcontains $Directory) {
        $env:Path = "$env:Path;$Directory"
    }
}

if ($Uninstall) {
    if (Test-Path -LiteralPath $StartMenuFolder) {
        Remove-Item -LiteralPath $StartMenuFolder -Recurse -Force
    }
    Write-Host "Removed the Overlord Start Menu shortcut."
    Write-Host "Preserved $GlobalInstructions and the bridge configuration."
    return
}

if (-not (Test-Path -LiteralPath $ProjectsRoot -PathType Container)) {
    throw "Projects root does not exist: $ProjectsRoot"
}
if (-not (Test-Path -LiteralPath $ClaudeExe -PathType Leaf)) {
    throw "Bundled Claude CLI is missing. Run .\run-windows.ps1 -Install first."
}
$ClaudeBin = Split-Path -Parent $ClaudeExe

if ($ClaudePathOnly) {
    if ($WhatIfPreference) {
        Write-Host "Would add the bundled Claude CLI directory to the user PATH: $ClaudeBin"
    } else {
        Add-UserPathEntry $ClaudeBin
        Write-Host "Open a new PowerShell window before running: claude auth login"
    }
    return
}

if (-not (Test-Path -LiteralPath $EnvFile -PathType Leaf)) {
    throw "Configure $EnvFile before installing the launcher."
}
if (-not (Test-Path -LiteralPath $IconPath -PathType Leaf)) {
    throw "Launcher icon is missing: $IconPath"
}

if ($WhatIfPreference) {
    Write-Host "Would create global instructions (if absent): $GlobalInstructions"
    Write-Host "Would configure the bridge workspace and shared instructions in $EnvFile"
    Write-Host "Would add the bundled Claude CLI directory to the user PATH: $ClaudeBin"
    Write-Host "Would install Start Menu shortcut: $ShortcutPath"
    return
}

if (-not (Test-Path -LiteralPath $GlobalInstructions -PathType Leaf)) {
    $Instructions = (Get-Content -LiteralPath $InstructionTemplate -Raw).Replace(
        "{{PROJECTS_ROOT}}",
        $ProjectsRoot
    )
    Set-Content -LiteralPath $GlobalInstructions -Value $Instructions -Encoding utf8
    Write-Host "Created global instructions: $GlobalInstructions"
} else {
    Write-Host "Preserved existing global instructions: $GlobalInstructions"
}

function Set-DotEnvValue {
    param([string]$Path, [string]$Name, [string]$Value)
    $Lines = @(Get-Content -LiteralPath $Path)
    $Found = $false
    for ($Index = 0; $Index -lt $Lines.Count; $Index++) {
        if ($Lines[$Index] -match "^\s*$([regex]::Escape($Name))\s*=") {
            $Lines[$Index] = "$Name=$Value"
            $Found = $true
        }
    }
    if (-not $Found) {
        $Lines += "$Name=$Value"
    }
    Set-Content -LiteralPath $Path -Value $Lines -Encoding utf8
}

Set-DotEnvValue $EnvFile "OVERLORD_CWD" $ProjectsRoot
Set-DotEnvValue $EnvFile "OVERLORD_INSTRUCTIONS_FILE" $GlobalInstructions
Set-DotEnvValue $EnvFile "OVERLORD_CLAUDE_AUTO_APPROVE_EDITS" "true"

Add-UserPathEntry $ClaudeBin

New-Item -ItemType Directory -Path $StartMenuFolder -Force | Out-Null
$PowerShell = (Get-Command pwsh.exe -ErrorAction Stop).Source
$Shell = New-Object -ComObject WScript.Shell
$Shortcut = $Shell.CreateShortcut($ShortcutPath)
$Shortcut.TargetPath = $PowerShell
$Shortcut.Arguments = (
    '-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "{0}" ' +
    '-WorkingDirectory "{1}"'
) -f $LauncherPath, $ProjectsRoot
$Shortcut.WorkingDirectory = $ProjectsRoot
$Shortcut.IconLocation = "$IconPath,0"
$Shortcut.Description = "Start the Overlord Telegram AI bridge"
$Shortcut.WindowStyle = 7
$Shortcut.Save()

Write-Host "Installed Start Menu shortcut: $ShortcutPath"
Write-Host "Default projects root: $ProjectsRoot"
Write-Host "Global instructions: $GlobalInstructions"
Write-Host "Claude CLI: $ClaudeExe"
Write-Host "Open a new PowerShell window before running: claude auth login"
Write-Host "Search for 'Overlord' in the Start Menu to launch it."
