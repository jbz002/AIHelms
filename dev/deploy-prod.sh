#!/usr/bin/env bash
# AIHelms 本地一键部署到 prod（131.131.2.10）
# 流程: 本地 tar 打包源码 → ssh 管道解包到服务器 → 服务器 buildx build + recreate aihelms
#
# 为什么不用 git pull / rsync:
#   - prod 服务器 /home/ai/aihelms/AIHelms 不是 git 仓库
#   - prod 访问 github 不通（Failure when receiving data）
#   - 本地 Windows git bash 无 rsync
#   → tar over ssh 是唯一不需装东西、不依赖外网的路径
#
# 用法:
#   bash dev/deploy-prod.sh           # 重建 aihelms（后端 + 前端 dist 改动都够）
#                                    # 前端 dist 经 named volume 共享：aihelms recreate 时
#                                    # start.sh 重跑 cp 覆盖 volume，nginx 直读新 dist，不用动 nginx
#   bash dev/deploy-prod.sh nginx     # 额外 recreate nginx（仅改 docker/nginx/* template 时）
#
# 排除项说明:
#   .env       — 服务器有自己的 prod .env，绝不能覆盖
#   data/logs  — 服务器运行数据/日志
#   node_modules/dist/__pycache__ — 构建产物/依赖，服务器 build 时重装
#   dev/roadmap dev/resource — 本地 only，不进服务器
set -euo pipefail
cd "$(dirname "$0")/.."   # 切到项目根

PROD_DIR=/home/ai/aihelms/AIHelms
IMG=aihelms:prod
PROJ=aihelms
COMPOSE=docker-compose.prod.yml

echo "== 1/3 同步代码（tar → ssh） =="
tar czf - \
  --exclude='./.git' \
  --exclude='./.env' \
  --exclude='node_modules' \
  --exclude='dist' \
  --exclude='__pycache__' \
  --exclude='*.pyc' \
  --exclude='./data' \
  --exclude='./logs' \
  --exclude='./.idea' \
  --exclude='./.ruff_cache' \
  --exclude='./.playwright-mcp' \
  --exclude='./.vscode' \
  --exclude='fix-ssh.txt' \
  --exclude='./dev/roadmap' \
  --exclude='./dev/resource' \
  --exclude='./ui/packages/*/.env.*.local' \
  . | ssh prod "tar xzf - -C $PROD_DIR"
echo "   同步完成"

echo "== 2/3 buildx build（--network host 防 DNS 失败，--ulimit 防 EMFILE） =="
ssh prod "cd $PROD_DIR && \
  docker buildx build --load --network host --ulimit nofile=1048576:1048576 \
    -t $IMG -f Dockerfile ."

echo "== 3/3 recreate aihelms =="
SVC="aihelms"
if [[ "${1:-}" == "nginx" ]]; then SVC="aihelms nginx"; fi
ssh prod "cd $PROD_DIR && \
  docker compose -p $PROJ -f $COMPOSE up -d --force-recreate $SVC && \
  docker compose -p $PROJ -f $COMPOSE ps"

echo "== 日志（尾 30 行） =="
ssh prod "cd $PROD_DIR && docker compose -p $PROJ -f $COMPOSE logs --tail=30 aihelms"
