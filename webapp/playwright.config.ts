import { defineConfig, devices } from '@playwright/test'

/**
 * E2E: настоящий браузер + Vite dev-сервер.
 *
 * API мокается в тестах через page.route — сценарии приёмки (и CI) не
 * требуют поднятого бэкенда и базы. Чтобы гонять против живого API,
 * уберите моки в спеке или поднимите backend на :8000 (Vite проксирует).
 */
export default defineConfig({
  testDir: './e2e',
  fullyParallel: true,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? 'github' : 'list',
  use: {
    baseURL: 'http://localhost:5173',
    trace: 'retain-on-failure',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  webServer: {
    command: 'npm run dev -- --port 5173 --strictPort',
    url: 'http://localhost:5173',
    reuseExistingServer: !process.env.CI,
    timeout: 60_000,
  },
})
