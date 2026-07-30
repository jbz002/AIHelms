---
name: xsj-build
description: XSJ 项目 Docker 部署指南。处理网络问题、镜像构建、服务更新等常见部署场景。当用户提到 Docker 部署、容器构建、docker-compose、镜像更新、服务重启、pip/apt 连接失败、DNS 解析失败、容器内代码未更新、构建报 EMFILE/os error 24/Too many open files、端口外部访问超时/防火墙放行/ufw、supervisord 启动失败/ENV 未展开、脚本 exec no such file（CRLF）、AIHub 单点登录 SSO 接入时使用此 skill。即使用户只是提到"部署"、"更新服务"或"构建镜像"，也应触发此 skill。
---

# XSJ 项目 Docker 部署指南

## 核心问题：Docker 网络配置

服务器上 Docker 默认 bridge 网络无法访问外网，必须使用 **host 网络**。

### docker-compose.yml 配置

```yaml
services:
  toolbox:
    build:
      context: .
      dockerfile: Dockerfile
      network: host    # 构建时使用宿主机网络
    image: toolbox:latest
    container_name: toolbox
    restart: unless-stopped
    network_mode: host  # 运行时也使用宿主机网络
```

两个 `host` 缺一不可：`build.network: host` 解决构建时 pip/apt 联网，`network_mode: host` 解决运行时服务可达性。

## 部署命令

### 代码更新后重新部署

```bash
# 1. 同步代码
git pull

# 2. 重新构建镜像（自动使用 host 网络）
sudo docker compose build

# 3. 启动服务
sudo docker compose up -d

# 4. 查看日志确认正常运行
sudo docker compose logs -f
```

### 强制完全重建

```bash
sudo docker compose down
sudo docker rmi toolbox:latest
sudo docker compose build --no-cache
sudo docker compose up -d
```

### 仅重启（代码未变化）

```bash
sudo docker compose restart
```

## 验证更新是否生效

```bash
# 查看容器内的代码
sudo docker exec toolbox cat /app/tools/bom_diff/writer.py | head -20

# 对比本地文件
head -20 tools/bom_diff/writer.py
```

## 常见问题

### 问题1：docker-compose 命令不存在

现代 Docker 已整合 compose 为子命令，使用 `docker compose`（无横线）。

deploy.sh 自动检测脚本：
```bash
if docker compose version &> /dev/null 2>&1; then
    COMPOSE_CMD="docker compose"
elif command -v docker-compose &> /dev/null; then
    COMPOSE_CMD="docker-compose"
fi
```

### 问题2：代码更新但容器内代码未更新

原因：重启容器不会更新镜像中的代码。必须重新构建镜像：

```bash
sudo docker compose build
sudo docker compose up -d
```

**解决方案：挂载代码目录**

```yaml
volumes:
  - ../app:/app/app
  - ../scripts:/app/scripts
  - ../config.prod.toml:/app/config.prod.toml:ro
```

这样只需 `git pull && docker compose restart` 即可更新代码。

### 问题3：pip/apt 连接失败

错误信息：`Temporary failure in name resolution` 或 `Failed to establish a new connection`

原因：Docker bridge 网络无法解析 DNS。

**方案1（推荐）**：使用 host 网络构建
```yaml
build:
  network: host
```

**方案2**：配置 Docker DNS
```bash
sudo tee /etc/docker/daemon.json <<EOF
{
  "dns": ["8.8.8.8", "114.114.114.114"]
}
EOF
sudo systemctl restart docker
```

### 问题4：配置文件不存在

错误信息：`[WARN] 配置文件 /app/config.prod.toml 不存在`

原因：配置文件在项目根目录，但没有挂载到容器内。

**解决方案**：在 docker-compose.yml 中挂载配置文件：
```yaml
volumes:
  - ../config.prod.toml:/app/config.prod.toml:ro
```

### 问题5：健康检查失败

错误信息：`dependency failed to start: container xxx is unhealthy`

**可能原因及解决方案**：

1. **容器内没有 curl 命令** - `python:3.11-slim` 镜像默认不包含 curl
   ```dockerfile
   RUN apt-get update && apt-get install -y --no-install-recommends curl
   ```

