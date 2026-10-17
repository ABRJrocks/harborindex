import { defineConfig } from '@playwright/test';
export default defineConfig({
  testDir: '.', testMatch: '*.spec.js', workers: 1, reporter: 'list',
  use: { baseURL: 'http://127.0.0.1:4188', viewport: { width: 1440, height: 1000 } },
  webServer: { command: 'python -m http.server 4188 --bind 127.0.0.1 --directory ../../reports', url: 'http://127.0.0.1:4188', reuseExistingServer: false },
});
