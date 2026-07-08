@echo off
cd /d "%~dp0\.."
.venv\Scripts\uvicorn.exe main:app --reload --host 0.0.0.0 --port 8000
