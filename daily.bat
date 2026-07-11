@echo off
chcp 65001 >nul
cd /d "%~dp0"
py -3.12 --version >nul 2>nul
if %errorlevel%==0 (
  py -3.12 scripts\bootstrap.py --command daily
) else (
  python scripts\bootstrap.py --command daily
)
pause
