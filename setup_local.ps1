param(
  [switch]$PlanOnly,
  [switch]$PreflightOnly,
  [switch]$SkipSmoke,
  [string]$Venv = ".venv"
)

$repo = Split-Path -Parent $MyInvocation.MyCommand.Path

function ConvertTo-MnoArgv([string]$Value) {
  $tokens = [System.Collections.Generic.List[string]]::new()
  foreach ($match in [regex]::Matches($Value, '"(?:\\.|[^"])*"|''(?:''''|[^''])*''|[^\s]+')) {
    $token = $match.Value
    if ($token.Length -ge 2 -and (($token[0] -eq '"' -and $token[-1] -eq '"') -or ($token[0] -eq "'" -and $token[-1] -eq "'"))) {
      $token = $token.Substring(1, $token.Length - 2)
    }
    $tokens.Add($token)
  }
  return @($tokens)
}

$selectedPython = $null
$candidates = [System.Collections.Generic.List[object]]::new()
if ($env:MNO_PYTHON) {
  $overrideArgv = @(ConvertTo-MnoArgv $env:MNO_PYTHON)
  if ($overrideArgv.Count -gt 0) {
    $candidates.Add([pscustomobject]@{ Exe = $overrideArgv[0]; Args = @($overrideArgv | Select-Object -Skip 1) })
  }
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
  "$repo\tools\setup_local.py",
  "--repo-root", "$repo",
  "--venv", "$Venv",
  "--python-cmd", ((@($selectedPython.Exe) + @($selectedPython.Args)) -join " ")
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

$pythonArgs = @($selectedPython.Args)
& $selectedPython.Exe @pythonArgs @cmd
exit $LASTEXITCODE
