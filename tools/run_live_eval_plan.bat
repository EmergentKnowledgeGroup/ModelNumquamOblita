@echo off
setlocal
set "SCRIPT_DIR=%~dp0"
set "EXEC_POLICY=%LIVE_EVAL_EXEC_POLICY%"
if "%EXEC_POLICY%"=="" set "EXEC_POLICY=RemoteSigned"
powershell -ExecutionPolicy %EXEC_POLICY% -File "%SCRIPT_DIR%run_live_eval_plan.ps1" %*
exit /b %ERRORLEVEL%
