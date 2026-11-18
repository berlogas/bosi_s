/**
 * E2E: новые панели вкладки «Проекты» в настоящем браузере.
 *
 * Юнит-тесты живут в jsdom и не показывают, как панель выглядит на самом
 * деле. Здесь API подменён через `page.route`, а панели открываются и
 * проверяются глазами: скриншоты складываются в `e2e/__screenshots__/`.
 */

import { expect, test, type Page } from '@playwright/test'

const HEALTH = {
  status: 'ok',
  llm_model: 'test-model',
  embedding_model: 'test-embed',
  ollama: { reachable: false, models: [], reason: 'mock' },
}

const SESSION = {
  id: 's-1',
  user_id: 'u-1',
  owner_username: 'ivanov',
  owner_full_name: null,
  title: 'Сессия',
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
    documents: 1,
    documents_limit: 50,
    storage_bytes: 0,
    storage_limit_bytes: 524288000,
    projects: 1,
    projects_limit: 10,
    messages: 0,
    links: 0,
    read_only: false,
  },
  settings: { k: 10, category: 'all', scope: 'best', no_cache: false },
  upstream: [],
  questions: [],
  history: [],
  recent_sources: [],
  recent_documents: [],
}

const USER = {
  id: 'u-1',
  username: 'ivanov',
  full_name: 'Иванов',
  role: 'admin',
  is_active: true,
}

const PROJECT = {
  id: 'p-1',
  session_id: 's-1',
  title: 'Статья о приливах',
  target_journal: 'ICES',
  status: 'planning',
  sections: [],
  order: 0,
  created_at: '2026-10-01T00:00:00+00:00',
  updated_at: '2026-10-01T00:00:00+00:00',
}

const VERSION = {
  id: 'v-1',
  section_plan_id: 'plan-1',
  project_id: 'p-1',
  session_id: 's-1',
  content_md: '## Введение\n\nПриливные циклы формируют береговые процессы [1].',
  language: 'ru',
  source_language: null,
  word_count: 7,
  citation_map: [
    { index: 1, marker: '[1]', source_scope: 'session', dockey: 'abc123', docname: 'Smith 2019' },
  ],
  generation_params: {},
  seconds: null,
  cost_usd: null,
  token_counts: {},
  quality_report: { citations_ok: true, warnings: [] },
  status: 'draft',
  parent_version_id: null,
  created_by: 'u-1',
  created_at: '2026-10-01T00:00:00+00:00',
  updated_at: '2026-10-01T00:00:00+00:00',
}

const VERSION_2 = {
  ...VERSION,
  id: 'v-2',
  content_md:
    '## Введение\n\nПриливные циклы формируют береговые процессы [1].\n\nОбновлённый абзац про биомассу [2].',
  word_count: 11,
  created_at: '2026-10-02T00:00:00+00:00',
}

const PLAN = {
  id: 'plan-1',
  project_id: 'p-1',
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
  status: 'review',
  current_version_id: 'v-2',
  current_version: VERSION_2,
  created_at: '2026-10-01T00:00:00+00:00',
  updated_at: '2026-10-02T00:00:00+00:00',
}

const MANUSCRIPT = {
  project_id: 'p-1',
  language: 'ru',
  full_text:
    '## Введение\n\nПриливные циклы формируют береговые процессы [1].\n\nОбновлённый абзац про биомассу [2].',
  stats: { sections_count: 1, total_words: 11, sources_count: 2, language: 'ru' },
  sections: [{ id: 'plan-1', name: 'Introduction', word_count: 11 }],
  bibliography: [
    { index: 1, title: 'Smith 2019', dockey: 'abc123', citation: 'Smith, 2019' },
    { index: 2, title: 'Ivanov 2020', dockey: 'def456', citation: 'Ivanov, 2020' },
  ],
  warnings: [],
}

