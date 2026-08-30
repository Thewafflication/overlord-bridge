[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$Package,
    [string]$ExpectedVersion
)

$ErrorActionPreference = 'Stop'
$packagePath = (Resolve-Path -LiteralPath $Package).Path
Add-Type -AssemblyName System.IO.Compression.FileSystem
$archive = [IO.Compression.ZipFile]::OpenRead($packagePath)
try {
    $entries = @{}
    foreach ($entry in $archive.Entries) {
        $entries[$entry.FullName.Replace('\', '/')] = $entry.Length
    }
    foreach ($required in @(
        '.wpm/package.txt',
        '.wpm/index.csv',
        '.wpm/install.cmd',
        '.wpm/remove.cmd',
        'packaging/wpm/Package-Lifecycle.ps1',
        'payload/bridge.py',
        'payload/requirements.txt',
        'payload/run-windows.ps1',
        'payload/Install-WindowsLauncher.ps1',
        'payload/modules/brain.py',
        'payload/assets/overlord.ico',
        'payload/tools/overlord_console.py'
    )) {
        if (-not $entries.ContainsKey($required) -or $entries[$required] -eq 0) {
            throw "WPM package is missing required non-empty entry: $required"
        }
    }
    foreach ($entry in $entries.Keys) {
        if ($entry -match '(^|/)(\.env|\.venv|__pycache__)(/|$)' -or
            $entry -match '\.py[co]$' -or
            $entry -match '(^|/)\.session') {
            throw "WPM package contains private or generated content: $entry"
        }
    }

    $metadataEntry = $archive.GetEntry('.wpm/package.txt')
    $reader = [IO.StreamReader]::new($metadataEntry.Open())
    try {
        $metadata = $reader.ReadToEnd()
    }
    finally {
        $reader.Dispose()
    }
    if ($metadata -notmatch '(?m)^name=overlord-bridge\r?$' -or
        $metadata -notmatch '(?m)^arch=any\r?$') {
        throw 'WPM package identity metadata is invalid.'
    }
    if ($ExpectedVersion -and
        $metadata -notmatch "(?m)^version=$([regex]::Escape($ExpectedVersion))\r?$") {
        throw "WPM package version does not match $ExpectedVersion."
    }
}
finally {
    $archive.Dispose()
}

Write-Host "Validated WPM package structure: $packagePath"
