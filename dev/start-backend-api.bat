@echo off
chcp 65001 >nul
cd /d "%~dp0\..\apps"

:: 检测 WSL2 IP 并设置连接地址（与 dev/start-api 逻辑一致）
:: 如果获取不到 WSL IP 则回退 localhost（vmIdleTimeout=-1 保证转发可靠）
for /f "usebackq tokens=*" %%i in (`wsl -e bash -c "ip -4 addr show eth0 2>/dev/null | grep -oP 'inet \K[\d.]+'" 2^>nul`) do set WSL_IP=%%i

if defined WSL_IP (
    echo WSL2 IP: %WSL_IP%
    set DB_HOST=%WSL_IP%
    set REDIS_HOST=%WSL_IP%
    set LITELLM_HOST=%WSL_IP%
    set AI_POLICIES_SCANNER_URL=http://%WSL_IP%:8010
    set DOCS_MCP_SERVER_URL=http://%WSL_IP%:8080/api
    set DOCS_MCP_SERVER_WEB_URL=http://%WSL_IP%:6281
) else (
    echo WSL2 IP 未获取到，使用 localhost 转发
    set DB_HOST=localhost
    set REDIS_HOST=localhost
    set LITELLM_HOST=localhost
    set AI_POLICIES_SCANNER_URL=http://localhost:8010
    set DOCS_MCP_SERVER_URL=http://localhost:8080/api
    set DOCS_MCP_SERVER_WEB_URL=http://localhost:6281
)

:: 开发环境日志目录
set LOG_DIR=%~dp0..\logs

uv run uvicorn main:app --reload --host 0.0.0.0 --port 8000
