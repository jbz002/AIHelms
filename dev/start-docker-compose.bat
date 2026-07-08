@echo off
cd /d "%~dp0\.."
docker compose -f docker-compose.middleware.yaml -p aihelms up -d
pause
