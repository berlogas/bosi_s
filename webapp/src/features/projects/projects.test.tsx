/**
 * Тесты вкладки «Проекты» (Фаза 3, паритет project_editor.py):
 * создание, выбор, статус, разделы (черновик → сохранить), генерация,
 * привязка документов, пустой список, read-only архива.
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

const SECTION = {
  name: 'Introduction',
  required: true,
  order: 1,
  word_target: 600,
  notes: '',
  content_md: 'Серверный текст',
  words: 3,
  written: false,
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
    highlights: [
      'TARGET AUDIENCE: Multidisciplinary scientists. Avoid narrow jargon.',
      'TONE: Engaging, concise, active voice.',
    ],
    templates: [{ label: 'Abstract и Introduction', sections: ['abstract', 'introduction'] }],
  },
  {
    key: 'sound_science',
    title: 'Здоровая наука',
    summary: 'PLOS ONE, Scientific Reports: воспроизводимость и сухое описание.',
    journals: ['PLOS ONE', 'Scientific Reports'],
    highlights: ['TONE: Dry, descriptive, highly detailed.'],
    templates: [
      { label: 'Materials and Methods', sections: ['methods'] },
      { label: 'Results (описательные)', sections: ['results'] },
    ],
  },
]

function mockProjectsApi(routes: Record<string, unknown> = {}) {
  return mockApi({
    'GET /api/health': HEALTH,
    'GET /api/journal-styles': JOURNAL_STYLES,
    'GET /api/sessions/s-1': DETAIL,
    'GET /api/sessions': [SESSION],
    'GET /api/tasks': { tasks: [], active: 0 },
    'GET /api/chat/messages': { messages: [], total: 0, offset: 0 },
    'GET /api/sessions/s-1/documents': [DOC],
    'GET /api/sessions/s-1/projects': [PROJECT],
    'GET /api/sessions/s-1/projects/p-1/sections': [SECTION],
    'GET /api/sessions/s-1/projects/p-1/documents': [],
    'GET /api/sessions/s-1/projects/p-1/progress': {
      project_id: 'p-1',
      status: 'planning',
      sections: 5,
      written: 1,
      words: 3,
      percent: 20,
    },
    ...routes,
  })
}

beforeEach(() => {
  sessionStorage.clear()
  loginAs()
})

afterEach(() => {
  vi.unstubAllGlobals()
  resetAuth()
})

describe('вкладка Проекты', () => {
  it('на странице есть порядок работы, а не только кнопки', async () => {
    mockProjectsApi()
    renderApp()

    expect(
      await screen.findByText('Как работать с проектом статьи'),
    ).toBeInTheDocument()
    // три шага, без которых не понять, что нажимать первым
    expect(screen.getByText(/Привяжите документы с ролью/)).toBeInTheDocument()
    expect(screen.getByText(/обязана ставить ссылки на источники/)).toBeInTheDocument()
    expect(screen.getByText(/Разбор черновика/)).toBeInTheDocument()
    expect(screen.getByText(/Word, Markdown или ZIP/)).toBeInTheDocument()
  })

  it('подсказка подсказывает начать с создания, когда проектов нет', async () => {
    mockProjectsApi({ 'GET /api/sessions/s-1/projects': [] })
    renderApp()

    expect(await screen.findByText(/Начните с первого шага/)).toBeInTheDocument()
  })

  it('выгрузка: Word по умолчанию, имя файла из заголовка', async () => {
    const downloads: string[] = []
    const createObjectURL = vi.fn(() => 'blob:article')
    const revokeObjectURL = vi.fn()
    vi.stubGlobal('URL', {
      ...URL,
      createObjectURL,
      revokeObjectURL,
    })
    const click = vi
      .spyOn(HTMLAnchorElement.prototype, 'click')
      .mockImplementation(function (this: HTMLAnchorElement) {
        downloads.push(this.download)
      })

    mockProjectsApi({
      'GET /api/sessions/s-1/projects/p-1/export': new Response('binary', {
        status: 200,
        headers: {
          'Content-Disposition':
            'attachment; filename="article.docx"; filename*=UTF-8\'\'%D0%91%D0%B0%D0%BD%D0%BA%D0%B0.docx',
          'Content-Type': 'application/octet-stream',
        },
      }),
    })
    renderApp()

    const button = await screen.findByRole('button', { name: 'Выгрузить' })
    await userEvent.click(button)

    expect(await screen.findByText('Файл сохранён: Банка.docx')).toBeInTheDocument()
    expect(downloads).toEqual(['Банка.docx'])
    expect(createObjectURL).toHaveBeenCalled()
    expect(revokeObjectURL).toHaveBeenCalledWith('blob:article')
    click.mockRestore()
  })

  it('выгрузка: ошибка показывается текстом, а не молчит', async () => {
    mockProjectsApi({
      'GET /api/sessions/s-1/projects/p-1/export': json(
        { detail: 'Проект не готов' },
        500,
      ),
    })
    renderApp()

    await userEvent.click(await screen.findByRole('button', { name: 'Выгрузить' }))

    expect(await screen.findByText(/Не удалось выгрузить/)).toBeInTheDocument()
  })

  it('пустой список — «Проектов нет — создайте первый»', async () => {
    mockProjectsApi({ 'GET /api/sessions/s-1/projects': [] })

    renderApp()

    expect(
      await screen.findByText('Проектов нет — создайте первый.'),
    ).toBeInTheDocument()
  })

  it('создание проекта уходит с названием и журналом', async () => {
    const { calls } = mockProjectsApi({
      'GET /api/sessions/s-1/projects': [],
      'POST /api/sessions/s-1/projects': {
        ...PROJECT,
        id: 'p-new',
        title: 'Новый проект',
      },
      'GET /api/sessions/s-1/projects/p-new/sections': [],
      'GET /api/sessions/s-1/projects/p-new/documents': [],
      'GET /api/sessions/s-1/projects/p-new/progress': {
        project_id: 'p-new',
        sections: 0,
        written: 0,
        words: 0,
        percent: 0,
      },
    })

    renderApp()
    await screen.findByText('Проектов нет — создайте первый.')

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
      const call = calls.find(
        (c) => c.url.endsWith('/projects') && c.init.method === 'POST',
      )
      expect(call).toBeDefined()
      expect(JSON.parse(String(call?.init.body))).toEqual({
        title: 'Новый проект',
        target_journal: 'multidisciplinary_breakthrough',
      })
    })
  })

  it('выбор проекта показывает прогресс, статус и раздел', async () => {
    mockProjectsApi()

    renderApp()

    expect(await screen.findByText(/1\/5 разделов/)).toBeInTheDocument()
    expect(screen.getByText(/3 слов/)).toBeInTheDocument()
    expect(screen.getByLabelText('Статус', { selector: 'input' })).toHaveValue(
      'Планирование (planning)',
    )
    // раздел из API, черновик берётся из серверного content_md
    const area = await screen.findByLabelText('Текст раздела: Введение (Introduction)')
    expect(area).toHaveValue('Серверный текст')
  })

  it('правка раздела живёт в черновике и сохраняется PUT-ом', async () => {
    const { calls } = mockProjectsApi({
      'PUT /api/sessions/s-1/projects/p-1/sections/Introduction': {
        ...SECTION,
        content_md: 'Новый черновик',
        words: 2,
      },
    })

    renderApp()
    const area = await screen.findByLabelText('Текст раздела: Введение (Introduction)')

    await userEvent.clear(area)
    await userEvent.type(area, 'Новый черновик')
    // черновик сразу в sessionStorage (паритет state.drafts)
    expect(sessionStorage.getItem('boasi.project.drafts')).toContain('Новый черновик')

    const sectionCard = area.closest('.mantine-Accordion-panel')
    await userEvent.click(
      within(sectionCard as HTMLElement).getByRole('button', { name: 'Сохранить' }),
    )

    await waitFor(() => {
      const call = calls.find(
        (c) => c.init.method === 'PUT' && c.url.includes('/sections/'),
      )
      expect(call).toBeDefined()
      expect(JSON.parse(String(call?.init.body))).toEqual({
        content_md: 'Новый черновик',
      })
    })
    expect(await screen.findByText('Раздел сохранён.')).toBeInTheDocument()
  })

  it('генерация раздела: спиннер → результат под разделом', async () => {
    mockProjectsApi({
      'POST /api/sessions/s-1/projects/p-1/generate': {
        project_id: 'p-1',
        section: 'Introduction',
        content_md: 'Сгенерированный текст [1].',
        word_count: 4,
        sources: [],
        references: ['[1] Отчёт'],
        citations_ok: false,
        warnings: ['Нет методики'],
        seconds: 1.5,
        from_cache: false,
      },
    })

    renderApp()
    const area = await screen.findByLabelText('Текст раздела: Введение (Introduction)')
    const sectionCard = area.closest('.mantine-Accordion-panel')

    await userEvent.click(
      within(sectionCard as HTMLElement).getByRole('button', { name: 'Сгенерировать' }),
    )

    // parитет _generate: текст, предупреждение о ссылках и ⚠ warnings
    expect(await screen.findByText(/Сгенерированный текст/)).toBeInTheDocument()
    expect(
      screen.getByText('Проверьте ссылки: часть из них не разрешается в источники.'),
    ).toBeInTheDocument()
    expect(screen.getByText(/⚠ Нет методики/)).toBeInTheDocument()
    // список источников свёрнут по умолчанию — раскрываем и ищем в нём
    await userEvent.click(
      within(sectionCard as HTMLElement).getByRole('button', { name: 'Источники' }),
    )
    expect(
      within(sectionCard as HTMLElement).getByText(/Отчёт/),
    ).toBeInTheDocument()
  })

/**
 * Открывает список видов и возвращает его узел.
 *
 * Mantine держит варианты в портале, а не рядом с полем, и в jsdom
 * помечает их скрытыми — ищем по связи aria-labelledby, а не по индексу
 * combobox: на странице их шесть, и по порядку открывается не то поле.
 */
