@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist logs mkdir logs
py -3.12 --version >nul 2>nul
if %errorlevel%==0 (
  py -3.12 scripts\bootstrap.py --command daily >> logs\bootstrap.log 2>&1
) else (
  python scripts\bootstrap.py --command daily >> logs\bootstrap.log 2>&1
)
echo Daily task finished. See logs\bootstrap.log
pause
