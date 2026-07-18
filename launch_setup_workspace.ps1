param(
  [switch]$PlanOnly,
  [switch]$SkipSetup,
  [switch]$SkipDesktopInstall
)

$repo = Split-Path -Parent $MyInvocation.MyCommand.Path

$selectedPython = $null
$candidates = [System.Collections.Generic.List[object]]::new()
if ($env:MNO_PYTHON) {
  if ($env:MNO_PYTHON -match '^py(?:\.exe)?\s+(-3\.\d+)$') { $candidates.Add([pscustomobject]@{ Exe = "py"; Args = @($Matches[1]) }) }
  else { $candidates.Add([pscustomobject]@{ Exe = $env:MNO_PYTHON; Args = @() }) }
}
foreach ($version in @("-3.12", "-3.13", "-3.14", "-3.15")) { $candidates.Add([pscustomobject]@{ Exe = "py"; Args = @($version) }) }
foreach ($exe in @("python3.15", "python3.14", "python3.13", "python3.12", "python")) { $candidates.Add([pscustomobject]@{ Exe = $exe; Args = @() }) }
foreach ($candidate in $candidates) {
  if (-not (Get-Command $candidate.Exe -ErrorAction SilentlyContinue) -and -not (Test-Path -LiteralPath $candidate.Exe)) { continue }
  $candidateArgs = @($candidate.Args)
  & $candidate.Exe @candidateArgs -c "import sys, venv, xml.parsers.expat; raise SystemExit(0 if sys.version_info >= (3, 12) else 1)" 2>$null
  if ($LASTEXITCODE -eq 0) { $selectedPython = $candidate; break }
}
if ($null -eq $selectedPython) {
  Write-Error "setup failed: Python not found in PATH. Install Python 3.12+ and retry."
  exit 2
}

$cmd = @(
  "$repo\tools\run_setup_workspace.py",
  "--repo-root", "$repo",
  "--python-cmd", ((@($selectedPython.Exe) + @($selectedPython.Args)) -join " ")
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

$pythonArgs = @($selectedPython.Args)
& $selectedPython.Exe @pythonArgs @cmd
exit $LASTEXITCODE
