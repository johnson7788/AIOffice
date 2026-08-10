import { defineConfig, devices } from '@playwright/test'

// Runs against the already-deployed stack (docker compose up). nginx serves the
// docs SPA at / and reverse-proxies the backend API; override with E2E_BASE_URL.
// ponytail: no webServer block — the stack is started separately (compose).
const baseURL = process.env.E2E_BASE_URL || 'http://localhost'

export default defineConfig({
  testDir: './tests',
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  // cold boots + big SPA bundles need longer than the 30s default; assertions
  // carry their own timeouts (5s expect default), this just un-cap the test
  timeout: 300_000,
  reporter: [['list'], ['html', { open: 'never' }]],
  use: {
    baseURL,
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
})
