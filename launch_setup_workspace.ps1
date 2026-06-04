param(
  [switch]$PlanOnly,
  [switch]$SkipSetup,
  [switch]$SkipDesktopInstall
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
  "$repo\tools\run_setup_workspace.py",
  "--repo-root", "$repo"
)
if ($PlanOnly) {
  $cmd += "--plan-only"
}
if ($SkipSetup) {
  $cmd += "--skip-setup"
}
if ($SkipDesktopInstall) {
  $cmd += "--skip-desktop-install"
}

& $cmd[0] $cmd[1..($cmd.Length-1)]
exit $LASTEXITCODE
