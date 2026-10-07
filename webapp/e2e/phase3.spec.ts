import { expect, test, type Page } from '@playwright/test'

/**
 * Приёмка Фазы 3: документы и проекты.
 *
 * Сценарии плана: загрузка файла (dropzone) + индексация (панель
 * прогресса), добавление по пути, проект-редактор: создание → раздел →
 * сохранение, привязка документа, экспорт.
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
  title: 'Сессия документов',
  status: 'active',
  created_at: '2026-10-01T00:00:00+00:00',
  expires_at: '2026-12-30T00:00:00+00:00',
}

const DETAIL = {
  ...SESSION,
  writable: true,
  days_left: 84,
  summary: {
    documents: 1,
    documents_limit: 50,
    storage_bytes: 1024,
    storage_limit_bytes: 524288000,
  },
}

const DOC = {
  id: 'd-1',
  dockey: 'abcd1234efgh',
  docname: 'otchet',
  title: 'Отчёт 2025',
  category: 'temp_literature',
  status: 'ready',
  size_bytes: 2048,
  chunk_count: 7,
  tags: ['смок'],
}

const PROJECT = {
  id: 'p-1',
  session_id: 's-1',
  title: 'Статья',
  target_journal: 'ICES',
  status: 'planning',
  sections: [],
  created_at: '2026-10-01T00:00:00+00:00',
  updated_at: '2026-10-01T00:00:00+00:00',
}

type Body = unknown | (() => unknown)
type Route = { status?: number; body: Body }

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
    'GET /api/sessions/s-1/documents': { body: [DOC] },
    'GET /api/sessions/s-1/projects': { body: [PROJECT] },
    'GET /api/sessions/s-1/projects/p-1/sections': {
      body: [
        {
          name: 'Introduction',
          required: true,
          order: 1,
          word_target: 600,
          notes: '',
          content_md: '',
          words: 0,
          written: false,
        },
      ],
    },
    'GET /api/sessions/s-1/projects/p-1/documents': { body: [] },
    'GET /api/sessions/s-1/projects/p-1/progress': {
      body: {
        project_id: 'p-1',
        sections: 5,
        written: 0,
        words: 0,
        percent: 0,
      },
    },
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
      const raw = typeof handler.body === 'function' ? handler.body() : handler.body
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

test('загрузка файла через dropzone → панель прогресса индексации', async ({
  page,
}) => {
  let uploaded = false
  const { requestLog } = await mockApi(page, {
    'GET /api/sessions/s-1/documents': {
      body: () =>
        uploaded ? [DOC, { ...DOC, id: 'd-2', title: 'Новый файл' }] : [DOC],
    },
    'POST /api/sessions/s-1/documents/upload': {
      body: () => {
        uploaded = true
        return {
          added: [{ ...DOC, id: 'd-2', title: 'Новый файл' }],
          duplicates: [],
          failed: [],
          total: 1,
        }
      },
    },
    'GET /api/tasks': {
      body: () => ({
        tasks: uploaded
          ? [
              {
                id: 't-idx',
                kind: 'indexing',
                title: 'Индексация: Новый файл',
                status: 'running',
                progress: 60,
                step: 'чанки',
                error: null,
                cancel_requested: false,
                session_id: 's-1',
                project_id: null,
                created_at: '2026-10-07T09:00:00+00:00',
                started_at: '2026-10-07T09:00:01+00:00',
                finished_at: null,
                seconds: 8,
                stage_seconds: 3,
                result: null,
              },
            ]
          : [],
        active: uploaded ? 1 : 0,
      }),
    },
  })

  await login(page)
  await page.goto('/s/s-1/documents')
  await expect(page.getByText('Временная литература (1)')).toBeVisible()

  // выбор файла (dropzone принимает и клик, и drop — здесь путь через input)
  await page.locator('input[type="file"]').setInputFiles({
    name: 'novyy.txt',
    mimeType: 'text/plain',
    buffer: Buffer.from('текст'),
  })
  await expect(page.getByText(/Выбрано файлов:/)).toBeVisible()

  await page.getByRole('button', { name: 'Загрузить файлы' }).click()

  // success-строка documents_tab
  await expect(page.getByText('Добавлено: 1, ошибок: 0')).toBeVisible({
    timeout: 15_000,
  })
  expect(requestLog.some((line) => line.includes('/documents/upload'))).toBe(true)

  // прогресс индексации: панель задачи с процентами и шагом
  await expect(page.getByText(/60%/)).toBeVisible()
  await expect(page.getByText(/чанки/)).toBeVisible()
})

test('добавление по пути: форма → POST path → документ в списке', async ({ page }) => {
  const { requestLog } = await mockApi(page, {
    'POST /api/sessions/s-1/documents/path': {
      body: { ...DOC, id: 'd-9', title: 'Файл с диска' },
    },
    'GET /api/sessions/s-1/documents': {
      body: () =>
        requestLog.some((line) => line.includes('/documents/path'))
          ? [DOC, { ...DOC, id: 'd-9', title: 'Файл с диска' }]
          : [DOC],
    },
  })

  await login(page)
  await page.goto('/s/s-1/documents')
  await expect(page.getByText('Временная литература (1)')).toBeVisible()

  await page.getByLabel('Путь к файлу на диске').fill('/data/file.pdf')
  await page.getByLabel('Теги через запятую').fill('тест')
  await page.getByRole('button', { name: 'Добавить' }).click()

  await expect(page.getByText(/Файл с диска/).first()).toBeVisible({
    timeout: 15_000,
  })
  const call = requestLog.find((line) => line.includes('/documents/path'))
  expect(call).toBeDefined()
})

test('проект-редактор: создание → раздел → сохранение черновика', async ({ page }) => {
  const { requestLog } = await mockApi(page, {
    'GET /api/sessions/s-1/projects': {
      body: () =>
        requestLog.some((line) => line.endsWith('/projects') && line.includes('POST'))
          ? [{ ...PROJECT, id: 'p-new', title: 'Новая статья' }]
          : [],
    },
    'POST /api/sessions/s-1/projects': {
      body: { ...PROJECT, id: 'p-new', title: 'Новая статья' },
    },
    'GET /api/sessions/s-1/projects/p-new/sections': {
      body: [
        {
          name: 'Introduction',
          required: true,
          order: 1,
          word_target: 600,
          notes: '',
          content_md: '',
          words: 0,
          written: false,
        },
      ],
    },
    'GET /api/sessions/s-1/projects/p-new/documents': { body: [] },
    'GET /api/sessions/s-1/projects/p-new/progress': {
      body: { project_id: 'p-new', sections: 5, written: 0, words: 0, percent: 0 },
    },
    'PUT /api/sessions/s-1/projects/p-new/sections/Introduction': {
      body: {
        name: 'Introduction',
        required: true,
        order: 1,
        word_target: 600,
        notes: '',
        content_md: 'Мой черновик введения',
        words: 3,
        written: true,
      },
    },
  })

  await login(page)
  await page.goto('/s/s-1/projects')
  await expect(page.getByText('Проектов нет — создайте первый.')).toBeVisible()

  // создание
  await page.getByLabel('Название').fill('Новая статья')
  await page.getByLabel('Целевой журнал').fill('ICES')
  await page.getByRole('button', { name: 'Создать' }).click()
  // после создания эффект сам выбирает новый проект (selectedId → list[0])
  await expect(page.getByRole('combobox', { name: 'Проект' })).toBeVisible({
    timeout: 15_000,
  })

  // раздел раскрыт (не написан) — правим и сохраняем
  const area = page.getByLabel('Текст раздела: Introduction')
  await area.fill('Мой черновик введения')
  await page.getByRole('button', { name: 'Сохранить' }).click()

  await expect(page.getByText('Раздел сохранён.')).toBeVisible({ timeout: 15_000 })
  expect(requestLog.some((line) => line.includes('/sections/Introduction'))).toBe(true)
})

test('привязка документа к проекту и отвязка', async ({ page }) => {
  const { requestLog } = await mockApi(page, {
    'POST /api/sessions/s-1/projects/p-1/documents': { status: 204, body: null },
    'GET /api/sessions/s-1/projects/p-1/documents': {
      body: () =>
        requestLog.some((line) => line.endsWith('/documents') && line.includes('POST'))
          ? [{ document: DOC, role: 'data' }]
          : [],
    },
  })

  await login(page)
  await page.goto('/s/s-1/projects/p-1/documents')
  await page.goto('/s/s-1/projects')
  await expect(page.getByText('Привязать документ')).toBeVisible()

  await page.getByRole('combobox', { name: 'Привязать документ' }).click()
  await page.getByRole('option', { name: 'Отчёт 2025', includeHidden: true }).click()
  await page.getByRole('combobox', { name: 'Роль' }).click()
  await page
    .getByRole('option', { name: 'data', exact: true, includeHidden: true })
    .click()
  await page.getByRole('button', { name: 'Привязать' }).click()

  await expect(page.getByText(/Отчёт 2025 — роль: data/)).toBeVisible({
    timeout: 15_000,
  })
  await page.getByRole('button', { name: 'Отвязать' }).click()
  await expect
    .poll(
      () =>
        requestLog.filter(
          (line) => line.includes('/projects/p-1/documents') && line.includes('DELETE'),
        ).length,
    )
    .toBeGreaterThan(0)
})
