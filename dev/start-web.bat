@echo off
wt.exe cmd /k "cd /d %~dp0..\ui && echo Starting admin dev server... && echo. && call npm run dev --workspace=@aihelms/admin && pause" ; cmd /k "cd /d %~dp0..\ui && echo Starting web dev server... && echo. && call npm run dev --workspace=@aihelms/web && pause"
