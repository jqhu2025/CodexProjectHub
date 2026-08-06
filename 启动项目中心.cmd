@echo off
setlocal
cd /d "%~dp0"

where pythonw.exe >nul 2>nul
if not errorlevel 1 (
    start "Codex 项目中心" pythonw.exe "%~dp0app_qt.pyw"
    exit /b 0
)

where pyw.exe >nul 2>nul
if not errorlevel 1 (
    start "Codex 项目中心" pyw.exe -3 "%~dp0app_qt.pyw"
    exit /b 0
)

echo 未找到 Python。请先安装 Python 3 和项目依赖：
echo     python -m pip install -r requirements.txt
pause