async function openKindList(): Promise<HTMLElement> {
  await screen.findByLabelText('Текст раздела: Введение (Introduction)')
  const kindInput = screen
    .getAllByRole('combobox')
    .find((box) =>
      document.querySelector(`label[for="${box.id}"]`)?.textContent?.startsWith('Вид'),
    )
  if (!kindInput) throw new Error('поле «Вид» не найдено')
  await userEvent.click(kindInput)
  return waitFor(() => {
    const label = document.querySelector(`label[for="${kindInput.id}"]`)
    const found =
      document.querySelector(`[role="listbox"][aria-labelledby="${kindInput.id}"]`) ??
      (label
        ? document.querySelector(`[role="listbox"][aria-labelledby="${label.id}"]`)
        : null)
    if (!found) throw new Error('список видов не открылся')
    return found as HTMLElement
  })
}

  it('в списке видов есть discussion — он есть в GenerationKind', async () => {
    mockProjectsApi()
    renderApp()

    const listbox = await openKindList()
    const options = within(listbox)
      .getAllByRole('option', { hidden: true })
      .map((node) => node.textContent)
    expect(options).toEqual(
      expect.arrayContaining(['Обсуждение результатов (discussion)']),
    )
    // 7 значений в GenerationKind; меньше — признак расхождения с backend
    expect(options).toHaveLength(7)
    // техническое значение уходит в запрос, а не подпись
    expect(options.some((label) => /^[a-z_]+$/.test(label))).toBe(false)
  })

  it('выбранный вид уходит в запрос техническим значением, а не подписью', async () => {
    const { calls } = mockProjectsApi({
      'POST /api/sessions/s-1/projects/p-1/generate': {
        body: {
          section: '',
          content_md: 'Текст.',
          word_count: 1,
          citations_ok: true,
          sources: [],
          warnings: [],
          references: [],
          kind: 'discussion',
          from_cache: false,
        },
      },
    })

    renderApp()
    const listbox = await openKindList()
    await userEvent.click(
      within(listbox).getByRole('option', {
        name: 'Обсуждение результатов (discussion)',
        hidden: true,
      }),
    )
    const kindField = screen
      .getAllByRole('combobox')
      .find((box) =>
        document.querySelector(`label[for="${box.id}"]`)?.textContent?.startsWith('Вид'),
      )
    expect(kindField).toHaveValue('Обсуждение результатов (discussion)')
    await userEvent.type(
      screen.getByLabelText('Вопрос или тема'),
      'Сопоставление с литературой',
    )
    await userEvent.click(screen.getByRole('button', { name: 'Запустить' }))

    await waitFor(() => {
      const sent = calls.find(
        (c) => c.init.method === 'POST' && c.url.includes('/projects/p-1/generate'),
      )
      expect(sent, 'POST /generate не ушёл').toBeDefined()
      // в запрос уходит техническое значение вида, а не подпись из списка
      expect(String(sent?.init.body)).toContain('"kind":"discussion"')
    })
  })

  it('журнал вне справочника вводится вручную', async () => {
    const { calls } = mockProjectsApi({
      'GET /api/sessions/s-1/projects': [],
      'POST /api/sessions/s-1/projects': { ...PROJECT, id: 'p-new' },
      'GET /api/sessions/s-1/projects/p-new/sections': [],
      'GET /api/sessions/s-1/projects/p-new/documents': [],
      'GET /api/sessions/s-1/projects/p-new/progress': {
        project_id: 'p-new', sections: 0, written: 0, words: 0, percent: 0,
      },
    })

    renderApp()
    await screen.findByText('Проектов нет — создайте первый.')
    await userEvent.type(screen.getByLabelText('Название'), 'Свой журнал')
    await userEvent.click(screen.getByRole('combobox', { name: 'Стиль журнала' }))
    await userEvent.click(
      await screen.findByRole('option', {
        name: 'Другой журнал — вписать вручную',
        hidden: true,
      }),
    )
    await userEvent.type(screen.getByLabelText('Название журнала'), 'ICES JCR')
    await userEvent.click(screen.getByRole('button', { name: 'Создать' }))

    await waitFor(() => {
      const call = calls.find(
        (c) => c.url.endsWith('/projects') && c.init.method === 'POST',
      )
      expect(JSON.parse(String(call?.init.body)).target_journal).toBe('ICES JCR')
    })
  })

  it('статус проекта сохраняется PATCH-ом', async () => {
    const { calls } = mockProjectsApi({
      'PATCH /api/sessions/s-1/projects/p-1': { ...PROJECT, status: 'drafting' },
    })

    renderApp()
    await screen.findByText(/1\/5 разделов/)

    // jsdom: listbox Mantine остаётся display:none — ищем option с hidden
    await userEvent.click(screen.getByLabelText('Статус', { selector: 'input' }))
    await userEvent.click(
      await screen.findByRole('option', { name: 'Написание текста (drafting)', hidden: true }),
    )
    await userEvent.click(screen.getByRole('button', { name: 'Обновить' }))

    await waitFor(() => {
      const call = calls.find((c) => c.init.method === 'PATCH')
      expect(call).toBeDefined()
      expect(JSON.parse(String(call?.init.body))).toEqual({ status: 'drafting' })
    })
  })

  it('привязка документа уходит с ролью, отвязка — DELETE', async () => {
    const { calls } = mockProjectsApi({
      'GET /api/sessions/s-1/projects/p-1/documents': [{ document: DOC, role: 'data' }],
    })

    renderApp()

    expect(
      await screen.findByText(/Отчёт — роль: Данные \(data\)/),
    ).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Отвязать' }))
    await waitFor(() =>
      expect(
        calls.some(
          (c) =>
            c.init.method === 'DELETE' && c.url.includes('/projects/p-1/documents/d-1'),
        ),
      ).toBe(true),
    )
  })

  it('разбор черновика: пробелы списком (паритет _generate_panel)', async () => {
    mockProjectsApi({
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

    renderApp()
    await screen.findByText(/1\/5 разделов/)

    await userEvent.click(screen.getByRole('button', { name: 'Разбор черновика' }))

    expect(
      await screen.findByText(/Найдено пробелов: 1 \(критичных 1\)/),
    ).toBeInTheDocument()
    expect(screen.getByText(/Methods.*не написан/)).toBeInTheDocument()
  })

  it('архивная сессия: редактирование заблокировано', async () => {
    mockProjectsApi({
      'GET /api/sessions/s-1': { ...DETAIL, status: 'archived', writable: false },
    })

    renderApp()

    expect(await screen.findByText(/1\/5 разделов/)).toBeInTheDocument()
    expect(screen.getByLabelText('Название')).toBeDisabled()
    expect(screen.getByLabelText('Статус', { selector: 'input' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Создать' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Обновить' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Удалить' })).toBeDisabled()
    const area = await screen.findByLabelText('Текст раздела: Введение (Introduction)')
    expect(area).toBeDisabled()
    expect(screen.queryByRole('button', { name: 'Сохранить' })).toBeDisabled()
  })
})