const GLOSSARY = [
  {
    id: 'g-1',
    project_id: 'p-1',
    term: 'биомасса',
    translations: { en: 'biomass', de: 'Biomasse' },
    definition: 'Масса живого вещества в водоёме',
    created_at: '2026-10-01T00:00:00+00:00',
  },
]

const DIFF = {
  from_version_id: 'v-1',
  to_version_id: 'v-2',
  added_claims: [
    { index: 1, text: 'Обновлённый абзац про биомассу', citations: [2] },
  ],
  removed_claims: [],
  modified_claims: [],
  citation_changes: { added: [2], removed: [] },
  terminology_changes: { биомасса: 'biomass' },
  word_count_delta: 4,
  summary: 'Добавлено 1 утверждение',
}

type Route = { status?: number; body: unknown }

async function mockApi(page: Page, overrides: Record<string, Route> = {}) {
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
    'GET /api/chat/quick-history': { body: [] },
    'GET /api/documents': { body: [] },
    'GET /api/documents/stats': { body: { total: 0, storage_bytes: 0, by_category: {} } },
    'GET /api/sessions/s-1/documents': { body: [] },
    'GET /api/sessions/s-1/projects': { body: [PROJECT] },
    'GET /api/sessions/s-1/projects/p-1/section-plans': { body: [PLAN] },
    'GET /api/sessions/s-1/projects/p-1/section-versions': { body: [] },
    'GET /api/sessions/s-1/projects/p-1/section-plans/plan-1/history': {
      body: {
        section_plan_id: 'plan-1',
        section_name: 'Introduction',
        roots: [{ version: VERSION_2, children: [] }],
        all_versions: [VERSION, VERSION_2],
      },
    },
    'GET /api/sessions/s-1/projects/p-1/documents': { body: [] },
    'GET /api/sessions/s-1/projects/p-1/progress': {
      body: {
        project_id: 'p-1',
        status: 'planning',
        sections: 5,
        written: 1,
        words: 11,
        percent: 20,
      },
    },
    'GET /api/sessions/s-1/projects/p-1/glossary': { body: GLOSSARY },
    'GET /api/sessions/s-1/projects/p-1/manuscript': { body: MANUSCRIPT },
    'GET /api/sessions/s-1/projects/p-1/terminology-check': {
      body: {
        project_id: 'p-1',
        glossary_terms: { биомасса: { en: 'biomass' } },
        section_terminology: [
          { section: 'Introduction', term: 'биомасса', expected: 'biomass' },
        ],
        consistent: false,
      },
    },
    'GET /api/sessions/s-1/projects/p-1/section-versions/diff': { body: DIFF },
    'POST /api/sessions/s-1/projects/p-1/section-plans/plan-1/translate': {
      body: { ...VERSION_2, id: 'v-3', language: 'en', source_language: 'ru' },
    },
    'POST /api/sessions/s-1/projects/p-1/pre-generation-check': {
      body: {
        ready: false,
        checks: {
          section_exists: true,
          has_question: true,
          sources_found: 1,
          sources_sufficient: false,
          has_style_guide: false,
          has_glossary: true,
          language_supported: true,
        },
        warnings: ['Мало источников: найдено 1, нужно 3'],
        sources_preview: [{ index: 1, title: 'Smith 2019', score: 0.8 }],
      },
    },
    'POST /api/sessions/s-1/projects/p-1/style-compliance': {
      body: {
        compliant: false,
        violations: [
          {
            rule: 'длина абзаца',
            location: 'абзац 2',
            suggestion: 'Разбейте абзац на два',
          },
        ],
        checks: {},
      },
    },
    ...overrides,
  }

  await page.route(
    (url) => url.pathname === '/api' || url.pathname.startsWith('/api/'),
    async (route) => {
      const req = route.request()
      const pathname = new URL(req.url()).pathname
      const key = `${req.method()} ${pathname}`
      let handler = routes[key]
      if (key === 'GET /api/auth/me' && req.headers()['authorization']) {
        handler = { body: USER }
      }
      if (!handler) {
        await route.fulfill({
          status: 404,
          contentType: 'application/json',
          body: JSON.stringify({ detail: `Неизвестный e2e-запрос: ${key}` }),
        })
        return
      }
      await route.fulfill({
        status: handler.status ?? 200,
        contentType: 'application/json',
        body: JSON.stringify(handler.body),
      })
    },
  )
}

