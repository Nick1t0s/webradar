@echo off
cd /d "%~dp0\.."
python -m perspective
if errorlevel 1 pause