2. **健康检查路径错误** - 确保路径返回 200 状态码
   ```yaml
   healthcheck:
     test: ["CMD", "curl", "-f", "http://localhost:38200/api/sources"]
   ```

3. **多进程模式下健康检查不稳定** - uvicorn 多 worker 模式可能导致健康检查时序问题，增加重试次数：
   ```yaml
   healthcheck:
     interval: 10s
     timeout: 10s
     retries: 5
   ```

### 问题6：Python 模块找不到

错误信息：`ModuleNotFoundError: No module named 'app'`

原因：在容器内执行脚本时，Python 路径未设置。

**解决方案**：设置 PYTHONPATH 环境变量
```bash
docker compose exec -e PYTHONPATH=/app api python scripts/init_db.py
```

### 问题7：pyproject.toml 引用 README.md 导致构建失败

错误信息：`OSError: Readme file does not exist: README.md`

原因：Dockerfile 中只复制了 `pyproject.toml`，但 `pyproject.toml` 引用了 `README.md`。

**解决方案**：同时复制 README.md
```dockerfile
COPY pyproject.toml README.md ./
```

### 问题8：uvicorn 命令找不到

错误信息：`executable file not found in $PATH`

原因：多阶段构建时只复制了 `site-packages`，没有复制 `/usr/local/bin`。

**解决方案**：使用单阶段构建，或同时复制 bin 目录：
```dockerfile
# 方案1：单阶段构建（推荐，更简单）
FROM python:3.11-slim
# 直接安装，无需复制

# 方案2：多阶段构建时复制 bin
COPY --from=builder /usr/local/bin /usr/local/bin
```

## Dockerfile 标准模板

### 单阶段构建（推荐，简单可靠）

```dockerfile
FROM python:3.11-slim

WORKDIR /app

# 使用阿里云镜像源加速，安装curl
RUN sed -i 's/deb.debian.org/mirrors.aliyun.com/g' /etc/apt/sources.list.d/debian.sources && \
    apt-get update && apt-get install -y --no-install-recommends curl && \
    rm -rf /var/lib/apt/lists/* && \
    pip install --no-cache-dir --upgrade pip uv -i https://mirrors.aliyun.com/pypi/simple/ --trusted-host mirrors.aliyun.com

# 安装依赖
COPY pyproject.toml README.md ./
RUN uv pip install --system --no-cache . --index-url https://mirrors.aliyun.com/pypi/simple/ --trusted-host mirrors.aliyun.com

# 安装 Playwright（如需要）
RUN playwright install chromium --with-deps

# 复制应用代码
COPY app/ ./app/
COPY scripts/ ./scripts/

EXPOSE 38200

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "38200", "--workers", "4"]
```

### 多阶段构建（减小镜像体积）

```dockerfile
FROM python:3.11 AS builder
WORKDIR /app
RUN pip install --no-cache-dir --upgrade pip uv -i https://mirrors.aliyun.com/pypi/simple/ --trusted-host mirrors.aliyun.com
COPY pyproject.toml README.md ./
RUN uv pip install --system --no-cache . --index-url https://mirrors.aliyun.com/pypi/simple/ --trusted-host mirrors.aliyun.com

FROM python:3.11-slim
WORKDIR /app
RUN sed -i 's/deb.debian.org/mirrors.aliyun.com/g' /etc/apt/sources.list.d/debian.sources && \
    apt-get update && apt-get install -y --no-install-recommends curl && \
    rm -rf /var/lib/apt/lists/*
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin
COPY app/ ./app/
EXPOSE 38200
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "38200"]
```

模板要点：
- 使用阿里云镜像源加速 pip 和 apt
- **必须安装 curl** 用于健康检查
- 多阶段构建需复制 `/usr/local/bin`
- 健康检查在 docker-compose.yml 中配置更灵活

### 问题9：Docker Compose 项目名冲突（孤儿容器）

**现象**：部署新项目时，Docker 报其他项目的容器为"孤儿容器"（orphan containers），甚至尝试停止/删除它们。

