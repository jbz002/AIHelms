# E2E 测试（Playwright）— admin

默认打本地 admin dev server（`webServer` 自动拉起 4001，已起则复用），不起 docker 栈。

## 运行（在 ui/ 目录）

```bash
npm i            # 首次（含 @playwright/test）
npm run e2e      # 无头跑全部
npm run e2e:headed
npm run e2e:report
```

浏览器：`npx playwright install chromium`（缓存 `~/AppData/Local/ms-playwright` 已有则跳过）。

## 覆盖范围

- `login-page.spec.ts`：登录页元素、点按钮跳 AI Hub
- `sso.spec.ts`：SSO 全链路（AI Hub 授权页「请输入用户名/密码」→ 授权 → 回调 `/admin/auth/callback` → admin 首页）。`e2e/.env` 配好账号即启用；**依赖后端 API（8100）和 docker 中间件在跑**，否则回调换 token 失败弹回登录页

## 打已部署实例

```bash
# ui/e2e/.env
E2E_BASE_URL=http://<server>:<WEB_PORT>
E2E_NO_WEBSERVER=1
```

## 约定

- 凭证只进 `e2e/.env`；`playwright-report/`、`test-results/`、`.env` 不入库。
- 后端未起时登录页相关 spec 仍可跑（纯前端路由）；涉 API 的断言需 `./dev/start-api`。
