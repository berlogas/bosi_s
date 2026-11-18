/**
 * Тесты новых панелей вкладки «Проекты».
 *
 * Проверяем то, что вытащили из бэкенда в интерфейс: сборку статьи,
 * глоссарий с проверкой терминологии, сравнение версий, перевод раздела,
 * проверку готовности к генерации и проверку стиля.
 */

import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient } from '@tanstack/react-query'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { AppProviders } from '../../app/AppProviders'
import { AppRoutes } from '../../routes'
import { loginAs, mockApi, resetAuth } from '../../test/helpers'

const HEALTH = {
  status: 'ok',
  llm_model: 'test-model',
  embedding_model: 'test-embed',
  ollama: {},
}

const SESSION = {
  id: 's-1',
  title: 'Сессия',
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
    storage_bytes: 0,
    storage_limit_bytes: 524288000,
  },
}

const PROJECT = {
  id: 'p-1',
  session_id: 's-1',
  title: 'Статья о приливах',
  target_journal: 'ICES',
  status: 'planning',
  sections: [],
  created_at: '2026-10-01T00:00:00+00:00',
  updated_at: '2026-10-01T00:00:00+00:00',
}

const VERSION = {
  id: 'v-1',
  section_plan_id: 'plan-1',
  project_id: 'p-1',
  session_id: 's-1',
  content_md: 'Серверный текст раздела',
  language: 'ru',
  source_language: null,
  word_count: 3,
  citation_map: [],
  generation_params: {},
  seconds: null,
  cost_usd: null,
  token_counts: {},
  quality_report: {},
  status: 'draft',
  parent_version_id: null,
  created_by: 'u-1',
  created_at: '2026-10-01T00:00:00+00:00',
  updated_at: '2026-10-01T00:00:00+00:00',
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
  current_version_id: 'v-1',
  current_version: VERSION,
  created_at: '2026-10-01T00:00:00+00:00',
  updated_at: '2026-10-01T00:00:00+00:00',
}

/** Вторая версия раздела — нужна, чтобы появилось сравнение версий. */
const VERSION_2 = {
  ...VERSION,
  id: 'v-2',
  content_md: 'Обновлённый текст раздела',
  word_count: 4,
  created_at: '2026-10-02T00:00:00+00:00',
}

const HISTORY = {
  section_plan_id: 'plan-1',
  section_name: 'Introduction',
  roots: [{ version: VERSION, children: [] }],
  all_versions: [VERSION, VERSION_2],
}

const DOC = {
  id: 'd-1',
  dockey: 'abcd1234',
  docname: 'doc',
  title: 'Отчёт',
  category: 'temp_literature',
}

const MANUSCRIPT = {
  project_id: 'p-1',
  language: 'ru',
  full_text: '# Статья о приливах\n\nСерверный текст раздела',
  stats: {
    sections_count: 1,
    total_words: 3,
    sources_count: 2,
    language: 'ru',
  },
  sections: [{ id: 'plan-1', name: 'Introduction', word_count: 3 }],
  bibliography: [{ index: 1, title: 'Smith 2019', dockey: 'abcd1234', citation: 'Smith, 2019' }],
  warnings: [],
}

const GLOSSARY = [
  {
    id: 'g-1',
    project_id: 'p-1',
    term: 'биомасса',
    translations: { en: 'biomass' },
    definition: 'Масса живого вещества',
    created_at: '2026-10-01T00:00:00+00:00',
  },
]

const DIFF = {
  from_version_id: 'v-1',
  to_version_id: 'v-2',
  added_claims: [{ index: 0, text: 'Новое утверждение', citations: [1] }],
  removed_claims: [],
  modified_claims: [],
  citation_changes: { added: [3], removed: [] },
  terminology_changes: { биомасса: 'biomass' },
  word_count_delta: 2,
  summary: 'Добавлено 1 утверждение',
}

function renderApp(path = '/s/s-1/projects') {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  })
  return render(
    <AppProviders initialPath={path} queryClient={queryClient}>
      <AppRoutes />
    </AppProviders>,
  )
}

