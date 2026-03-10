param(
  [string]$Input = "",
  [string]$Store = "",
  [string]$RunDir = "",
  [switch]$SkipImport,
  [int]$RequestedCases = 6,
  [int]$ScanBudget = 600000,
  [ValidateSet("basic", "trust-v2", "trust-v3")]
  [string]$FixtureMode = "trust-v3",
  [int]$BatchSize = 2,
  [int]$BatchPauseMs = 100,
  [int]$ReadoutMaxCases = 12
)

$repo = Split-Path -Parent $PSScriptRoot
if (-not $Store -or [string]::IsNullOrWhiteSpace($Store)) {
  $Store = Join-Path $repo ".runtime\imports\atoms.sqlite3"
}

Write-Host "NumquamOblita one-click eval"
Write-Host "Store: $Store"
if ($SkipImport.IsPresent) {
  Write-Host "Import: skipped"
} else {
  if (-not $Input -or [string]::IsNullOrWhiteSpace($Input)) {
    Write-Host "Import: auto-detect conversations.json"
  } else {
    Write-Host "Import: $Input"
  }
}
if ($RunDir -and -not [string]::IsNullOrWhiteSpace($RunDir)) {
  Write-Host "RunDir: $RunDir"
}
Write-Host "Eval: cases=$RequestedCases scanBudget=$ScanBudget fixture=$FixtureMode batchSize=$BatchSize batchPauseMs=$BatchPauseMs readoutMaxCases=$ReadoutMaxCases"

$args = @(
  "$repo\tools\run_oneclick_eval.py",
  "--store", "$Store",
  "--requested-cases", "$RequestedCases",
  "--scan-budget", "$ScanBudget",
  "--fixture-mode", "$FixtureMode",
  "--batch-size", "$BatchSize",
  "--batch-pause-ms", "$BatchPauseMs",
  "--readout-max-cases", "$ReadoutMaxCases"
)

if ($SkipImport.IsPresent) {
  $args += "--skip-import"
}
if ($Input -and -not [string]::IsNullOrWhiteSpace($Input)) {
  $args += @("--input", "$Input")
}
if ($RunDir -and -not [string]::IsNullOrWhiteSpace($RunDir)) {
  $args += @("--run-dir", "$RunDir")
}

python @args
if ($LASTEXITCODE -ne 0) {
  Write-Host "One-click eval failed. Review output above for manifest path."
  exit $LASTEXITCODE
}
