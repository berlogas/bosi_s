/**
 * Тесты вкладки «Проекты».
 *
 * Проверяют то, что видит пользователь на текущем интерфейсе:
 * порядок работы, создание проекта, разделы с текстом в редакторе,
 * сохранение правки, генерацию, историю версий, статус, документы,
 * разбор черновика, выгрузку и режим архива.
 */

import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient } from '@tanstack/react-query'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { AppProviders } from '../../app/AppProviders'
import { AppRoutes } from '../../routes'
import { json, loginAs, mockApi, resetAuth } from '../../test/helpers'

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

/** Версия раздела: серверный текст в `current_version.content_md`. */
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

/** План раздела вместе с текущей версией. */
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

const HISTORY = {
  section_plan_id: 'plan-1',
  section_name: 'Introduction',
  roots: [{ version: VERSION, children: [] }],
  all_versions: [VERSION],
}

const DOC = {
  id: 'd-1',
  dockey: 'abcd1234',
  docname: 'doc',
  title: 'Отчёт',
  category: 'temp_literature',
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

const JOURNAL_STYLES = [
  {
    key: 'multidisciplinary_breakthrough',
    title: 'Мультидисциплинарный прорыв',
    summary: 'Nature, Science, Cell, PNAS: широкая аудитория, активный залог.',
    journals: ['Nature', 'Science', 'Cell', 'PNAS'],
    description: 'Читатель: междисциплинарные учёные.\nТон: вовлекающий, краткий.',
    description_lines: [
      'Читатель: междисциплинарные учёные.',
      'Тон: вовлекающий, краткий.',
    ],
    highlights: [
      'TARGET AUDIENCE: Multidisciplinary scientists. Avoid narrow jargon.',
      'TONE: Engaging, concise, active voice.',
    ],
    templates: [{ label: 'Abstract и Introduction', sections: ['abstract', 'introduction'] }],
  },
]

/**
 * Базовые ответы API.
 *
 * `plans` — общий объект, чтобы проверка правки видела, что сервер вернул
 * обновлённый текст (как это делает настоящий бэкенд).
 */
function baseRoutes(overrides: Record<string, unknown> = {}) {
  const plans = [{ ...PLAN }]
  return {
    plans,
    routes: {
      'GET /api/health': HEALTH,
      'GET /api/journal-styles': JOURNAL_STYLES,
      'GET /api/sessions/s-1': DETAIL,
      'GET /api/sessions': [SESSION],
      'GET /api/tasks': { tasks: [], active: 0 },
      'GET /api/chat/messages': { messages: [], total: 0, offset: 0 },
      'GET /api/sessions/s-1/documents': [DOC],
      'GET /api/sessions/s-1/projects': [PROJECT],
      'GET /api/sessions/s-1/projects/p-1/section-plans': plans,
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
      ...overrides,
    },
  }
}

beforeEach(() => {
  sessionStorage.clear()
  loginAs()
})

afterEach(() => {
  vi.unstubAllGlobals()
  resetAuth()
})

/** Дождаться, пока проект выберется и отрисуется его редактор. */
async function waitForProject() {
  await waitFor(() =>
    expect(screen.getAllByText(/Статья о приливах/).length).toBeGreaterThan(0),
  )
  return screen.findByLabelText('Текст раздела: Introduction')
}

describe('вкладка Проекты', () => {
  it('на странице есть порядок работы, а не только кнопки', async () => {
    mockApi(baseRoutes().routes)
    renderApp()

    expect(await screen.findByText('Как работать с проектом статьи')).toBeInTheDocument()
    expect(screen.getByText(/Привяжите документы с ролью/)).toBeInTheDocument()
    expect(screen.getByText(/обязана ставить ссылки на источники/)).toBeInTheDocument()
    expect(screen.getByText(/Разбор черновика/)).toBeInTheDocument()
    expect(screen.getByText(/Word, Markdown или ZIP/)).toBeInTheDocument()
  })

  it('подсказка подсказывает начать с создания, когда проектов нет', async () => {
    const { routes } = baseRoutes({ 'GET /api/sessions/s-1/projects': [] })
    mockApi(routes)
    renderApp()

    expect(await screen.findByText(/Начните с первого шага/)).toBeInTheDocument()
  })

  it('пустой список — «Проектов пока нет»', async () => {
    const { routes } = baseRoutes({ 'GET /api/sessions/s-1/projects': [] })
    mockApi(routes)
    renderApp()

    expect(await screen.findByText('Проектов пока нет')).toBeInTheDocument()
  })

  it('создание проекта уходит с названием и журналом', async () => {
    const { routes } = baseRoutes({
      'GET /api/sessions/s-1/projects': [],
      'POST /api/sessions/s-1/projects': { ...PROJECT, id: 'p-new', title: 'Новый проект' },
    })
    const { calls } = mockApi(routes)

    renderApp()
    await screen.findByText('Проектов пока нет')

    await userEvent.type(screen.getByLabelText('Название'), 'Новый проект')
    await userEvent.click(screen.getByRole('combobox', { name: 'Стиль журнала' }))
    await userEvent.click(
      await screen.findByRole('option', {
        name: 'Мультидисциплинарный прорыв',
        hidden: true,
      }),
    )
    await userEvent.click(screen.getByRole('button', { name: 'Создать' }))

    await waitFor(() => {
      const call = calls.find((c) => c.url.endsWith('/projects') && c.init.method === 'POST')
      expect(call).toBeDefined()
      expect(JSON.parse(String(call?.init.body))).toEqual({
        title: 'Новый проект',
        target_journal: 'multidisciplinary_breakthrough',
        language: 'ru',
      })
    })
  })

  it('выбор проекта показывает прогресс и разделы', async () => {
    mockApi(baseRoutes().routes)
    renderApp()

    await waitForProject()
    expect(await screen.findByText(/1\/5 разделов/)).toBeInTheDocument()
    expect(screen.getByText(/3 слов/)).toBeInTheDocument()
    // Название раздела есть и в аккордеоне разделов, и в таблице плана.
    expect(screen.getAllByText('Introduction').length).toBeGreaterThan(0)
  })

  it('текст раздела виден в редакторе без перезагрузки страницы', async () => {
    // Главная беда: текст генерируется и лежит в базе, но интерфейс его
    // не показывал — он брал только локальное состояние после генерации.
    mockApi(baseRoutes().routes)
    renderApp()

    const editor = await waitForProject()
    expect(editor).toHaveValue('Серверный текст раздела')
  })

  it('правка раздела сохраняется PUT-ом и остаётся в редакторе', async () => {
    const { plans, routes } = baseRoutes()
    // Сервер после правки отдаёт обновлённый текст — как настоящий бэкенд.
    ;(routes as Record<string, unknown>)[
      'PUT /api/sessions/s-1/projects/p-1/section-plans/plan-1/content'
    ] = (_url: string, init: RequestInit) => {
      const body = JSON.parse(String(init.body)) as { content_md: string }
      plans[0].current_version = {
        ...VERSION,
        content_md: body.content_md,
      } as typeof VERSION
      return json(plans[0].current_version)
    }
    const { calls } = mockApi(routes)

    renderApp()
    const editor = await waitForProject()

    await userEvent.clear(editor)
    await userEvent.type(editor, 'Новый черновик')

    const saveButton = screen.getByRole('button', { name: 'Сохранить' })
    await waitFor(() => expect(saveButton).toBeEnabled())
    await userEvent.click(saveButton)

    await waitFor(() => {
      const call = calls.find(
        (c) =>
          c.init.method === 'PUT' && c.url.includes('/section-plans/plan-1/content'),
      )
      expect(call).toBeDefined()
      expect(JSON.parse(String(call?.init.body))).toEqual({
        content_md: 'Новый черновик',
      })
    })
  })

  it('генерация раздела показывает результат под разделом', async () => {
    const { routes } = baseRoutes({
      'POST /api/sessions/s-1/projects/p-1/generate-v2': {
        version_id: 'v-2',
        section_plan_id: 'plan-1',
        content_md: 'Сгенерированный текст [1].',
        language: 'ru',
        word_count: 4,
        citation_map: [{ marker: '1', docname: 'Отчёт' }],
        quality_report: { citations_ok: false, warnings: ['Нет методики'] },
        status: 'draft',
        created_at: '2026-10-02T00:00:00+00:00',
      },
    })
    mockApi(routes)

    renderApp()
    await waitForProject()

    await userEvent.click(screen.getByRole('button', { name: 'Сгенерировать' }))

    expect(await screen.findByText(/Сгенерированный текст/)).toBeInTheDocument()
    expect(
      screen.getByText('Проверьте ссылки: часть из них не разрешается в источники.'),
    ).toBeInTheDocument()
    expect(screen.getByText(/⚠ Нет методики/)).toBeInTheDocument()
  })

  it('история версий показывает текст выбранной версии', async () => {
    mockApi(baseRoutes().routes)
    renderApp()
    await waitForProject()

    await userEvent.click(
      screen.getAllByRole('button', { name: 'История версий' })[0],
    )

    expect(await screen.findByText(/Версия от/)).toBeInTheDocument()
    // Текст версии показывается и в открытой панели, и в общем списке истории.
    expect(screen.getAllByText('Серверный текст раздела').length).toBeGreaterThan(0)
  })

  it('статус проекта сохраняется PATCH-ом при изменении', async () => {
    const { routes } = baseRoutes({
      'PATCH /api/sessions/s-1/projects/p-1': { ...PROJECT, status: 'drafting' },
    })
    const { calls } = mockApi(routes)

    renderApp()
    await waitForProject()

    // В списке проектов статус — Select без подписи; ищем по текущему значению.
    const statusBox = await waitFor(() => {
      const found = screen
        .getAllByRole('combobox')
        .find((box) => (box as HTMLInputElement).value === 'Планирование (planning)')
      expect(found).toBeDefined()
      return found as HTMLInputElement
    })
    await userEvent.click(statusBox)
    await userEvent.click(
      (await screen.findAllByRole('option', {
        name: 'Написание текста (drafting)',
        hidden: true,
      }))[0],
    )

    await waitFor(() => {
      const call = calls.find((c) => c.init.method === 'PATCH')
      expect(call).toBeDefined()
      expect(JSON.parse(String(call?.init.body))).toEqual({ status: 'drafting' })
    })
  })

  it('привязка документа уходит с ролью, отвязка — DELETE', async () => {
    const { routes } = baseRoutes({
      'GET /api/sessions/s-1/projects/p-1/documents': [{ document: DOC, role: 'data' }],
    })
    const { calls } = mockApi(routes)

    renderApp()
    await waitForProject()

    // Панель документов лежит в аккордеоне — открываем его.
    await userEvent.click(screen.getByRole('button', { name: 'Документы проекта' }))

    expect(await screen.findByText('Данные (data)')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Отвязать Отчёт' }))
    await waitFor(() =>
      expect(
        calls.some(
          (c) =>
            c.init.method === 'DELETE' && c.url.includes('/projects/p-1/documents/d-1'),
        ),
      ).toBe(true),
    )
  })

  it('разбор черновика: пробелы списком', async () => {
    const { routes } = baseRoutes({
      'GET /api/sessions/s-1/projects/p-1/draft-analysis': {
        has_gaps: true,
        gaps: [
          {
            severity: 'high',
            where: 'Methods',
            hint: 'Раздел «Methods» не написан.',
            excerpt: '',
          },
        ],
        by_severity: { high: 1, medium: 0, low: 0 },
      },
    })
    mockApi(routes)

    renderApp()
    await waitForProject()

    await userEvent.click(screen.getByRole('tab', { name: 'Анализ' }))
    await userEvent.click(screen.getByRole('button', { name: 'Разбор черновика' }))

    expect(
      await screen.findByText(/Найдено пробелов: 1 \(критичных 1\)/),
    ).toBeInTheDocument()
  })

  it('вид генерации уходит в запрос техническим значением', async () => {
    const { routes } = baseRoutes({
      'POST /api/sessions/s-1/projects/p-1/generate-v2': {
        version_id: 'v-2',
        section_plan_id: 'plan-1',
        content_md: 'Обсуждение результатов.',
        language: 'ru',
        word_count: 3,
        citation_map: [],
        quality_report: { citations_ok: true, warnings: [] },
        status: 'draft',
        created_at: '2026-10-02T00:00:00+00:00',
      },
    })
    const { calls } = mockApi(routes)

    renderApp()
    await waitForProject()

    // Выпадающий список «Вид» — Mantine Select, варианты живут в портале.
    const kindBox = screen.getAllByRole('combobox').find((box) =>
      document
        .querySelector(`label[for="${box.id}"]`)
        ?.textContent?.startsWith('Вид'),
    )
    expect(kindBox).toBeDefined()
    await userEvent.click(kindBox as HTMLElement)
    await userEvent.click(
      await screen.findByRole('option', {
        name: 'Обсуждение результатов (discussion)',
        hidden: true,
      }),
    )
    await userEvent.type(screen.getByLabelText('Вопрос или тема'), 'Что получилось')
    await userEvent.click(screen.getByRole('button', { name: 'Запустить' }))

    await waitFor(() => {
      const sent = calls.find(
        (c) => c.init.method === 'POST' && c.url.includes('/generate-v2'),
      )
      expect(sent, 'POST /generate-v2 не ушёл').toBeDefined()
      const body = JSON.parse(String(sent?.init.body)) as Record<string, unknown>
      expect(body.kind).toBe('discussion')
      // у вида «обсуждение» свой раздел — он не пустой
      expect(String(body.section).length).toBeGreaterThan(0)
    })
  })

  it('план разделов: «Синхронизировать из JSON» зовёт сервер', async () => {
    const { routes } = baseRoutes({
      'POST /api/sessions/s-1/projects/p-1/section-plans/sync': {
        synced: 5,
        plans: [{ id: 'plan-1', name: 'Introduction' }],
      },
    })
    const { calls } = mockApi(routes)

    renderApp()
    await waitForProject()

    await userEvent.click(
      await screen.findByRole('button', { name: 'Документы проекта' }),
    )
    await userEvent.click(
      await screen.findByRole('button', { name: 'План разделов (новая система)' }),
    )
    await userEvent.click(
      await screen.findByRole('button', { name: 'Синхронизировать из JSON' }),
    )

    await waitFor(() =>
      expect(
        calls.some(
          (c) =>
            c.init.method === 'POST' && c.url.includes('/section-plans/sync'),
        ),
      ).toBe(true),
    )
  })

  it('план разделов: «Добавить раздел» создаёт раздел', async () => {
    const { routes } = baseRoutes({
      'POST /api/sessions/s-1/projects/p-1/section-plans': { id: 'plan-2', name: 'Методы' },
    })
    const { calls } = mockApi(routes)

    renderApp()
    await waitForProject()

    await userEvent.click(
      await screen.findByRole('button', { name: 'Документы проекта' }),
    )
    await userEvent.click(
      await screen.findByRole('button', { name: 'План разделов (новая система)' }),
    )
    await userEvent.click(
      await screen.findByRole('button', { name: 'Добавить раздел' }),
    )
    // В модалке своё поле «Название» — ищем внутри окна, а не по всей странице.
    const dialog = await screen.findByRole('dialog')
    await userEvent.type(
      within(dialog).getByLabelText('Название'),
      'Методы',
    )
    await userEvent.click(within(dialog).getByRole('button', { name: 'Сохранить' }))

    await waitFor(() => {
      const sent = calls.find(
        (c) =>
          c.init.method === 'POST' && c.url.endsWith('/section-plans'),
      )
      expect(sent, 'POST /section-plans не ушёл').toBeDefined()
      const body = JSON.parse(String(sent?.init.body)) as Record<string, unknown>
      expect(body.name).toBe('Методы')
    })
  })

  it('история версий: версию можно одобрить и откатить', async () => {
    const { routes } = baseRoutes({
      'POST /api/sessions/s-1/projects/p-1/section-plans/plan-1/approve': VERSION,
      'POST /api/sessions/s-1/projects/p-1/section-plans/plan-1/rollback': VERSION,
    })
    const { calls } = mockApi(routes)

    renderApp()
    await waitForProject()

    await userEvent.click(
      screen.getAllByRole('button', { name: 'История версий' })[0],
    )
    expect(await screen.findByText(/Версия от/)).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: 'Одобрить' }))
    await waitFor(() =>
      expect(
        calls.some((c) => c.url.includes('/section-plans/plan-1/approve')),
      ).toBe(true),
    )

    await userEvent.click(
      screen.getByRole('button', { name: 'Откатить к этой версии' }),
    )
    await waitFor(() =>
      expect(
        calls.some((c) => c.url.includes('/section-plans/plan-1/rollback')),
      ).toBe(true),
    )
  })

  it('выгрузка: Word по умолчанию, имя файла из заголовка', async () => {
    const downloads: string[] = []
    const createObjectURL = vi.fn(() => 'blob:article')
    const revokeObjectURL = vi.fn()
    vi.stubGlobal('URL', { ...URL, createObjectURL, revokeObjectURL })
    const click = vi
      .spyOn(HTMLAnchorElement.prototype, 'click')
      .mockImplementation(function (this: HTMLAnchorElement) {
        downloads.push(this.download)
      })

    const { routes } = baseRoutes({
      'GET /api/sessions/s-1/projects/p-1/export': new Response('binary', {
        status: 200,
        headers: {
          'Content-Disposition':
            "attachment; filename=\"article.docx\"; filename*=UTF-8''%D0%91%D0%B0%D0%BD%D0%BA%D0%B0.docx",
          'Content-Type': 'application/octet-stream',
        },
      }),
    })
    mockApi(routes)
    renderApp()
    await waitForProject()

    await userEvent.click(screen.getByRole('button', { name: 'Экспорт' }))
    await userEvent.click(await screen.findByRole('button', { name: 'Выгрузить' }))

    expect(await screen.findByText('Файл скачан: Банка.docx')).toBeInTheDocument()
    expect(downloads).toEqual(['Банка.docx'])
    expect(createObjectURL).toHaveBeenCalled()
    expect(revokeObjectURL).toHaveBeenCalledWith('blob:article')
    click.mockRestore()
  })

  it('архивная сессия: редактирование заблокировано', async () => {
    const { routes } = baseRoutes({
      'GET /api/sessions/s-1': { ...DETAIL, status: 'archived', writable: false },
    })
    mockApi(routes)
    renderApp()

    await waitFor(() =>
      expect(screen.getAllByText(/Статья о приливах/).length).toBeGreaterThan(0),
    )
    expect(await screen.findByText(/1\/5 разделов/)).toBeInTheDocument()
    expect(screen.getByLabelText('Название')).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Создать' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Удалить' })).toBeDisabled()
    // Редактор раздела отключён для архивной сессии
    const editor = await screen.findByLabelText('Текст раздела: Introduction')
    expect(editor).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Сгенерировать' })).toBeDisabled()
  })
})
