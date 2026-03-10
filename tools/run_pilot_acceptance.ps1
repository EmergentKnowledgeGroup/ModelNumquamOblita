param(
  [string]$Memories = "",
  [string]$Truthset = "",
  [switch]$RequireReviewedTruthset,
  [int]$TruthsetMinCases = 6,
  [int]$TruthsetMinSupported = 3,
  [int]$TruthsetMinUnsupported = 2,
  [switch]$SkipTruthsetQualityGate,
  [int]$RequestedCases = 12,
  [int]$LoadTurns = 12,
  [int]$ScanBudget = 600000,
  [int]$BatchSize = 2,
  [int]$BatchPauseMs = 100
)

$repo = Split-Path -Parent $PSScriptRoot
if (-not $Memories -or [string]::IsNullOrWhiteSpace($Memories)) {
  $defaultSqlite = Join-Path $repo ".runtime\imports\atoms.sqlite3"
  if (Test-Path $defaultSqlite) {
    $Memories = $defaultSqlite
  } else {
    $Memories = Join-Path $repo "runtime\imports\memories.json"
  }
}

Write-Host "NumquamOblita pilot acceptance"
Write-Host "Memories: $Memories"
if ($Truthset -and -not [string]::IsNullOrWhiteSpace($Truthset)) {
  Write-Host "Truthset: $Truthset"
} else {
  Write-Host "Truthset: (auto reviewed if available, else generated)"
}
Write-Host "Cases:    $RequestedCases"
Write-Host "Turns:    $LoadTurns"
Write-Host "Batch:    size=$BatchSize pauseMs=$BatchPauseMs"
if ($RequireReviewedTruthset) {
  Write-Host "Truthset policy: reviewed required"
}
if ($SkipTruthsetQualityGate) {
  Write-Host "Truthset quality gate: skipped"
} else {
  Write-Host "Truthset quality gate: minCases=$TruthsetMinCases minSupported=$TruthsetMinSupported minUnsupported=$TruthsetMinUnsupported"
}

$cmd = @(
  "python",
  "$repo\tools\run_pilot_acceptance.py",
  "--memories", "$Memories",
  "--requested-cases", "$RequestedCases",
  "--load-turns", "$LoadTurns",
  "--scan-budget", "$ScanBudget",
  "--batch-size", "$BatchSize",
  "--batch-pause-ms", "$BatchPauseMs",
  "--truthset-min-cases", "$TruthsetMinCases",
  "--truthset-min-supported", "$TruthsetMinSupported",
  "--truthset-min-unsupported", "$TruthsetMinUnsupported"
)
if ($Truthset -and -not [string]::IsNullOrWhiteSpace($Truthset)) {
  $cmd += @("--truthset", "$Truthset")
}
if ($RequireReviewedTruthset) {
  $cmd += "--require-reviewed-truthset"
}
if ($SkipTruthsetQualityGate) {
  $cmd += "--skip-truthset-quality-gate"
}
& $cmd[0] $cmd[1..($cmd.Length-1)]

if ($LASTEXITCODE -ne 0) {
  Write-Host "Pilot acceptance failed. Check runtime\\pilot\\<stamp> for logs and support bundle."
  exit $LASTEXITCODE
}

Write-Host "Pilot acceptance complete."
