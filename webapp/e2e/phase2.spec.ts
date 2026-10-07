import { expect, test, type Page } from '@playwright/test'

/**
 * Приёмка Фазы 2: чат сессии.
 *
 * Сценарии плана: долгий вопрос → панель этапов → отмена;
 * ответ с предупреждением grounding; References отображаются;
 * восстановление поллинга задачи после F5.
 *
 * Сеть замокана целиком — бэкенд не нужен.
 */

const HEALTH = {
  status: 'ok',
  llm_model: 'test-model',
  embedding_model: 'test-embed',
  ollama: { reachable: false, models: [], reason: 'mock' },
  build: { build: 'e2e', commit: null, built_at: null, ui: null },
}

const USER = { username: 'admin', role: 'admin', display_name: 'Admin' }

const SESSION = {
  id: 's-1',
  title: 'Чат-сессия',
  status: 'active',
  created_at: '2026-10-01T00:00:00+00:00',
  expires_at: '2026-12-30T00:00:00+00:00',
}

const DETAIL = {
  ...SESSION,
  writable: true,
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

const SOURCE = {
  index: 1,
  marker: '📚',
  source_scope: 'global',
  dockey: 'k1',
  title: 'Данные GF/F',
  category: 'global_knowledge',
  score: 0.87,
}

type Route = {
  status?: number
  body: unknown | (() => unknown) | ((url: URL) => unknown)
}

async function mockApi(
  page: Page,
  overrides: Record<string, Route> = {},
): Promise<{ requestLog: string[] }> {
  const requestLog: string[] = []
  const routes: Record<string, Route> = {
    'GET /api/health': { body: HEALTH },
    'GET /api/auth/me': { status: 401, body: { detail: 'Not authenticated' } },
    'POST /api/auth/refresh': {
      body: {
        access_token: 'e2e-access',
        refresh_token: 'e2e-refresh',
        expires_in: 900,
        refresh_expires_in: 86400,
      },
    },
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
    'GET /api/sessions': { body: [SESSION] },
    'GET /api/sessions/s-1': { body: DETAIL },
    'GET /api/tasks': { body: { tasks: [], active: 0 } },
    'GET /api/chat/messages': { body: { messages: [], total: 0, offset: 0 } },
    ...overrides,
  }

  await page.route(
    (url) => url.pathname === '/api' || url.pathname.startsWith('/api/'),
    async (route) => {
      const req = route.request()
      const url = new URL(req.url())
      const key = `${req.method()} ${url.pathname}`
      let handler = routes[key]
      requestLog.push(`${key}${url.search}`)
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
      const raw =
        typeof handler.body === 'function'
          ? (handler.body as (u: URL) => unknown)(url)
          : handler.body
      await route.fulfill({
        status: handler.status ?? 200,
        contentType: 'application/json',
        body: JSON.stringify(raw ?? null),
      })
    },
  )
  return { requestLog }
}

async function login(page: Page): Promise<void> {
  await page.goto('/login')
  await page.getByLabel('Логин').fill('admin')
  await page.getByLabel('Пароль').fill('admin')
  await page.getByRole('button', { name: 'Войти' }).click()
  await expect(page).toHaveURL(/\/$/)
}

/** открыть чат сессии с уже замоканной сетью */
async function openChat(page: Page): Promise<void> {
  await page.goto('/s/s-1/chat')
  await expect(page.getByLabel('Ваш вопрос')).toBeVisible()
}

test('долгий вопрос: панель этапов с прогрессом → отмена', async ({ page }) => {
  let taskPhase: 'run' | 'cancelled' = 'run'
  const { requestLog } = await mockApi(page, {
    'POST /api/chat/query-async': { body: { task_id: 't-1' } },
    'GET /api/tasks/t-1': {
      body: () => ({
        id: 't-1',
        kind: 'chat',
        title: 'Вопрос: биомасса',
        status: taskPhase === 'run' ? 'running' : 'cancelled',
        progress: 55,
        step: 'LLM формирует ответ',
        error: null,
        cancel_requested: taskPhase !== 'run',
        session_id: 's-1',
        created_at: '2026-10-06T12:00:00+00:00',
        started_at: '2026-10-06T12:00:00+00:00',
        finished_at: null,
        seconds: 42,
        stage_seconds: 7,
        result: null,
      }),
    },
    'POST /api/tasks/t-1/cancel': {
      body: () => {
        taskPhase = 'cancelled'
        return { cancelled: true, task: null }
      },
    },
  })

  await login(page)
  await openChat(page)

  await page.getByLabel('Ваш вопрос').fill('Что такое биомасса?')
  await page.getByRole('button', { name: '➤' }).click()

  // pending-пузырь + панель этапов: процент, шаг, секундомер
  await expect(page.getByText('Вопрос обрабатывается…')).toBeVisible()
  await expect(page.getByText(/55%/)).toBeVisible()
  await expect(page.getByText(/LLM формирует ответ/)).toBeVisible()
  await expect(page.getByText(/всего 42с/)).toBeVisible()

  // task_id пережил запуск — поллинг продолжается
  const stored = await page.evaluate(() =>
    window.sessionStorage.getItem('boasi.chat.task'),
  )
  expect(stored).toContain('t-1')

  // отмена (exact: aria-label пузыря «Отменить вопрос…» тоже содержит слово)
  await page.getByRole('button', { name: 'Отменить', exact: true }).click()
  await expect
    .poll(() => requestLog.filter((line) => line.includes('/cancel')).length)
    .toBeGreaterThan(0)

  // задача cancelled: панель и pending гаснут, остаётся пометка об отмене
  await expect(page.getByText('Задача отменена')).toBeVisible({ timeout: 15_000 })
  await expect(page.getByRole('button', { name: 'Отменить' })).toBeHidden()
})

test('ответ с предупреждением grounding: ⚠️ и expander', async ({ page }) => {
  await mockApi(page, {
    'POST /api/chat/query': {
      body: {
        answer: 'Ответ по данным [1].',
        sources: [SOURCE],
        references: ['[1] Данные GF/F (глобальная база)'],
        mode: 'hybrid',
        query: 'вопрос',
        from_cache: false,
        stats: {
          grounding: { warnings: ['Цитата [2] не найдена в списке источников'] },
          citations: { warnings: ['Факт без опоры в тексте'] },
        },
        base_empty: false,
      },
    },
  })

  await login(page)
  await openChat(page)

  // переключаемся на синхронный режим
  await page.getByRole('switch', { name: /Фоновый режим/ }).click()
  await page.getByLabel('Ваш вопрос').fill('вопрос')
  await page.getByRole('button', { name: '➤' }).click()

  // первое предупреждение видно сразу
  await expect(page.getByText(/⚠️.*Цитата \[2\] не найдена/)).toBeVisible()

  // второе — за expander'ом
  await page.getByText(/Все предупреждения проверки \(2\)/).click()
  await expect(page.getByText(/Факт без опоры в тексте/)).toBeVisible()
})

test('References отображаются и открываются, цитата подсвечивает источник', async ({
  page,
}) => {
  await mockApi(page, {
    'POST /api/chat/query': {
      body: {
        answer: 'Ответ по данным [1].',
        sources: [SOURCE],
        references: ['[1] Данные GF/F (глобальная база)'],
        mode: 'hybrid',
        query: 'вопрос',
        from_cache: false,
        stats: {},
        base_empty: false,
      },
    },
  })

  await login(page)
  await openChat(page)

  await page.getByRole('switch', { name: /Фоновый режим/ }).click()
  await page.getByLabel('Ваш вопрос').fill('вопрос')
  await page.getByRole('button', { name: '➤' }).click()

  // список источников
  await expect(page.getByText('Источники:')).toBeVisible()
  await expect(page.getByText(/Данные GF\/F/).first()).toBeVisible()

  // References: expander открывается и показывает строку
  await page.getByText('Список источников').click()
  await expect(page.getByText(/Данные GF\/F \(глобальная база\)/)).toBeVisible()

  // клик по цитате [1] в ответе подсвечивает источник
  // (активный источник получает px=4 → padding; bg — style-проп Mantine)
  await page.getByRole('link', { name: '[1]' }).click()
  const highlighted = page.locator('[data-src="1"]')
  await expect(highlighted).toHaveCSS('padding-left', '4px')
})

test('восстановление после F5: поллинг задачи продолжается', async ({ page }) => {
  await mockApi(page, {
    'GET /api/tasks/t-1': {
      body: {
        id: 't-1',
        kind: 'chat',
        title: 'Вопрос: биомасса',
        status: 'running',
        progress: 85,
        step: 'Проверка цитат',
        error: null,
        cancel_requested: false,
        session_id: 's-1',
        created_at: '2026-10-06T12:00:00+00:00',
        started_at: '2026-10-06T12:00:00+00:00',
        finished_at: null,
        seconds: 120,
        stage_seconds: 9,
        result: null,
      },
    },
  })

  await login(page)
  await openChat(page)

  // задача уже висела в sessionStorage до захода на страницу
  await page.evaluate(() =>
    window.sessionStorage.setItem(
      'boasi.chat.task',
      JSON.stringify({
        sessionId: 's-1',
        taskId: 't-1',
        question: 'Вопрос до F5',
      }),
    ),
  )
  await page.reload()

  // панель восстановилась и поллит прогресс
  await expect(page.getByText('Вопрос до F5')).toBeVisible()
  await expect(page.getByText(/85%/)).toBeVisible()
  await expect(page.getByText(/Проверка цитат/)).toBeVisible()
  await expect(
    page.getByRole('button', { name: 'Отменить', exact: true }),
  ).toBeVisible()
})
