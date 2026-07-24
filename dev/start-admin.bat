@echo off
chcp 65001 >nul
cd /d "%~dp0\..\ui"

echo Starting admin dev server...
echo.
call npm run dev --workspace=@aihelms/admin
pause
