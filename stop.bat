@echo off
chcp 65001 >nul
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" scripts\stop_panel.py
) else (
  py -3.12 scripts\stop_panel.py
)
timeout /t 2 /nobreak >nul
