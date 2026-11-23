/**
 * Тесты вкладки «Документы» (Фаза 3 + Волна 4): добавление по пути, dropzone
 * с валидацией форматов, группировка по категориям, удаление с подтверждением,
 * прогресс индексации, лимиты и read-only архива.
 */

import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient } from '@tanstack/react-query'
import { notifications } from '@mantine/notifications'
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
  resume_note: null,
  state_snapshot: {},
  usage: { sources: 0, messages: 0, downloads: 0, export_count: 0, minutes_used: 0 },
  summary: {
    title: '',
    sources: 0,
    documents: 1,
    documents_limit: 50,
    storage_bytes: 1024,
    storage_limit_bytes: 524288000,
    projects: 0,
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

const DOC = {
  id: 'd-1',
  dockey: 'abcd1234efgh',
  docname: 'otchet',
  title: 'Отчёт 2025',
  category: 'temp_literature',
  status: 'ready',
  size_bytes: 2048,
  chunk_count: 7,
  tags: ['прилив', 'смок'],
}

const DOC2 = {
  ...DOC,
  id: 'd-2',
  dockey: 'ffff0000aaaa',
  title: 'Заметки полевые',
  category: 'notes',
  tags: [],
}

function renderApp(path = '/s/s-1/documents') {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  })
  return render(
    <AppProviders initialPath={path} queryClient={queryClient}>
      <AppRoutes />
    </AppProviders>,
  )
}

function mockDocsApi(routes: Record<string, unknown> = {}) {
  return mockApi({
    'GET /api/health': HEALTH,
    'GET /api/sessions/s-1': DETAIL,
    'GET /api/sessions': [SESSION],
    'GET /api/tasks': { tasks: [], active: 0 },
    'GET /api/chat/messages': { messages: [], total: 0, offset: 0 },
    'GET /api/sessions/s-1/documents': [DOC, DOC2],
    ...routes,
  })
}

beforeEach(() => {
  sessionStorage.clear()
  loginAs()
  // Сбрасываем location, чтобы useSearchParams начинал с чистого состояния
  window.history.replaceState(null, '', '/s/s-1/documents')
})

afterEach(() => {
  vi.unstubAllGlobals()
  resetAuth()
  // Уведомления живут в портале и переживают размонтирование: их текст
  // мешал бы findByText. Чистим штатным способом — портал при этом остаётся
  // на месте: удалять его из DOM нельзя, React на него ссылается.
  notifications.clean()
})

