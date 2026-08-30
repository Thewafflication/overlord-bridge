[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [string]$ProjectsRoot,
    [switch]$Uninstall
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
if (-not (Test-Path -LiteralPath $EnvFile -PathType Leaf)) {
    throw "Configure $EnvFile before installing the launcher."
}
if (-not (Test-Path -LiteralPath $IconPath -PathType Leaf)) {
    throw "Launcher icon is missing: $IconPath"
}

if ($WhatIfPreference) {
    Write-Host "Would create global instructions (if absent): $GlobalInstructions"
    Write-Host "Would configure the bridge workspace and shared instructions in $EnvFile"
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
Write-Host "Search for 'Overlord' in the Start Menu to launch it."
