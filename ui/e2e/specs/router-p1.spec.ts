import { test, expect, type Page } from '@playwright/test';

const TOKEN = process.env.E2E_TOKEN ?? '';
const ADMIN_URL = process.env.E2E_ADMIN_URL ?? 'http://localhost:4001';
const WEB_URL = process.env.E2E_WEB_URL ?? 'http://localhost:4002';
// 检测用模型：默认 dev 的 Step-5-Preview；对 prod 复验时用 E2E_MODEL/E2E_FAIL_MODEL 覆盖
const CHECK_MODEL = process.env.E2E_MODEL ?? 'Step-5-Preview';
const FAIL_MODEL = process.env.E2E_FAIL_MODEL ?? 'LongCat-2.5-Preview';

async function loginAsAdmin(page: Page): Promise<void> {
  await page.addInitScript((token: string) => {
    localStorage.setItem('aihelms_token', token);
  }, TOKEN);
}

test.beforeEach(async () => {
  if (!TOKEN) throw new Error('E2E_TOKEN 未设置');
});

test.describe('网关路由稳定性 P1（管理端）', () => {
  test('路由配置弹窗展示并持久化流式超时', async ({ page }) => {
    await loginAsAdmin(page);
    await page.goto(`${ADMIN_URL}/admin/models`);
    await page.getByText(CHECK_MODEL, { exact: true }).first().click();
    await expect(page.getByRole('button', { name: '路由配置' })).toBeVisible();

    await page.getByRole('button', { name: '路由配置' }).click();
    const streamInput = page
      .getByText('流式超时 (秒)')
      .locator('..')
      .locator('input');
    await expect(streamInput).not.toHaveValue('');
    const original = await streamInput.inputValue();
    const changed = original === '1801' ? '1800' : '1801';

    await streamInput.fill(changed);
    await page.getByRole('button', { name: '保存', exact: true }).click();
    await expect(page.getByRole('button', { name: '保存', exact: true })).toBeEnabled();
    await page.getByRole('button', { name: '取消', exact: true }).click();

    await page.getByRole('button', { name: '路由配置' }).click();
    await expect(streamInput).toHaveValue(changed);

    await streamInput.fill(original);
    await page.getByRole('button', { name: '保存', exact: true }).click();
    await expect(page.getByRole('button', { name: '保存', exact: true })).toBeEnabled();
    await page.getByRole('button', { name: '取消', exact: true }).click();
  });

  test('健康检测展示部署健康状态', async ({ page }) => {
    test.setTimeout(180_000);
    await loginAsAdmin(page);
    await page.goto(`${ADMIN_URL}/admin/models`);
    await page.getByText(CHECK_MODEL, { exact: true }).first().click();

    await page.getByRole('button', { name: '健康检测' }).click();
    await expect(page.getByText('健康', { exact: true }).first()).toBeVisible({
      timeout: 150_000,
    });
  });

  test('全量健康检查串行执行五项检查并全部通过', async ({ page }) => {
    test.setTimeout(300_000);
    await loginAsAdmin(page);
    await page.goto(`${ADMIN_URL}/admin/models`);
    await page.getByText(CHECK_MODEL, { exact: true }).first().click();

    await page.getByRole('button', { name: '测试', exact: true }).first().click();
    await page.getByRole('button', { name: '全量健康检查' }).click();

    // 状态条逐项从“检测中”变为终态，五项全部通过
    for (const label of ['发送测试', '工具调用', 'Thinking', '历史回放', 'Prompt Cache']) {
      await expect(page.getByText(`${label}·通过`)).toBeVisible({ timeout: 180_000 });
    }
    await expect(page.getByText('回放目标：')).toBeVisible();
    await expect(page.getByText('第 2 轮：')).toHaveCount(2);
    await expect(page.getByText('历史回放未通过')).toHaveCount(0);
    await expect(page.getByText('缓存未命中')).toHaveCount(0);
  });

  test('全量健康检查在基础连通失败时跳过后续探针', async ({ page }) => {
    test.setTimeout(120_000);
    await loginAsAdmin(page);
    await page.goto(`${ADMIN_URL}/admin/models`);
    // FAIL_MODEL 的 LiteLLM 组为禁用态，发送测试必然失败
    await page.getByText(FAIL_MODEL, { exact: true }).first().click();

    await page.getByRole('button', { name: '测试', exact: true }).first().click();
    await page.getByRole('button', { name: '全量健康检查' }).click();

    await expect(page.getByText('发送测试·未通过')).toBeVisible({ timeout: 90_000 });
    await expect(page.getByText('工具调用·已跳过')).toBeVisible();
    await expect(page.getByText('Prompt Cache·已跳过')).toBeVisible();
    await expect(page.getByText('其余检测已跳过')).toBeVisible();
  });
});

test.describe('网关路由稳定性 P1（用户端）', () => {
  test('模型广场接入弹窗展示 Claude Code 档位配置', async ({ page }) => {
    await loginAsAdmin(page);
    await page.goto(`${WEB_URL}/models`);
    const accessButtons = page.getByRole('button', { name: '查看接入信息' });
    await expect(accessButtons.first()).toBeVisible({ timeout: 30_000 });
    await accessButtons.first().click({ force: true });
    await expect(page.getByText('ANTHROPIC_DEFAULT_SONNET_MODEL')).toBeVisible();
    await expect(page.getByText('ANTHROPIC_BASE_URL')).toBeVisible();
  });
});
