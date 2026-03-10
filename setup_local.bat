@echo off
setlocal
set "SCRIPT_DIR=%~dp0"
set "EXEC_POLICY=%POWERSHELL_EXEC_POLICY%"
if "%EXEC_POLICY%"=="" set "EXEC_POLICY=RemoteSigned"
powershell -ExecutionPolicy %EXEC_POLICY% -File "%SCRIPT_DIR%setup_local.ps1" %*
