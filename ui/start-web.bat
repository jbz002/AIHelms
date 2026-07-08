@echo off
wt.exe cmd /k "cd /d %~dp0 && echo Starting web dev server... && echo. && call npm run dev --workspace=@aihelms/web && pause"
