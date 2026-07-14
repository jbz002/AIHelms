@echo off

:: 获取项目根目录（dev/ 的上级目录）
pushd "%~dp0.."
set "WIN_PATH=%CD%"
popd

:: 转换 Windows 路径为 WSL 路径 (D:\project\AIHelms -> /mnt/d/project/AIHelms)
for /f "delims=" %%i in ('wsl wslpath "%WIN_PATH%"') do set "WSL_ROOT=%%i"

echo 通过 WSL2 启动中间件（db, redis, litellm, skillspector, docs-mcp-server）...
wsl -e bash -c "cd '%WSL_ROOT%' && docker compose -f docker-compose.middleware.yaml -p aihelms up -d db redis litellm skillspector docs-mcp-worker docs-mcp-server docs-mcp-web"

echo.
echo 中间件状态：
wsl -e bash -c "cd '%WSL_ROOT%' && docker compose -f docker-compose.middleware.yaml -p aihelms ps"

pause
