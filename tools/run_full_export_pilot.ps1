param(
  [string]$InputPath = "",
  [string]$Store = "",
  [switch]$SkipImport,
  [int]$RequestedCases = 12,
  [int]$LoadTurns = 12,
  [int]$ScanBudget = 600000,
  [int]$BatchSize = 2,
  [int]$BatchPauseMs = 100
)

$repo = Split-Path -Parent $PSScriptRoot

if (-not $Store -or [string]::IsNullOrWhiteSpace($Store)) {
  $Store = Join-Path $repo ".runtime\imports\atoms.sqlite3"
}

if (-not $InputPath -or [string]::IsNullOrWhiteSpace($InputPath)) {
  $InputPath = Join-Path $repo "conversations.json"
  if (-not (Test-Path $InputPath)) {
    $InputPath = Join-Path (Split-Path -Parent $repo) "User Online Activity\conversations\conversations.json"
  }
}

Write-Host "NumquamOblita full export pilot"
Write-Host "Input:  $InputPath"
Write-Host "Store:  $Store"
Write-Host "Cases:  $RequestedCases"
Write-Host "Turns:  $LoadTurns"
if ($SkipImport) {
  Write-Host "Import: skipped"
}

$cmd = @(
  "python",
  "$repo\tools\run_full_export_pilot.py",
  "--input", "$InputPath",
  "--store", "$Store",
  "--requested-cases", "$RequestedCases",
  "--load-turns", "$LoadTurns",
  "--scan-budget", "$ScanBudget",
  "--batch-size", "$BatchSize",
  "--batch-pause-ms", "$BatchPauseMs"
)
if ($SkipImport) {
  $cmd += "--skip-import"
}

& $cmd[0] $cmd[1..($cmd.Length-1)]

if ($LASTEXITCODE -ne 0) {
  Write-Host "Full export pilot failed. Check runtime\live_runs\live_<stamp>\logs for details."
  exit $LASTEXITCODE
}

Write-Host "Full export pilot complete."
