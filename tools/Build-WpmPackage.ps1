[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$Version,

    [string]$Wpm = 'wpm.exe',
    [string]$SigningKey,
    [string]$OutputDirectory = 'dist\wpm',
    [string]$StagingDirectory = 'out\wpm-staging\overlord-bridge',
    [switch]$StageOnly
)

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot

if ($Version -notmatch '^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$') {
    throw "Version must be valid SemVer: $Version"
}

function Resolve-RepositoryPath {
    param([Parameter(Mandatory = $true)][string]$Path)
    if ([IO.Path]::IsPathRooted($Path)) {
        return [IO.Path]::GetFullPath($Path)
    }
    return [IO.Path]::GetFullPath((Join-Path $repoRoot $Path))
}

function Copy-RequiredFile {
    param(
        [Parameter(Mandatory = $true)][string]$RelativePath,
        [Parameter(Mandatory = $true)][string]$DestinationRoot
    )
    $source = Join-Path $repoRoot $RelativePath
    if (-not (Test-Path -LiteralPath $source -PathType Leaf)) {
        throw "Required package file is missing: $source"
    }
    $destination = Join-Path $DestinationRoot $RelativePath
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $destination) |
        Out-Null
    Copy-Item -LiteralPath $source -Destination $destination -Force
}

$staging = Resolve-RepositoryPath $StagingDirectory
$output = Resolve-RepositoryPath $OutputDirectory
if (Test-Path -LiteralPath $staging) {
    Remove-Item -LiteralPath $staging -Recurse -Force
}
$payload = Join-Path $staging 'payload'
$metadataDirectory = Join-Path $staging '.wpm'
New-Item -ItemType Directory -Force -Path $payload, $metadataDirectory, $output |
    Out-Null

foreach ($file in @(
    'bridge.py',
    'requirements.txt',
    'run-windows.ps1',
    'Install-WindowsLauncher.ps1',
    'AGENTS.example.md',
    'AGENTS.windows.md',
    'CAPABILITIES.md',
    'README.md'
)) {
    Copy-RequiredFile -RelativePath $file -DestinationRoot $payload
}

foreach ($directory in @('modules', 'plugins', 'assets')) {
    $source = Join-Path $repoRoot $directory
    if (-not (Test-Path -LiteralPath $source -PathType Container)) {
        throw "Required package directory is missing: $source"
    }
    Copy-Item -LiteralPath $source -Destination $payload -Recurse -Force
}
Copy-RequiredFile -RelativePath 'tools\overlord_console.py' -DestinationRoot $payload
Copy-RequiredFile -RelativePath 'packaging\wpm\Package-Lifecycle.ps1' -DestinationRoot $staging

Get-ChildItem -LiteralPath $payload -Directory -Recurse -Force |
    Where-Object Name -eq '__pycache__' |
    Remove-Item -Recurse -Force
Get-ChildItem -LiteralPath $payload -File -Recurse -Force -Include '*.pyc', '*.pyo' |
    Remove-Item -Force

$revision = (& git -C $repoRoot rev-parse HEAD 2>$null) -join ''
if ($LASTEXITCODE -ne 0 -or -not $revision) {
    $revision = 'unknown'
}
@(
    'name=overlord-bridge'
    "version=$Version"
    'arch=any'
    'debug=false'
    'description=Telegram control bridge for Claude and Codex'
    'maintainer=Jordan Waughtal'
    'homepage=https://github.com/Thewafflication/overlord-bridge'
    'repository=https://github.com/Thewafflication/overlord-bridge'
    'license=Proprietary'
    "source-revision=$revision"
) | Set-Content -LiteralPath (Join-Path $metadataDirectory 'package.txt') -Encoding ascii

@(
    '@echo off'
    'setlocal'
    ('powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0..\packaging\wpm\Package-Lifecycle.ps1" -Action Install -SourceDirectory "%~dp0..\payload" -Version "{0}"' -f $Version)
    'exit /b %ERRORLEVEL%'
) | Set-Content -LiteralPath (Join-Path $metadataDirectory 'install.cmd') -Encoding ascii

@(
    '@echo off'
    'setlocal'
    ('powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0..\packaging\wpm\Package-Lifecycle.ps1" -Action Remove -Version "{0}"' -f $Version)
    'exit /b %ERRORLEVEL%'
) | Set-Content -LiteralPath (Join-Path $metadataDirectory 'remove.cmd') -Encoding ascii

@(
    '__pycache__/'
    '*.pyc'
    '*.pyo'
    '.env'
    '.session*'
    '.venv/'
    'run/'
    'worker_reports/'
) | Set-Content -LiteralPath (Join-Path $metadataDirectory 'wpmignore.txt') -Encoding ascii

if ($StageOnly) {
    $staging
    return
}

$arguments = @('build', $staging, $output)
if ($SigningKey) {
    $resolvedSigningKey = (Resolve-Path -LiteralPath $SigningKey).Path
    $arguments += @('--sign', $resolvedSigningKey)
}
& $Wpm @arguments
if ($LASTEXITCODE -ne 0) {
    throw 'WPM failed to create the Overlord package.'
}

$expectedName = "overlord-bridge-any-$Version.zip"
$package = Join-Path $output $expectedName
if (-not (Test-Path -LiteralPath $package -PathType Leaf)) {
    throw "WPM did not create the expected package: $package"
}
$package
