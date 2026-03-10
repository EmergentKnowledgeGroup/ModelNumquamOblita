@echo off
setlocal
set "SCRIPT=%~dp0run_mcp_connector_gui.py"
where pyw >nul 2>nul
if %ERRORLEVEL%==0 (
  start "NumquamOblita MCP Connector" pyw -3 "%SCRIPT%"
  exit /b 0
)
where py >nul 2>nul
if %ERRORLEVEL%==0 (
  start "NumquamOblita MCP Connector" py -3 "%SCRIPT%"
  exit /b 0
)
mshta "javascript:var sh=new ActiveXObject('WScript.Shell'); sh.Popup('Windows Python 3 is required to open NumquamOblita MCP Connector. Install Python 3 and make sure the py launcher is available.', 0, 'NumquamOblita MCP Connector', 16);close();"
exit /b 1
