@echo off
setlocal
set "SCRIPT_DIR=%~dp0"
set "EXEC_POLICY=%POWERSHELL_EXEC_POLICY%"
if "%EXEC_POLICY%"=="" set "EXEC_POLICY=RemoteSigned"
powershell -ExecutionPolicy %EXEC_POLICY% -File "%SCRIPT_DIR%run_live_runtime.ps1" %*
exit /b %ERRORLEVEL%
