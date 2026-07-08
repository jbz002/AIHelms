@echo off
wt.exe cmd /k "cd /d %~dp0 && echo Starting admin dev server... && echo. && call npm run dev --workspace=@aihelms/admin && pause"