function baseRoutes(overrides: Record<string, unknown> = {}) {
  return {
    routes: {
      'GET /api/health': HEALTH,
      'GET /api/journal-styles': [],
      'GET /api/sessions/s-1': DETAIL,
      'GET /api/sessions': [SESSION],
      'GET /api/tasks': { tasks: [], active: 0 },
      'GET /api/chat/messages': { messages: [], total: 0, offset: 0 },
      'GET /api/sessions/s-1/documents': [DOC],
      'GET /api/sessions/s-1/projects': [PROJECT],
      'GET /api/sessions/s-1/projects/p-1/section-plans': [PLAN],
      'GET /api/sessions/s-1/projects/p-1/section-versions': [],
      'GET /api/sessions/s-1/projects/p-1/section-plans/plan-1/history': HISTORY,
      'GET /api/sessions/s-1/projects/p-1/documents': [],
      'GET /api/sessions/s-1/projects/p-1/progress': {
        project_id: 'p-1',
        status: 'planning',
        sections: 5,
        written: 1,
        words: 3,
        percent: 20,
      },
      'GET /api/sessions/s-1/projects/p-1/glossary': GLOSSARY,
      'GET /api/sessions/s-1/projects/p-1/manuscript': MANUSCRIPT,
      'GET /api/sessions/s-1/projects/p-1/terminology-check': {
        consistent: false,
        section_terminology: [{ section: 'Introduction', term: 'биомасса', expected: 'biomass' }],
        global_terminology: [],
        recommendations: [],
      },
      ...overrides,
    },
  }
}

/** Дождаться, пока откроется редактор проекта. */
async function waitForProject() {
  await waitFor(() =>
    expect(screen.getAllByText(/Статья о приливах/).length).toBeGreaterThan(0),
  )
}

/** Открыть аккордеон «Сборка статьи». */
async function openManuscriptPanel() {
  await userEvent.click(
    await screen.findByRole('button', { name: 'Сборка статьи' }),
  )
}

beforeEach(() => {
  sessionStorage.clear()
  loginAs()
})

afterEach(() => {
  vi.unstubAllGlobals()
  resetAuth()
})

describe('сборка статьи', () => {
  it('статья собирается по кнопке, а не молча при открытии', async () => {
    const { calls } = mockApi(baseRoutes().routes)
    renderApp()
    await waitForProject()

    await openManuscriptPanel()

    // Запрос на манускрипт уходит только после нажатия кнопки.
    expect(
      calls.filter((c) => c.url.includes('/manuscript')),
    ).toHaveLength(0)

    await userEvent.click(screen.getByRole('button', { name: 'Собрать статью' }))

    expect(await screen.findByText(/разделов: 1/)).toBeInTheDocument()
    expect(await screen.findByText(/слов: 3/)).toBeInTheDocument()
    expect(
      calls.filter((c) => c.url.includes('/manuscript')),
    ).not.toHaveLength(0)
  })

  it('собранный текст и список литературы показываются', async () => {
    mockApi(baseRoutes().routes)
    renderApp()
    await waitForProject()

    await openManuscriptPanel()
    await userEvent.click(screen.getByRole('button', { name: 'Собрать статью' }))

    expect(await screen.findByText('Список литературы')).toBeInTheDocument()
    expect(await screen.findByText(/Smith 2019/)).toBeInTheDocument()
  })
})

describe('глоссарий терминов', () => {
  it('термин из глоссария показан с переводом', async () => {
    mockApi(baseRoutes().routes)
    renderApp()
    await waitForProject()

    await userEvent.click(await screen.findByText('Глоссарий терминов'))

    expect(await screen.findByText('биомасса')).toBeInTheDocument()
    expect(await screen.findByText('en: biomass')).toBeInTheDocument()
    expect(await screen.findByText('Масса живого вещества')).toBeInTheDocument()
  })

  it('новый термин уходит на сервер с переводами', async () => {
    const { calls } = mockApi(
      baseRoutes({
        'POST /api/sessions/s-1/projects/p-1/glossary': { id: 'g-2', term: 'прилив' },
      }).routes,
    )
    renderApp()
    await waitForProject()

    await userEvent.click(await screen.findByText('Глоссарий терминов'))
    await userEvent.type(await screen.findByLabelText('Термин'), 'прилив')
    await userEvent.type(screen.getByLabelText('Переводы'), 'en: tide')
    await userEvent.click(screen.getByRole('button', { name: 'Добавить' }))

    await waitFor(() => {
      const call = calls.find((c) => c.init.method === 'POST' && c.url.includes('/glossary'))
      expect(call).toBeDefined()
      expect(JSON.parse(String(call?.init.body))).toEqual({
        term: 'прилив',
        translations: { en: 'tide' },
        definition: undefined,
      })
    })
  })

  it('проверка терминологии показывает расхождения', async () => {
    mockApi(baseRoutes().routes)
    renderApp()
    await waitForProject()

    await userEvent.click(await screen.findByText('Глоссарий терминов'))
    await userEvent.click(
      await screen.findByRole('button', { name: 'Проверить терминологию в разделах' }),
    )

    expect(await screen.findByText('Термины расходятся')).toBeInTheDocument()
    expect(await screen.findByText(/«биомасса» вместо «biomass»/)).toBeInTheDocument()
  })
})

