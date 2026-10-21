import { defineConfig, devices } from '@playwright/test'

/**
 * E2E: настоящий браузер + Vite dev-сервер.
 *
 * API мокается в тестах через page.route — сценарии приёмки (и CI) не
 * требуют поднятого бэкенда и базы. Чтобы гонять против живого API,
 * уберите моки в спеке или поднимите backend на :8000 (Vite проксирует).
 *
 * `multiuser.spec.ts` — исключение: он ходит в настоящий API и требует
 * поднятого backend и пользователей, заведённых скриптом (mu_ivan, mu_petr,
 * mu_admin). В CI их нет, поэтому файл исключается: иначе прогон падал на
 * логине и краснел по причине, которой нет в коде. Локально (без CI) файл
 * гоняется как обычно, когда стенд поднят.
 */
export default defineConfig({
  testDir: './e2e',
  testIgnore: process.env.CI ? ['**/multiuser.spec.ts'] : [],
  fullyParallel: true,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? 'github' : 'list',
  use: {
    baseURL: 'http://localhost:5173',
    trace: 'retain-on-failure',
    // Даты в UI форматируются в локальной зоне браузера: без явной зоны
    // e2e-ожидания зависели от машины (CI — UTC, разработчик — Europe/Moscow).
    timezoneId: 'Europe/Moscow',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  webServer: {
    command: 'npm run dev -- --port 5173 --strictPort',
    url: 'http://localhost:5173',
    reuseExistingServer: !process.env.CI,
    timeout: 60_000,
  },
})
