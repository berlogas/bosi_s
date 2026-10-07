import { expect, test, type Page } from '@playwright/test'

/**
 * Приёмка Фазы 1: вход → создать сессию → заархивировать в два шага.
 *
 * API мокается на уровне сети — спека не требует поднятого бэкенда.
 */

const HEALTH = {
  status: 'ok',
  llm_model: 'test-model',
  embedding_model: 'test-embed',
  ollama: { reachable: false, models: [], reason: 'mock' },
  build: { build: 'e2e', commit: null, built_at: null, ui: null },
}

const SESSION = {
  id: 's-1',
  title: 'Сессия для архива',
  status: 'active',
  created_at: '2026-10-01T00:00:00+00:00',
  expires_at: '2026-12-30T00:00:00+00:00',
  last_action_at: '2026-10-06T12:00:00+00:00',
  last_action_label: 'Загрузка данных',
}

const detail = {
  id: 's-1',
  title: 'Сессия для архива',
  status: 'active',
  writable: true,
  created_at: SESSION.created_at,
  expires_at: SESSION.expires_at,
  days_left: 84,
  usage: { sources: 0, messages: 0, downloads: 0, export_count: 0, minutes_used: 0 },
  summary: {
    title: '',
    sources: 0,
    documents: 0,
    skipped: 0,
    collections: 0,
    last_sync: null,
  },
  settings: { k: 10, category: 'all', scope: 'best', no_cache: false },
  upstream: [],
  questions: [],
  history: [],
  recent_sources: [],
  recent_documents: [],
}

const USER = { username: 'admin', role: 'admin', display_name: 'Admin' }

type Route = { status?: number; body: unknown | (() => unknown) }

async function mockApi(
  page: Page,
  overrides: Record<string, Route> = {},
): Promise<void> {
  const routes: Record<string, Route> = {
    'GET /api/health': { body: HEALTH },
    // 401 без токена (сессии ещё нет), юзер — с токеном (bootstrap после F5
    // идёт me() → refresh → повтор)
    'GET /api/auth/me': { status: 401, body: { detail: 'Not authenticated' } },
    'POST /api/auth/refresh': {
      body: {
        access_token: 'e2e-access',
        refresh_token: 'e2e-refresh',
        expires_in: 900,
        refresh_expires_in: 86400,
      },
    },
    'GET /api/sessions': { body: [] },
    'GET /api/tasks': { body: { tasks: [], active: 0 } },
    'POST /api/auth/login': {
      body: {
        user: USER,
        tokens: {
          access_token: 'e2e-access',
          refresh_token: 'e2e-refresh',
          expires_in: 900,
          refresh_expires_in: 86400,
        },
      },
    },
    ...overrides,
  }

  // только реальный шина API: путь «/api/…», а не модули «/src/api/…»
  await page.route(
    (url) => url.pathname === '/api' || url.pathname.startsWith('/api/'),
    async (route) => {
      const req = route.request()
      const pathname = new URL(req.url()).pathname
      const key = `${req.method()} ${pathname}`
      let handler = routes[key]
      // «живой» мок: /me отвечает юзером, когда клиент уже нёс токен
      // (bootstrap после F5: me() → 401 → refresh → повтор с Bearer)
      if (key === 'GET /api/auth/me' && req.headers()['authorization']) {
        handler = { body: USER }
      }
      if (!handler) {
        await route.fulfill({
          status: 404,
          contentType: 'application/json',
          body: JSON.stringify({ detail: `Немокнутый e2e-запрос: ${key}` }),
        })
        return
      }
      const body = typeof handler.body === 'function' ? handler.body() : handler.body
      await route.fulfill({
        status: handler.status ?? 200,
        contentType: 'application/json',
        body: JSON.stringify(body),
      })
    },
  )
}

async function login(page: Page): Promise<void> {
  await page.goto('/login')
  await page.getByLabel('Логин').fill('admin')
  await page.getByLabel('Пароль').fill('admin')
  await page.getByRole('button', { name: 'Войти' }).click()
  await expect(page).toHaveURL(/\/$/)
}

test('приёмка: вход → создать сессию → архив в два шага с подтверждением', async ({
  page,
}) => {
  const archiveRequests: string[] = []
  let created = false
  let archived = false
  await mockApi(page, {
    // до создания список пуст (проверяем подсказку «нет активных»),
    // после — появляется карточка для архива
    'GET /api/sessions': {
      body: () =>
        created ? [{ ...SESSION, status: archived ? 'archived' : 'active' }] : [],
    },
    'POST /api/sessions': {
      body: { ...SESSION, id: 's-new', title: 'Новая' },
    },
    'GET /api/sessions/s-new': { body: { ...detail, id: 's-new', title: 'Новая' } },
    'GET /api/sessions/s-1': { body: detail },
    'POST /api/sessions/s-1/archive': {
      body: () => {
        archived = true
        return { ...SESSION, status: 'archived' }
      },
    },
  })
  // фиксируем запросы архива (после переопределения роутов — через событие)
  await page.on('request', (req) => {
    if (req.url().includes('/api/sessions/s-1/archive')) {
      archiveRequests.push(`${req.method()} ${req.url()}`)
    }
  })

  // --- вход ---
  await login(page)
  await expect(page.getByRole('heading', { name: /boasi_s/ })).toBeVisible()

  // --- пустой дашборд: подсказка «Активных сессий нет» ---
  await expect(page.getByText('Активных сессий нет — создайте первую.')).toBeVisible()

  // --- создание сессии ---
  await page.getByLabel('Название').fill('Новая')
  await page.getByRole('button', { name: 'Создать' }).click()
  created = true
  // index-роут сессии ведёт на вкладку по умолчанию — чат (Фаза 2)
  await expect(page).toHaveURL(/\/s\/s-new\/chat$/)
  await expect(page.getByRole('heading', { name: 'Новая' })).toBeVisible()

  // --- возврат на дашборд и архив в два шага ---
  await page.goto('/')
  await expect(page.getByTestId('session-card')).toBeVisible()
  await page.getByRole('button', { name: 'Архив', exact: true }).click()

  // шаг 1: модалка спрашивает, запроса пока нет
  const modal = page.getByRole('dialog')
  await expect(modal).toBeVisible()
  await expect(modal.getByText(/уйдёт в архив|Станет только для чтения/)).toBeVisible()
  expect(archiveRequests).toHaveLength(0)

  // шаг 2: подтверждаем — уходит запрос
  await modal.getByRole('button', { name: 'Да, в архив' }).click()
  await expect
    .poll(() => archiveRequests.length, { timeout: 10_000 })
    .toBeGreaterThan(0)
  await expect(modal).toBeHidden()

  // карточка перерисовывается в режим «только чтение»
  await expect(page.getByText('Архив (1) — только чтение')).toBeVisible()
})

test('архив можно отменить в модалке — запрос не уходит', async ({ page }) => {
  const archiveRequests: string[] = []
  await mockApi(page, {
    'GET /api/sessions': { body: [SESSION] },
    'GET /api/sessions/s-1': { body: detail },
  })
  await page.on('request', (req) => {
    if (req.url().includes('/archive')) archiveRequests.push(req.url())
  })

  await login(page)
  await page.getByTestId('session-card').waitFor()
  await page.getByRole('button', { name: 'Архив', exact: true }).click()
  const modal = page.getByRole('dialog')
  await modal.getByRole('button', { name: 'Отмена' }).click()
  await expect(modal).toBeHidden()
  expect(archiveRequests).toHaveLength(0)
})
