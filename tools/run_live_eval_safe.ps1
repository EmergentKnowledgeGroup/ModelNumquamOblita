param(
  [string]$Memories = "",
  [int]$RequestedCases = 6,
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

$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$outDir = Join-Path $repo "runtime\evals\safe_$stamp"
New-Item -ItemType Directory -Path $outDir -Force | Out-Null
$logPath = Join-Path $outDir "live_eval.log"

Write-Host "NumquamOblita safe live eval"
Write-Host "Memories: $Memories"
Write-Host "OutDir:   $outDir"
Write-Host "Log:      $logPath"
Write-Host "Batch:    size=$BatchSize pauseMs=$BatchPauseMs"

python "$repo\tools\run_truthset_eval.py" `
  --memories "$Memories" `
  --requested-cases $RequestedCases `
  --scan-budget $ScanBudget `
  --batch-size $BatchSize `
  --batch-pause-ms $BatchPauseMs `
  --write-partial-artifacts `
  --out-dir "$outDir" `
  --log-file "$logPath"

if ($LASTEXITCODE -ne 0) {
  Write-Host "Failed. See log: $logPath"
  exit $LASTEXITCODE
}

Write-Host "Done. Artifacts: $outDir"
Write-Host "Done. Log written to: $logPath"