**根因**：Docker Compose 默认用 compose 文件所在目录名作为项目名。如果两个项目的 compose 文件都在名为 `docker` 的目录下（如 `/home/app/ai-hub/docker/docker-compose.prod.yml` 和 `/home/app/im-tools/docker/docker-compose.yml`），它们会被合并到同一个项目 `docker` 下。部署其中一个时，Docker 发现 compose 文件里没有另一个项目的 service 定义，就把它们当孤儿容器处理。

**解决方案**：两层保护

**1. 创建 `.env` 文件**（Docker Compose 自动读取）：

在 compose 文件所在目录（如 `docker/`）下创建 `.env`：

```bash
echo 'COMPOSE_PROJECT_NAME=<项目名>' > /path/to/project/docker/.env
```

例如 AI Hub 项目：
```bash
echo 'COMPOSE_PROJECT_NAME=aihub' > /home/app/ai-hub/docker/.env
```

**2. deploy.sh 中加 `-p` 参数**（双保险）：

```bash
COMPOSE_PROJECT="aihub"

# 所有 docker compose 命令都加上 -p
$COMPOSE_CMD -p "$COMPOSE_PROJECT" -f "$COMPOSE_FILE" up -d
$COMPOSE_CMD -p "$COMPOSE_PROJECT" -f "$COMPOSE_FILE" build ...
```

### 问题10：build 时 EMFILE (os error 24) — 宿主 ulimit 太低

**现象**：`docker build` / `buildx build` 时 `uv` 字节码编译或 pip 报 `os error 24` / `EMFILE` / `Too many open files`，中途失败。

**根因**：宿主默认 `ulimit -n=1024`（查 `ulimit -n`），构建时 uv 并发编译开大量文件描述符耗尽。buildx 某些阶段继承宿主 ulimit 限制。

**方案**：buildx 显式提 ulimit（compose `build:` 块不支持 ulimit，需命令行先 build）：

```bash
sudo docker buildx build --load --network host \
  --ulimit nofile=1048576:1048576 \
  -t <image>:<tag> -f Dockerfile .
sudo docker compose -p <项目> -f docker-compose.prod.yml up -d
```

### 问题11：Windows 同步脚本 CRLF 致 exec 失败

**现象**：容器启动报 `exec /app/start.sh: no such file or directory`，但 `ls` 文件明明存在、有执行权限。

**根因**：Windows 开发，shell 脚本经 git 同步带 CRLF 行结束符，shebang 变成 `#!/bin/bash\r`，内核找不到带 `\r` 的解释器。

**方案**（任选）：
- entrypoint 启动前转 LF：`sed -i 's/\r$//' /app/start.sh /app/entrypoint.sh`
- 根治：`.gitattributes` 加 `*.sh text eol=lf`，或 git `core.autocrlf=input`。

### 问题12：host 模式端口外部不可达 — 宿主防火墙（ufw）

**现象**：host 网络服务 `ss -tln` 监听 `0.0.0.0:<port>`，`curl 127.0.0.1:<port>` 本机通，**但跨机/外部访问超时**（`curl` 返回 000 / 浏览器 ERR_TIMEDOUT）。

**根因**：host 模式 + daemon `"iptables": false` → Docker 不再管防火墙，端口外部可达性全靠**宿主防火墙**。若宿主 INPUT 默认 DROP（被 ufw 接管），新端口未放行即被挡。与"服务起没起"无关，纯防火墙。

**诊断**：
```bash
sudo iptables -L INPUT -n -v --line-numbers
# policy DROP + 规则全跳 ufw-before-input / ufw-after-input 等 ufw-* 链 = ufw 管
# 若看不到放行 <port> 的规则但该端口外部可达 → 在云安全组，登云控制台改
sudo ufw status numbered
ip -br addr          # 查物理网卡名与对应 IP
```

**方案**：用 ufw 放行（**不要** `iptables -I`，会被 ufw 体系绕开、重启丢）：

```bash
# 仅放行业务内网网卡（如 ens29f1=131.131.2.10），公网网卡不开
sudo ufw allow in on ens29f1 proto tcp to any port 30700:30799
sudo ufw status numbered | grep 30700   # 验证落位
```

