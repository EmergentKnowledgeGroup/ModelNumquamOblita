$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

$pythonExe = if (Get-Command py -ErrorAction SilentlyContinue) { "py" } elseif (Get-Command python -ErrorAction SilentlyContinue) { "python" } else { "python3" }
$pythonArgs = if ($pythonExe -eq "py") { @("-3") } else { @() }
$scriptArgs = @("tools/build_windows_single_exe.py", "--onefile")

Write-Output "Running: $pythonExe $(($pythonArgs + $scriptArgs) -join ' ')"
& $pythonExe @pythonArgs @scriptArgs
