import { defineConfig } from '@playwright/test';
import { loadE2EEnv } from './utils/env';

loadE2EEnv();

// 默认打本地 admin dev server（webServer 自动拉起）；.env 可指向已部署实例
const DEFAULTS = {
  E2E_BASE_URL: 'http://localhost:4001',
  E2E_USERNAME: '',
  E2E_PASSWORD: '',
};

for (const [k, v] of Object.entries(DEFAULTS)) {
  if (process.env[k] === undefined) process.env[k] = v;
}

export default defineConfig({
  testDir: 'specs',
  outputDir: 'test-results',
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [
    ['list'],
    ['html', { outputFolder: 'playwright-report', open: 'never' }],
  ],
  use: {
    baseURL: process.env.E2E_BASE_URL,
    headless: true,
    locale: 'zh-CN',
    actionTimeout: 15_000,
    navigationTimeout: 30_000,
    screenshot: 'only-on-failure',
    trace: 'retain-on-failure',
  },
  expect: {
    timeout: 10_000,
  },
  // 本地跑时自动起 admin dev server（已起则复用）
  webServer: process.env.E2E_NO_WEBSERVER
    ? undefined
    : {
        command: 'npm run dev --workspace @aihelms/admin',
        url: 'http://localhost:4001',
        reuseExistingServer: true,
        timeout: 120_000,
      },
  projects: [
    {
      name: 'chromium',
      use: { browserName: 'chromium' },
    },
  ],
});