ufw 自动持久化到 `/etc/ufw/user.rules`。多网卡场景技术主管常要求"只放开网卡1"——按业务网卡放行，公网网卡留关闭。

> 三物理网卡典型布局：ens29f0 公网 / ens29f1 业务内网 / ens29f2 其他内网。"网卡1"按编号常指 ens29f1，**务必与主管确认是哪块**。

### 问题13：supervisord `%(ENV_xxx)s` 无法展开

**现象**：单容器多进程（supervisord 跑 gunicorn + celery 等）启动失败，日志报 `key 'ENV_XXX' not found` 或配置里 `%(ENV_XXX)s` 原样输出到命令行。

**根因**：supervisord 配置引用了 `%(ENV_xxx)s`，但 `.env` / compose `environment` 缺该变量。supervisord 对 ENV 引用严格，缺任一即失败，不像 shell 有空默认。

**方案**：补齐 supervisord 引用的**所有**变量（常见 `CELERY_LOGLEVEL`、`CELERY_PREFETCH_MULTIPLIER`、`CELERY_WORKER_CONCURRENCY` 等），验证：

```bash
sudo docker exec <container> env | grep -E 'CELERY|GUNICORN'
```

### 问题14：子系统接入 XSJ AIHub 单点登录（SSO）

XSJ 各子系统（如 aihelms）统一走 AIHub（`...:30080`）OAuth2 授权码登录，**无本地账号体系**，部署完服务≠能用，必须打通 SSO。

**接入清单**（AIHub 管理员侧 + 子系统侧）：

1. **AIHub 应用管理 → 新增应用**：
   - 应用编码（= 子系统 app_code，如 `aihelms`）、类型选**外部链接**、入口 URL（子系统外网/内网地址）。
   - 编辑该应用 → 应用内角色 → 添加成员 → 选用户 + 角色标签（如 `aihelms-admin`）回车。子系统靠 `app_roles` 判权限。

2. **子系统后端 `.env`**：
   ```
   AI_HUB_URL=http://127.0.0.1:30080       # 同机换 token，走 127.0.0.1
   AI_HUB_APP_CODE=<app_code>
   AI_HUB_ADMIN_ROLE=<管理员角色标签>        # app_roles 含此 → is_admin=True
   ```

3. **子系统前端**（build 时注入，**改必 rebuild 镜像**）：
   ```
   VITE_AI_HUB_URL=http://<浏览器可达地址>:30080   # 用户浏览器跳转，填可达 IP 非127.0.0.1
   ```

4. **SSO 链路**：前端登录按钮 → `${AI_HUB_URL}/api/v1/auth/authorize?redirect_uri=<origin>/auth/callback&app_code=<code>` → AIHub 授权 → 回调 `?code=` → 后端 `POST /api/v1/auth/token` 换 token → `GET /api/v1/auth/me?app_code=` 拿 `app_roles` → 签本地 JWT。

**常见坑**：
- 前端 `VITE_AI_HUB_URL` 写成测试服地址、上线忘改 → rebuild 注入新地址。
- AIHub 该环境没注册此应用（测试服注册≠生产服注册）→ 生产 AIHub 需重新注册。
- 后端 `AI_HUB_URL` 填浏览器地址（外网）→ 同机换 token 应走 `127.0.0.1`，否则绕一圈走公网。

## 常用命令速查

| 命令 | 用途 |
|------|------|
| `docker compose ps` | 查看服务状态 |
| `docker compose logs -f` | 查看实时日志 |
| `docker compose logs -f api` | 查看指定服务日志 |
| `docker compose down` | 停止并删除容器 |
| `docker compose restart` | 重启服务 |
| `docker compose build --no-cache` | 强制重建镜像 |
| `docker rmi <image>:latest` | 删除镜像 |
| `docker exec <container> cat /app/xxx` | 查看容器内文件 |
| `docker logs <container> --tail 50` | 查看容器日志 |
| `curl -f http://localhost:port/path` | 手动测试健康检查 |