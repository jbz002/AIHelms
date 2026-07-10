@echo off
cd /d "%~dp0\..\apps"
uv run celery -A celery_app worker --pool=solo --loglevel=info
