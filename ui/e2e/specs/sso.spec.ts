import { test, expect } from '@playwright/test';

/**
 * AI Hub SSO 登录全链路：/admin/login 点「AI Hub 登录」→ AI Hub 授权页
 * （111.229.103.94:30080，placeholder「请输入用户名/请输入密码」）→
 * 回调 /admin/auth/callback → 进 admin 首页。
 * 需要 e2e/.env 配 E2E_USERNAME / E2E_PASSWORD（AI Hub 账号）。
 */
const hasAccount = Boolean(process.env.E2E_USERNAME && process.env.E2E_PASSWORD);

test.skip(!hasAccount, '需要 AI Hub 测试账号（e2e/.env 配 E2E_USERNAME/E2E_PASSWORD）');

test.describe('AI Hub SSO 登录', () => {
  test('登录后进入 admin 首页', async ({ page }) => {
    await page.goto('/admin/login');
    await page.getByRole('button', { name: 'AI Hub 登录' }).click();

    // 跳到 AI Hub 授权页（redirect_uri 参数含 localhost，按 hostname 判断；
    // 授权页外部资源慢，用 poll 而非 waitForURL，不等 load 事件）
    await expect
      .poll(async () => new URL(page.url()).hostname, { timeout: 20_000 })
      .not.toBe('localhost');
    await page.getByPlaceholder('请输入用户名').fill(process.env.E2E_USERNAME!);
    await page.getByPlaceholder('请输入密码').fill(process.env.E2E_PASSWORD!);
    await page.getByRole('button', { name: '登 录', exact: true }).click();

    // 可能出现 OAuth 授权确认页：有「授权/确认」按钮就点
    const authorize = page.getByRole('button', { name: /授\s*权|确\s*认|同\s*意/ });
    await authorize.waitFor({ state: 'visible', timeout: 5_000 }).then(
      () => authorize.click(),
      () => {}, // 无确认页直接回调
    );

    // 回调回 admin 本地并进首页
    await expect
      .poll(async () => new URL(page.url()).hostname, { timeout: 60_000 })
      .toBe('localhost');
    await expect(page).not.toHaveURL(/\/admin\/(login|auth\/callback)/, { timeout: 30_000 });
  });
});