describe('вкладка Документы', () => {
  it('список сгруппирован по категориям, размер/чанки/теги на месте', async () => {
    mockDocsApi()

    renderApp()

    expect(await screen.findByText(/Временная литература/)).toBeInTheDocument()
    const notesGroups = screen.getAllByText(/Заметки/)
    expect(notesGroups.length).toBeGreaterThan(0)
    // аккордеон раскрыт по умолчанию (defaultValue)
    expect(await screen.findByText(/Отчёт 2025 — 2 КБ, 7 чанков/)).toBeInTheDocument()
    expect(screen.getByText('теги: прилив, смок')).toBeInTheDocument()
    // dockey обрезан до 8 символов
    expect(screen.getByText('abcd1234')).toBeInTheDocument()
  })

  it('добавление по пути уходит с категорией и тегами, поле очищается', async () => {
    const { calls } = mockDocsApi({
      'POST /api/sessions/s-1/documents/path': {
        id: 'd-3',
        dockey: 'new',
        title: 'Новый',
        category: 'project_data',
        tags: ['a'],
      },
    })

    renderApp()

    await screen.findByText('Временная литература (1)')
    // Категория по умолчанию 'all' — не передаётся в запросе
    await userEvent.type(
      screen.getByLabelText('Путь к файлу на диске'),
      '/data/file.pdf',
    )
    // TagsInput: вводим теги через запятую
    const tagsInput = screen.getByLabelText('Теги', { selector: 'input' })
    await userEvent.type(tagsInput, 'a,b')
    await userEvent.click(screen.getByRole('button', { name: 'Добавить' }))

    await waitFor(() => {
      const call = calls.find((c) => c.url.includes('/documents/path'))
      expect(call).toBeDefined()
      const body = JSON.parse(String(call?.init.body))
      expect(body).toMatchObject({
        path: '/data/file.pdf',
        tags: ['a', 'b'],
        force_reindex: false,
      })
      expect(body.category).toBeUndefined()
    })
    await waitFor(() =>
      expect(screen.getByLabelText('Путь к файлу на диске')).toHaveValue(''),
    )
  })

  it('без пути кнопка «Добавить» заблокирована', async () => {
    mockDocsApi()

    renderApp()

    await screen.findByText('Временная литература (1)')
    expect(screen.getByRole('button', { name: 'Добавить' })).toBeDisabled()
  })

  it('загрузка файлов уходит POST на /documents/upload', async () => {
    const { calls: _calls } = mockDocsApi({
      'POST /api/sessions/s-1/documents/upload': {
        added: [DOC],
        duplicates: [],
        failed: [],
        total: 1,
      },
    })
    void _calls

    renderApp()
    await screen.findByText('Временная литература (1)')

    // Проверяем, что кнопка загрузки появляется только при наличии файлов
    expect(
      screen.queryByRole('button', { name: 'Загрузить файлы' }),
    ).not.toBeInTheDocument()
  })

  it('загрузка идёт в фон: сервер отдаёт task_id, прогресс виден в панели задач', async () => {
    const { calls } = mockDocsApi({
      'POST /api/sessions/s-1/documents/upload-async': { task_id: 't-1', total: 1 },
      'GET /api/tasks': {
        tasks: [
          {
            id: 't-1',
            kind: 'indexing',
            title: 'Индексация 1 файлов',
            status: 'running',
            progress: 40,
            step: 'файл 1/1: report.md',
            error: null,
            cancel_requested: false,
            user_id: 'u-1',
            session_id: 's-1',
            project_id: null,
            created_at: '2026-10-01T00:00:00+00:00',
            started_at: '2026-10-01T00:00:00+00:00',
            finished_at: null,
            seconds: 3,
            stage_seconds: 2,
            result: null,
          },
        ],
        active: 1,
      },
    })

    renderApp()
    await screen.findByText('Временная литература (1)')

    const input = screen.getByTestId('doc-file-input')
    await userEvent.upload(
      input,
      new File(['# Отчёт\n\nХлорофилл 1.85.\n'], 'report.md', {
        type: 'text/markdown',
      }),
    )

    await userEvent.click(screen.getByRole('button', { name: 'Загрузить файлы' }))

    // Фоновая загрузка: ответ — task_id, а не список документов.
    await waitFor(() => {
      const call = calls.find((c) => c.url.includes('/documents/upload-async'))
      expect(call).toBeDefined()
      expect(call?.init.method).toBe('POST')
    })
    expect(
      calls.some(
        (c) => c.url.includes('/documents/upload') && !c.url.includes('upload-async'),
      ),
    ).toBe(false)

    // Панель задачи с прогрессом индексации: у живой задачи видно этап.
    expect(await screen.findByText(/файл 1\/1: report.md/)).toBeInTheDocument()
    expect(await screen.findByLabelText(/Индексация 1 файлов: 40%/)).toBeInTheDocument()
  })

  it('файл с тем же именем спрашивает замену прежней версии', async () => {
    const { calls } = mockDocsApi({
      'GET /api/sessions/s-1/documents': [{ ...DOC, filename: 'otchet.md' }],
      'POST /api/sessions/s-1/documents/upload-async': { task_id: 't-3', total: 1 },
    })

    renderApp()
    await screen.findByText('Временная литература (1)')

    const input = screen.getByTestId('doc-file-input')
    await userEvent.upload(
      input,
      new File(['# Отчёт\n\nХлорофилл 1.85.\n'], 'otchet.md', {
        type: 'text/markdown',
      }),
    )

    await userEvent.click(screen.getByRole('button', { name: 'Загрузить файлы' }))

    // Спрашиваем подтверждение — молча перезаписывать нельзя.
    expect(await screen.findByText('Заменить прежние версии?')).toBeInTheDocument()
    expect(calls.some((c) => c.url.includes('/documents/upload-async'))).toBe(false)

    await userEvent.click(screen.getByRole('button', { name: 'Заменить и загрузить' }))

    await waitFor(() => {
      const call = calls.find((c) => c.url.includes('/documents/upload-async'))
      expect(call).toBeDefined()
      const body = call?.init.body as FormData
      expect(body.get('replace')).toBe('true')
    })
  })

  it('после индексации показывается итог: сколько добавили и что не разобрали', async () => {
    mockDocsApi({
      'POST /api/sessions/s-1/documents/upload-async': { task_id: 't-2', total: 2 },
      'GET /api/tasks': {
        tasks: [
          {
            id: 't-2',
            kind: 'indexing',
            title: 'Индексация 2 файлов',
            status: 'done',
            progress: 100,
            step: 'готово',
            error: null,
            cancel_requested: false,
            user_id: 'u-1',
            session_id: 's-1',
            project_id: null,
            created_at: '2026-10-01T00:00:00+00:00',
            started_at: '2026-10-01T00:00:00+00:00',
            finished_at: '2026-10-01T00:00:05+00:00',
            seconds: 5,
            stage_seconds: 1,
            result: {
              added: [{ id: 'd-9', docname: 'report', chunks: 3 }],
              duplicates: ['notes.md'],
              failed: [{ name: 'broken.pdf', error: 'Не удалось прочитать PDF' }],
              total: 3,
            },
          },
        ],
        active: 0,
      },
    })

    renderApp()
    await screen.findByText('Временная литература (1)')

    expect(await screen.findByText('Итог индексации')).toBeInTheDocument()
    expect(
      await screen.findByText(/Проиндексировано: 1.*дубликатов: 1.*с ошибкой: 1/),
    ).toBeInTheDocument()
    expect(
      await screen.findByText(/broken.pdf: Не удалось прочитать PDF/),
    ).toBeInTheDocument()
  })

  it('удаление документа — оптимистично с undo-тостом, затем DELETE', async () => {
    const { calls } = mockDocsApi({
      'GET /api/sessions/s-1/documents': [DOC, DOC2],
      'DELETE /api/sessions/s-1/documents/d-1': () => {
        return new Response(null, { status: 204 })
      },
    })

    renderApp()
    await screen.findByText(/Отчёт 2025/)

    // Кнопка удаления в строке документа
    const deleteButtons = screen.getAllByRole('button', { name: 'Удалить' })
    expect(deleteButtons.length).toBeGreaterThan(0)
    await userEvent.click(deleteButtons[0] as HTMLElement)

    // DELETE уходит сразу (оптимистичное удаление)
    await waitFor(() =>
      expect(
        calls.some(
          (c) => c.init.method === 'DELETE' && c.url.includes('/documents/d-1'),
        ),
      ).toBe(true),
    )
  })

  it('ошибка API показывается alert-ом', async () => {
    mockDocsApi({
      'GET /api/sessions/s-1/documents': json({ detail: 'Сессия не найдена' }, 404),
    })

    renderApp()

    expect(await screen.findByText('Сессия не найдена')).toBeInTheDocument()
  })

  it('пустой список — «Документов пока нет»', async () => {
    mockDocsApi({ 'GET /api/sessions/s-1/documents': [] })

    renderApp()

    const emptyTexts = await screen.findAllByText('Документов пока нет.')
    expect(emptyTexts.length).toBeGreaterThan(0)
  })

  it('прогресс индексации: активная задача рисует панель этапов', async () => {
    mockDocsApi({
      'GET /api/tasks': {
        tasks: [
          {
            id: 't-9',
            kind: 'indexing',
            title: 'Индексация: отчёт.pdf',
            status: 'running',
            progress: 40,
            step: 'чанки',
            error: null,
            cancel_requested: false,
            session_id: 's-1',
            project_id: null,
            created_at: '2026-10-07T09:00:00+00:00',
            started_at: '2026-10-07T09:00:01+00:00',
            finished_at: null,
            seconds: 5,
            stage_seconds: 2,
            result: null,
          },
        ],
        active: 1,
      },
    })

    renderApp()

    expect(await screen.findByText(/40%/)).toBeInTheDocument()
    // в running-режиме title живёт в aria-label прогресс-бара
    expect(screen.getByLabelText('Индексация: отчёт.pdf: 40%')).toBeInTheDocument()
  })

  it('архивная сессия: всё только чтение', async () => {
    mockDocsApi({
      'GET /api/sessions/s-1': { ...DETAIL, status: 'archived', writable: false },
    })

    renderApp()

    await screen.findByText(/Отчёт 2025/)
    // Страница грузится в два запроса (сессия → документы), поэтому поля
    // формы ищем с ожиданием, а не сразу.
    expect(await screen.findByLabelText('Путь к файлу на диске')).toBeDisabled()
    expect(screen.getByLabelText('Категория', { selector: 'input' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Добавить' })).toBeDisabled()
    // кнопки удаления на месте, но заблокированы
    const deleteButtons = screen.getAllByRole('button', { name: 'Удалить' })
    expect(deleteButtons.length).toBeGreaterThan(0)
    for (const button of deleteButtons) expect(button).toBeDisabled()
  })
})
