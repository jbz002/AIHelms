@echo off
cd /d "%~dp0\..\apps"
.venv\Scripts\celery.exe -A celery_app beat --loglevel=info
