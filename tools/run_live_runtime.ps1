param(
  [string]$Memories = "",
  [string]$FromLiveManifest = "",
  [string]$Host = "127.0.0.1",
  [int]$Port = 7340,
  [string]$ModelName = "numquam-oblita-runtime",
  [double]$MaxSeconds = 0.0,
  [switch]$PlanOnly
)

$repo = Split-Path -Parent $PSScriptRoot

if ($Memories -and $FromLiveManifest) {
  Write-Error "Flags -Memories and -FromLiveManifest are mutually exclusive."
  exit 2
}

if (-not $Memories -and -not $FromLiveManifest) {
  $Memories = Join-Path $repo ".runtime\imports\atoms.sqlite3"
}

Write-Host "NumquamOblita live runtime launcher"
if ($FromLiveManifest) {
  Write-Host "Manifest: $FromLiveManifest"
} else {
  Write-Host "Memories: $Memories"
}
Write-Host "URL:      http://$Host`:$Port"
if ($PlanOnly) {
  Write-Host "Mode:     plan-only"
}

$cmd = @(
  "python",
  "$repo\tools\run_live_runtime.py",
  "--host", "$Host",
  "--port", "$Port",
  "--model-name", "$ModelName",
  "--max-seconds", "$MaxSeconds"
)
if ($FromLiveManifest) {
  $cmd += @("--from-live-manifest", "$FromLiveManifest")
} else {
  $cmd += @("--memories", "$Memories")
}
if ($PlanOnly) {
  $cmd += "--plan-only"
}

& $cmd[0] $cmd[1..($cmd.Length-1)]

if ($LASTEXITCODE -ne 0) {
  Write-Host "Live runtime launch failed."
  exit $LASTEXITCODE
}
