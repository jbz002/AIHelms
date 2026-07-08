@echo off
cd /d "%~dp0\..\apps"
.venv\Scripts\celery.exe -A celery_app worker --pool=solo --loglevel=info
