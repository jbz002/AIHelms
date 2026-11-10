import { test, expect } from '@playwright/test';

test.describe('admin 登录页', () => {
  test('页面加载：欢迎语与 AI Hub 登录入口', async ({ page }) => {
    await page.goto('/admin/login');
    await expect(page.getByRole('heading', { name: '欢迎回来' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'AI Hub 登录' })).toBeVisible();
  });

  test('点击登录跳转 AI Hub 授权页', async ({ page }) => {
    await page.goto('/admin/login');
    const [popupOrNav] = await Promise.all([
      page.waitForEvent('popup', { timeout: 10_000 }).catch(() => null),
      page.getByRole('button', { name: 'AI Hub 登录' }).click(),
    ]);
    const target = popupOrNav ?? page;
    // redirectToAiHub 跳 AI Hub（VITE_AI_HUB_URL）；redirect_uri 参数里仍带本地地址，按 origin 判断
    await expect
      .poll(async () => new URL(target.url()).hostname, { timeout: 15_000 })
      .not.toBe('localhost');
    await expect(page.getByRole('heading', { name: /数智效能中台|登录/ }).first()).toBeVisible({
      timeout: 10_000,
    });
  });
});
