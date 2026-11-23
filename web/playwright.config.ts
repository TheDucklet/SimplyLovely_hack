import { defineConfig } from '@playwright/test';

const baseURL = 'http://127.0.0.1:4176';

export default defineConfig({
  testDir: './e2e',
  reporter: [['list'], ['html', { open: 'never' }]],
  use: {
    baseURL,
    browserName: 'chromium',
    locale: 'ru-RU',
    viewport: { width: 1440, height: 960 },
    serviceWorkers: 'block',
    launchOptions: { args: ['--enable-unsafe-swiftshader'] },
    screenshot: 'only-on-failure',
    trace: 'retain-on-failure',
  },
  timeout: 60000,
  webServer: {
    command: 'npm run preview -- --port 4176 --strictPort',
    url: baseURL,
    reuseExistingServer: false,
  },
});
