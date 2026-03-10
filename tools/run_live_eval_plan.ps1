param(
  [string]$Memories = "",
  [int]$RequestedCases = 120,
  [int]$ScanBudget = 600000
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
$logDir = Join-Path $repo "runtime\evals"
New-Item -ItemType Directory -Path $logDir -Force | Out-Null
$logPath = Join-Path $logDir ("plan_{0}.log" -f $stamp)

Write-Host "NumquamOblita live eval plan-only"
Write-Host "Memories: $Memories"
Write-Host "Log:      $logPath"

python "$repo\tools\run_truthset_eval.py" `
  --memories "$Memories" `
  --requested-cases $RequestedCases `
  --scan-budget $ScanBudget `
  --plan-only `
  --log-file "$logPath"

if ($LASTEXITCODE -ne 0) {
  Write-Host "Failed. See log: $logPath"
  exit $LASTEXITCODE
}

Write-Host "Done. Log written to: $logPath"
