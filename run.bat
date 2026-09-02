@echo off
chcp 65001 >nul
rem RuiC-VideoGrab Windows 一键启动：首次运行自动创建 venv、安装依赖和无头浏览器
cd /d "%~dp0"

rem 1. 虚拟环境与依赖
if not exist ".venv\Scripts\python.exe" (
  echo [RuiC-VideoGrab] 首次运行：创建虚拟环境并安装依赖...
  where py >nul 2>nul && (py -3 -m venv .venv) || (python -m venv .venv)
  ".venv\Scripts\pip" install -q --upgrade pip
  ".venv\Scripts\pip" install -q -r requirements.txt
)

rem 2. 无头浏览器（抖音下载依赖，约 95MB）
set "NEED_CHROME=0"
set "PW_DIR=%LOCALAPPDATA%\ms-playwright"
if not exist "%PW_DIR%" set "NEED_CHROME=1"
if exist "%PW_DIR%" (
  dir /b "%PW_DIR%" 2>nul | findstr /i "chromium" >nul
  if errorlevel 1 set "NEED_CHROME=1"
)
if "%NEED_CHROME%"=="1" (
  echo [RuiC-VideoGrab] 安装无头浏览器（抖音下载依赖，约 95MB）...
  ".venv\Scripts\playwright" install chromium
)

rem 3. 启动（2 秒后自动打开浏览器）
echo [RuiC-VideoGrab] 启动 http://127.0.0.1:8900
start "" cmd /c "timeout /t 2 >nul & start "" http://127.0.0.1:8900"
".venv\Scripts\uvicorn" backend.main:app --host 127.0.0.1 --port 8900
