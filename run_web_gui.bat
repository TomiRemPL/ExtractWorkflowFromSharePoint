@echo off
cd /d "%~dp0"
title DORA Web GUI (NiceGUI)
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" main_web.py --show %*
) else (
    where uv >nul 2>&1
    if %errorlevel%==0 (
        uv run python main_web.py --show %*
    ) else (
        python main_web.py --show %*
    )
)
if errorlevel 1 pause
