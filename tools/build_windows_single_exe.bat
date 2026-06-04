@echo off
setlocal enabledelayedexpansion

set "SCRIPT_DIR=%~dp0"
pushd "%SCRIPT_DIR%\.."

where py >nul 2>&1
if %ERRORLEVEL%==0 (
  py -3 tools\build_windows_single_exe.py --onefile
) else (
  python tools\build_windows_single_exe.py --onefile
)

set "EXIT_CODE=%ERRORLEVEL%"
popd
exit /b %EXIT_CODE%
