@echo off
setlocal
set "SCRIPT_DIR=%~dp0"
powershell -ExecutionPolicy RemoteSigned -File "%SCRIPT_DIR%launch_setup_workspace.ps1" %*
