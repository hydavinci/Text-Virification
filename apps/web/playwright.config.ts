import { defineConfig, devices } from '@playwright/test'

export default defineConfig({
  testDir: './tests/layout',
  use: {
    baseURL: 'http://127.0.0.1:4173',
    ...devices['Desktop Chrome']
  },
  webServer: {
    command: 'npm run dev -- --host 127.0.0.1 --port 4173 --strictPort',
    url: 'http://127.0.0.1:4173',
    reuseExistingServer: false
  }
})
