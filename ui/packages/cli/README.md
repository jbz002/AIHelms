# @aihelms/cli

AIHelms Skill 分发通道 CLI —— 通过命令行搜索、安装、发布 Skill，自动落地到本地 Agent 目录。

## 安装

```bash
# 在 monorepo 内（ui/ 下）
npm install
npm run build --workspace=@aihelms/cli

# 或全局链接后使用
npm link --workspace=@aihelms/cli
```

## 配置

AIHelms 为私有化部署，无固定公共 registry。首次使用需指定 registry 与 CLI 令牌：

```bash
aihelms login --registry http://localhost:8000 --token sk_cli_xxxxxxxx
```

令牌在 admin 后台「CLI 令牌」页面创建（Scoped Token，带 `skill:search` / `skill:read` / `skill:install` / `skill:publish` 等 scope）。

也可用环境变量：

```bash
export AIHELMS_REGISTRY=http://localhost:8000
export AIHELMS_TOKEN=sk_cli_xxxxxxxx
```

## 命令

| 命令 | 说明 |
|------|------|
| `login` / `logout` | 保存/移除 registry 与令牌 |
| `whoami` | 校验当前令牌与 scope |
| `search [query]` | 搜索已发布 Skill（`--category` / `--label` / `--sort` / `--limit`） |
| `install <skill>` | 安装 Skill（接受 UUID 或 name；`--scope` / `--agent` / `--dir` / `--version` / `--force`） |
| `list` | 列出本地已安装 Skill |
| `remove <skill>` | 移除本地 Skill（`--agent` / `--all`） |
| `doctor` | 扫描项目内 Skill，重建 inventory，检测版本冲突 |
| `publish <skillId> <path>` | 为指定 Skill 发布新版本（提交审核；`--version` 必填，`--label` / `--change-log` 可选） |
| `version` / `help` | 版本 / 帮助 |

所有命令均支持 `--json` 机器可读输出。

## 安装目录优先级

未显式指定时，按 Agent 检测结果落地；检测不到则按 4 级优先级回退（兼容 OpenSkills / Claude Code）：

1. `./.agents/skills/`
2. `~/.agents/skills/`
3. `./.claude/skills/`
4. `~/.claude/skills/`

支持的 Agent profile：claude-code、codex、cursor、github-copilot、gemini-cli、windsurf、openhands。

每次安装写入 `<skill_dir>/.aihelms/metadata.json`，记录 registry / skillId / name / version / agent / installedAt。本地状态存于 `~/.aihelms/`（config.json、credentials.json、inventory.json）。
