param(
    [Parameter(Mandatory = $true)][string]$Path,
    [int]$Skip = 0,
    [int]$First = 200
)
$lines = Get-Content -LiteralPath $Path
$end = [Math]::Min($lines.Count, $Skip + $First)
for ($i = $Skip; $i -lt $end; $i++) {
    '{0,5}: {1}' -f ($i + 1), $lines[$i]
}