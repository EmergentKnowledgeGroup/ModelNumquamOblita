param(
  [switch]$PlanOnly,
  [switch]$PreflightOnly,
  [switch]$SkipSmoke,
  [string]$Venv = ".venv"
)

$repo = Split-Path -Parent $MyInvocation.MyCommand.Path

$pythonCmd = ""
if (Get-Command py -ErrorAction SilentlyContinue) {
  $pythonCmd = "py"
} elseif (Get-Command python -ErrorAction SilentlyContinue) {
  $pythonCmd = "python"
} else {
  Write-Error "setup failed: Python not found in PATH. Install Python 3.12+ and retry."
  exit 2
}

$cmd = @(
  $pythonCmd,
  "$repo\tools\setup_local.py",
  "--repo-root", "$repo",
  "--venv", "$Venv"
)
if ($PlanOnly) {
  $cmd += "--plan-only"
}
if ($PreflightOnly) {
  $cmd += "--preflight-only"
}
if ($SkipSmoke) {
  $cmd += "--skip-smoke"
}

& $cmd[0] $cmd[1..($cmd.Length-1)]
exit $LASTEXITCODE
