import { defineConfig } from '@playwright/test';
export default defineConfig({
  testDir: './e2e', timeout: 60000, expect: { timeout: 10000 }, workers: 1,
  use: { baseURL: process.env.DEPSCOPE_WEB_URL ?? 'http://127.0.0.1:5173', viewport: { width: 1440, height: 1024 }, screenshot: 'only-on-failure', launchOptions: { executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH ?? (process.platform === 'darwin' ? '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome' : undefined) } },
  reporter: [['list'], ['json', { outputFile: '../artifacts/verification/core-browser-tests.json' }]],
});