/**
 * Войти и открыть вкладку «Проекты» с выбранным проектом.
 *
 * Первая загрузка в dev-режиме долгая: Vite собирает ленивые чанки
 * (редактор CodeMirror весит больше всех), поэтому ждём с запасом.
 */
async function openProjects(page: Page): Promise<void> {
  await page.goto('/login')
  await page.getByLabel('Логин').fill('ivanov')
  await page.getByLabel('Пароль').fill('e2e-pass-123')
  await page.getByRole('button', { name: 'Войти' }).click()
  await expect(page).toHaveURL(/\/$/, { timeout: 30_000 })

  await page.goto('/s/s-1/projects')
  await expect(page.getByText('Статья о приливах').first()).toBeVisible({
    timeout: 30_000,
  })
}

test.describe('новые панели вкладки «Проекты»', () => {
  test('сборка статьи показывает текст, объём и литературу', async ({ page }) => {
    await mockApi(page)
    await openProjects(page)

    await page.getByRole('button', { name: 'Сборка статьи' }).click()
    await page.getByRole('button', { name: 'Собрать статью' }).click()

    await expect(page.getByText('разделов: 1')).toBeVisible()
    await expect(page.getByText('слов: 11')).toBeVisible()
    await expect(page.getByText('Список литературы')).toBeVisible()
    await expect(page.getByText(/Smith 2019/)).toBeVisible()

    await page.screenshot({ path: 'e2e/__screenshots__/projects-manuscript.png', fullPage: true })
  })

  test('глоссарий показывает термины и результат проверки', async ({ page }) => {
    await mockApi(page)
    await openProjects(page)

    await page.getByRole('button', { name: 'Глоссарий терминов' }).click()
    await expect(page.getByText('биомасса').first()).toBeVisible()
    await expect(page.getByText('en: biomass')).toBeVisible()

    await page.getByRole('button', { name: 'Проверить терминологию в разделах' }).click()
    await expect(page.getByText('Термины расходятся')).toBeVisible()

    await page.screenshot({ path: 'e2e/__screenshots__/projects-glossary.png', fullPage: true })
  })

  test('история версий: текст версии и перевод', async ({ page }) => {
    await mockApi(page)
    await openProjects(page)

    // Кнопка «История версий» есть и у раздела, и у аккордеона сессии —
    // берём ту, что внутри карточки раздела.
    const section = page.getByRole('region', { name: /Introduction/ })
    await section.getByRole('button', { name: 'История версий' }).click()
    await expect(page.getByText('Сравнение версий')).toBeVisible()

    await page.getByLabel('Язык перевода раздела').click()
    await page.getByRole('option', { name: 'English (en)' }).click()
    await page.getByRole('button', { name: 'Перевести раздел' }).click()

    // Перевод ушёл без ошибки — в панели нет красного сообщения.
    await expect(page.getByRole('alert')).toHaveCount(0)

    await page.screenshot({ path: 'e2e/__screenshots__/projects-history.png', fullPage: true })
  })

  test('проверка готовности показывает замечания', async ({ page }) => {
    await mockApi(page)
    await openProjects(page)

    await page.getByLabel('Вопрос или тема').fill('О приливах')
    await page.getByRole('combobox', { name: 'Раздел' }).click()
    await page.getByRole('option', { name: 'Introduction' }).click()
    await page.getByRole('button', { name: 'Проверить готовность' }).click()

    await expect(page.getByText('Проверьте перед генерацией')).toBeVisible()
    await expect(page.getByText('Мало источников: найдено 1, нужно 3')).toBeVisible()

    await page.screenshot({ path: 'e2e/__screenshots__/projects-precheck.png', fullPage: true })
  })
})