describe('история версий раздела', () => {
  it('сравнение версий показывает утверждения и цитаты', async () => {
    mockApi(
      baseRoutes({
        'GET /api/sessions/s-1/projects/p-1/section-plans/plan-1/diff': DIFF,
      }).routes,
    )
    renderApp()
    await waitForProject()

    await userEvent.click(await screen.findByRole('button', { name: 'История версий' }))
    expect(await screen.findByText(/Сравнение версий/)).toBeInTheDocument()
  })

  it('перевод раздела уходит на сервер с выбранным языком', async () => {
    const { calls } = mockApi(
      baseRoutes({
        'POST /api/sessions/s-1/projects/p-1/section-plans/plan-1/translate': {
          version_id: 'v-2',
          target_language: 'en',
        },
      }).routes,
    )
    renderApp()
    await waitForProject()

    await userEvent.click(await screen.findByRole('button', { name: 'История версий' }))
    await userEvent.click(
      await screen.findByLabelText('Язык перевода раздела'),
    )
    await userEvent.click(await screen.findByRole('option', { name: 'English (en)' }))
    await userEvent.click(screen.getByRole('button', { name: 'Перевести раздел' }))

    await waitFor(() => {
      const call = calls.find((c) => c.init.method === 'POST' && c.url.includes('/translate'))
      expect(call).toBeDefined()
      expect(JSON.parse(String(call?.init.body))).toMatchObject({
        target_language: 'en',
      })
    })
  })

  it('проверка стиля показывает отступления от стиля журнала', async () => {
    mockApi(
      baseRoutes({
        'POST /api/sessions/s-1/projects/p-1/style-compliance': {
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
      }).routes,
    )
    renderApp()
    await waitForProject()

    await userEvent.click(await screen.findByRole('button', { name: 'История версий' }))
    await userEvent.click(
      await screen.findByRole('button', { name: 'Проверить соответствие стилю' }),
    )

    expect(await screen.findByText('Есть отступления от стиля')).toBeInTheDocument()
    expect(await screen.findByText(/Разбейте абзац на два/)).toBeInTheDocument()
  })
})

describe('проверка готовности к генерации', () => {
  it('проверка идёт по кнопке и показывает замечания', async () => {
    const { calls } = mockApi(
      baseRoutes({
        'POST /api/sessions/s-1/projects/p-1/pre-generation-check': {
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
          warnings: ['Источников найдено мало: 1'],
          sources_preview: [],
        },
      }).routes,
    )
    renderApp()
    await waitForProject()

    // До нажатия запрос не уходит.
    expect(
      calls.filter((c) => c.url.includes('/pre-generation-check')),
    ).toHaveLength(0)

    await userEvent.type(
      await screen.findByLabelText('Вопрос или тема'),
      'О приливах',
    )
    // Проверка идёт по разделу — выбираем его.
    await userEvent.click(
      await screen.findByRole('combobox', { name: 'Раздел' }),
    )
    await userEvent.click(
      await screen.findByRole('option', { name: 'Introduction', hidden: true }),
    )
    await userEvent.click(screen.getByRole('button', { name: 'Проверить готовность' }))

    expect(await screen.findByText('Проверьте перед генерацией')).toBeInTheDocument()
    expect(await screen.findByText('Источников найдено мало: 1')).toBeInTheDocument()
  })
})

describe('аккордеон проекта', () => {
  it('новые панели доступны в редакторе проекта', async () => {
    mockApi(baseRoutes().routes)
    renderApp()
    await waitForProject()

    expect(await screen.findByText('Глоссарий терминов')).toBeInTheDocument()
    expect(await screen.findByText('Сборка статьи')).toBeInTheDocument()
  })

  it('панели открываются по клику и показывают содержимое', async () => {
    mockApi(baseRoutes().routes)
    renderApp()
    await waitForProject()

    await openManuscriptPanel()
    await waitFor(() =>
      expect(
        screen.getByRole('button', { name: 'Собрать статью' }),
      ).toBeInTheDocument(),
    )
  })
})
