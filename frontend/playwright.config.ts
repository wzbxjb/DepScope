import { defineConfig } from '@playwright/test';
export default defineConfig({
  testDir: './e2e', timeout: 60000, expect: { timeout: 10000 }, workers: 1,
  use: { baseURL: 'http://127.0.0.1:5173', viewport: { width: 1440, height: 1024 }, screenshot: 'only-on-failure', launchOptions: { executablePath: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome' } },
  reporter: [['list'], ['json', { outputFile: '../artifacts/verification/core-browser-tests.json' }]],
});
