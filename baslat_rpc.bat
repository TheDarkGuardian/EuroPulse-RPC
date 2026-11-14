@echo off
where pythonw >nul 2>&1
if not errorlevel 1 (
    start "" pythonw "%~dp0ets2_rpc.py"
    exit /b 0
)
where pyw >nul 2>&1
if not errorlevel 1 (
    start "" pyw "%~dp0ets2_rpc.py"
    exit /b 0
)
start "" python "%~dp0ets2_rpc.py"
