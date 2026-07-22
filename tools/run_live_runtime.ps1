param(
  [string]$Memories = "",
  [string]$FromLiveManifest = "",
  [Alias("Host")]
  [string]$BindHost = "127.0.0.1",
  [int]$Port = 7340,
  [string]$ModelName = "numquam-oblita-runtime",
  [string]$Episodes = "",
  [switch]$AllowUncurated,
  [double]$MaxSeconds = 0.0,
  [switch]$PlanOnly
)

$repo = Split-Path -Parent $PSScriptRoot

if ($Memories -and $FromLiveManifest) {
  Write-Error "Flags -Memories and -FromLiveManifest are mutually exclusive."
  exit 2
}

if (-not $Memories -and -not $FromLiveManifest) {
  $Memories = Join-Path $repo "runtime\imports\atoms.sqlite3"
}

Write-Host "NumquamOblita live runtime launcher"
if ($FromLiveManifest) {
  Write-Host "Manifest: $FromLiveManifest"
} else {
  Write-Host "Memories: $Memories"
}
Write-Host "URL:      http://$BindHost`:$Port"
if ($PlanOnly) {
  Write-Host "Mode:     plan-only"
}

$cmd = @(
  "python",
  "$repo\tools\run_live_runtime.py",
  "--host", "$BindHost",
  "--port", "$Port",
  "--model-name", "$ModelName",
  "--max-seconds", "$MaxSeconds"
)
if ($FromLiveManifest) {
  $cmd += @("--from-live-manifest", "$FromLiveManifest")
} else {
  $cmd += @("--memories", "$Memories")
}
if ($Episodes) {
  $cmd += @("--episodes", "$Episodes")
}
if ($AllowUncurated) {
  $cmd += "--allow-uncurated"
}
if ($PlanOnly) {
  $cmd += "--plan-only"
}

& $cmd[0] $cmd[1..($cmd.Length-1)]

if ($LASTEXITCODE -ne 0) {
  Write-Host "Live runtime launch failed."
  exit $LASTEXITCODE
}

