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

const USER = {
  id: 'u-1',
  username: 'admin',
  full_name: 'Admin',
  role: 'admin',
  is_active: true,
}

const SESSION = {
  id: 's-1',
  // `user_id` обязателен в контракте SessionOut: без него в списке сессий
  // `groupByOwner` получает пустого владельца, и React ругается на key.
  user_id: 'u-1',
  owner_username: 'ivanov',
  owner_full_name: null,
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
    'POST /api/sessions/s-1/documents/upload-async': {
      body: () => {
        uploaded = true
        return { task_id: 't-idx', total: 1 }
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
                status: 'done',
                progress: 100,
                step: 'готово',
                error: null,
                cancel_requested: false,
                session_id: 's-1',
                project_id: null,
                created_at: '2026-10-07T09:00:00+00:00',
                started_at: '2026-10-07T09:00:01+00:00',
                finished_at: '2026-10-07T09:00:08+00:00',
                seconds: 8,
                stage_seconds: null,
                result: {
                  added: [{ ...DOC, id: 'd-2', title: 'Новый файл' }],
                  duplicates: [],
                  failed: [],
                  total: 1,
                },
              },
            ]
          : [],
        active: 0,
      }),
    },
  })

  await login(page)
  await page.goto('/s/s-1/documents')
  await expect(page.getByText('Временная литература (1)')).toBeVisible()

  // выбор файла (dropzone принимает и клик, и drop — здесь путь через input)
  await page.getByTestId('doc-file-input').setInputFiles({
    name: 'novyy.txt',
    mimeType: 'text/plain',
    buffer: Buffer.from('текст'),
  })
  await expect(page.getByText(/Выбрано файлов:/)).toBeVisible()

  await page.getByRole('button', { name: 'Загрузить файлы' }).click()

  // success-строка documents_tab
  await expect(page.getByText('Проиндексировано: 1')).toBeVisible({
    timeout: 15_000,
  })
  expect(requestLog.some((line) => line.includes('/documents/upload'))).toBe(true)

  // итог индексации виден в сводке внутри вкладки «Документы»
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
  await page.getByPlaceholder('Теги через запятую').fill('тест')
  await page.getByRole('button', { name: 'Добавить' }).click()

  await expect(page.getByText(/Файл с диска/).first()).toBeVisible({
    timeout: 15_000,
  })
  const call = requestLog.find((line) => line.includes('/documents/path'))
  expect(call).toBeDefined()
})

test('проект-редактор: создание → раздел → сохранение черновика', async ({ page }) => {
  const { requestLog } = await mockApi(page, {
    // Без мока список стилей пуст, и выпадающий «Стиль журнала» нечего выбирать:
    // unmocked-запрос возвращает 404, компонент показывает пустой Select.
    'GET /api/journal-styles': {
      body: [
        {
          key: 'multidisciplinary_breakthrough',
          title: 'Мультидисциплинарный прорыв',
          summary: 'Nature, Science, Cell, PNAS: широкая аудитория.',
          journals: ['Nature', 'Science'],
          description: 'Читатель: междисциплинарные учёные.',
          description_lines: ['Читатель: междисциплинарные учёные.'],
          highlights: ['TARGET AUDIENCE: Multidisciplinary scientists.'],
          templates: [{ label: 'Обзор', sections: ['Introduction', 'Results'] }],
        },
      ],
    },
    'GET /api/sessions/s-1/projects': {
      body: () =>
        requestLog.some((line) => line.endsWith('/projects') && line.includes('POST'))
          ? [{ ...PROJECT, id: 'p-new', title: 'Новая статья' }]
          : [],
    },
    'POST /api/sessions/s-1/projects': {
      body: { ...PROJECT, id: 'p-new', title: 'Новая статья' },
    },
    'GET /api/sessions/s-1/projects/p-new/section-plans': {
      body: [
        {
          id: 'plan-new',
          project_id: 'p-new',
          name: 'Introduction',
          kind: 'standard',
          order: 1,
          required: true,
          word_target: 600,
          word_min: 300,
          word_max: 2400,
          notes: '',
          language: 'ru',
          depends_on: [],
          status: 'pending',
          current_version_id: null,
          current_version: null,
          created_at: '2026-10-01T00:00:00+00:00',
          updated_at: '2026-10-01T00:00:00+00:00',
        },
      ],
    },
    'GET /api/sessions/s-1/projects/p-new/documents': { body: [] },
    'GET /api/sessions/s-1/projects/p-new/progress': {
      body: { project_id: 'p-new', sections: 5, written: 0, words: 0, percent: 0 },
    },
    'PUT /api/sessions/s-1/projects/p-new/section-plans/plan-new/content': {
      body: {
        id: 'v-new',
        section_plan_id: 'plan-new',
        project_id: 'p-new',
        content_md: 'Мой черновик введения',
        word_count: 3,
        citation_map: [],
        generation_params: {},
        quality_report: {},
        status: 'draft',
        created_at: '2026-10-01T00:01:00+00:00',
        updated_at: '2026-10-01T00:01:00+00:00',
      },
    },
  })

  await login(page)
  await page.goto('/s/s-1/projects')
  await expect(page.getByText('Проектов пока нет')).toBeVisible()

  // создание
  await page.getByLabel('Название').fill('Новая статья')
  // «Целевой журнал» стал выпадающим списком стилей журнала: значение —
  // идентификатор группы журналов, а не свободный текст.
  const journal = page.getByRole('combobox', { name: 'Стиль журнала' })
  await journal.click()
  await page.getByRole('option', { name: /Мультидисциплинарный прорыв/ }).click()
  await page.getByRole('button', { name: 'Создать', exact: true }).click()
  // после создания эффект сам выбирает новый проект (selectedId → list[0])
  await expect(page.getByText('Новая статья').first()).toBeVisible({ timeout: 15_000 })

  // раздел раскрыт (не написан) — правим и сохраняем
  // В браузере редактор — CodeMirror (aria-label только у тестового textarea).
  const area = page.locator('.cm-content').first()
  await area.fill('Мой черновик введения')
  await page.getByRole('button', { name: 'Сохранить' }).click()

  expect(
    requestLog.some((line) => line.includes('/section-plans/plan-new/content')),
  ).toBe(true)
})

test('привязка документа к проекту и отвязка', async ({ page }) => {
  const { requestLog } = await mockApi(page, {
    'POST /api/sessions/s-1/projects/p-1/documents': { status: 204, body: null },
    'DELETE /api/sessions/s-1/projects/p-1/documents/d-1': { status: 204, body: null },
    'GET /api/sessions/s-1/projects/p-1/documents': {
      body: () =>
        requestLog.some(
          (line) => line.includes('/projects/p-1/documents') && line.includes('POST'),
        )
          ? [{ document: DOC, role: 'data' }]
          : [],
    },
  })

  await login(page)
  await page.goto('/s/s-1/projects')
  await page.getByRole('button', { name: 'Документы проекта' }).click()

  await page.getByRole('button', { name: 'Привязать' }).click()

  await expect(page.getByText('Отчёт 2025').first()).toBeVisible({ timeout: 15_000 })
  expect(
    requestLog.some(
      (line) => line.includes('/projects/p-1/documents') && line.includes('POST'),
    ),
  ).toBe(true)

  await page.getByRole('button', { name: /Отвязать Отчёт 2025/ }).click()
  await expect
    .poll(
      () =>
        requestLog.filter(
          (line) => line.includes('/projects/p-1/documents') && line.includes('DELETE'),
        ).length,
    )
    .toBeGreaterThan(0)
})
