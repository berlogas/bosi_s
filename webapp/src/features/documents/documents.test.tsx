/**
 * Тесты вкладки «Документы» (Фаза 3): добавление по пути, drag&drop
 * с последующей загрузкой, группировка по категориям, удаление,
 * прогресс индексации, лимиты и read-only архива.
 */

import { render, screen, waitFor } from '@testing-library/react'
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
})

afterEach(() => {
  vi.unstubAllGlobals()
  resetAuth()
})

describe('вкладка Документы', () => {
  it('список сгруппирован по категориям, размер/чанки/теги на месте', async () => {
    mockDocsApi()

    renderApp()

    expect(await screen.findByText('Временная литература (1)')).toBeInTheDocument()
    expect(screen.getByText('Заметки (1)')).toBeInTheDocument()
    // содержимое панели accordeon раскрывается с transition — ждём
    expect(await screen.findByText(/Отчёт 2025 — 2 КБ, 7 чанков/)).toBeInTheDocument()
    expect(screen.getByText('теги: прилив, смок')).toBeInTheDocument()
    // dockey обрезан до 8 символов (как в documents_tab)
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
    await userEvent.type(
      screen.getByLabelText('Категория', { selector: 'input' }),
      'Данные',
    )
    await userEvent.type(
      screen.getByLabelText('Путь к файлу на диске'),
      '/data/file.pdf',
    )
    await userEvent.type(screen.getByLabelText('Теги через запятую'), 'a, b')
    await userEvent.click(screen.getByRole('button', { name: 'Добавить' }))

    await waitFor(() => {
      const call = calls.find((c) => c.url.includes('/documents/path'))
      expect(call).toBeDefined()
      const body = JSON.parse(String(call?.init.body))
      expect(body).toEqual({
        path: '/data/file.pdf',
        category: 'temp_literature',
        tags: ['a', 'b'],
      })
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

  it('dropzone копит файлы, «Загрузить файлы» уходит multipart-ом', async () => {
    const { calls } = mockDocsApi({
      'POST /api/sessions/s-1/documents/upload': {
        added: [DOC],
        duplicates: [],
        failed: [],
        total: 1,
      },
    })

    renderApp()
    await screen.findByText('Временная литература (1)')

    // drag&drop: React SyntheticEvent — dispatch через dataTransfer
    const dropzone = screen.getByTestId('doc-dropzone')
    const file = new File(['содержимое'], 'report.pdf', { type: 'application/pdf' })
    const dropEvent = new Event('drop', { bubbles: true, cancelable: true })
    Object.defineProperty(dropEvent, 'dataTransfer', {
      value: { files: [file] },
    })
    dropzone.dispatchEvent(dropEvent)

    expect(await screen.findByText(/Выбрано файлов: 1/)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Загрузить файлы' }))

    await waitFor(() => {
      const call = calls.find((c) => c.url.includes('/documents/upload'))
      expect(call).toBeDefined()
      expect(call?.init.method).toBe('POST')
    })
    // parитет: success-строка documents_tab
    expect(await screen.findByText('Добавлено: 1, ошибок: 0')).toBeInTheDocument()
  })

  it('удаление документа уходит DELETE и инвалидирует список', async () => {
    let deleted = false
    const { calls } = mockDocsApi({
      'GET /api/sessions/s-1/documents': () => json(deleted ? [DOC2] : [DOC, DOC2]),
      'DELETE /api/sessions/s-1/documents/d-1': () => {
        deleted = true
        return new Response(null, { status: 204 })
      },
    })

    renderApp()
    await screen.findByText(/Отчёт 2025/)

    // кнопка внутри раскрытой панели accordeon (transition — ждём роль)
    // панели открыты обе (defaultValue) — берём кнопку в группе документа
    const del = screen.getAllByRole('button', { name: 'Удалить' })[0]
    expect(del).toBeDefined()
    await userEvent.click(del as HTMLElement)

    await waitFor(() =>
      expect(
        calls.some(
          (c) => c.init.method === 'DELETE' && c.url.includes('/documents/d-1'),
        ),
      ).toBe(true),
    )
    expect(await screen.findByText(/Заметки полевые/)).toBeInTheDocument()
  })

  it('ошибка API показывается alert-ом', async () => {
    mockDocsApi({
      'GET /api/sessions/s-1/documents': json({ detail: 'Сессия не найдена' }, 404),
    })

    renderApp()

    expect(await screen.findByRole('alert')).toHaveTextContent('Сессия не найдена')
  })

  it('пустой список — «Документов пока нет»', async () => {
    mockDocsApi({ 'GET /api/sessions/s-1/documents': [] })

    renderApp()

    expect(await screen.findByText('Документов пока нет.')).toBeInTheDocument()
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
    expect(screen.getByLabelText('Путь к файлу на диске')).toBeDisabled()
    expect(screen.getByLabelText('Категория', { selector: 'input' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Добавить' })).toBeDisabled()
    // кнопки удаления на месте, но заблокированы (как disabled в Streamlit)
    const deleteButtons = screen.getAllByRole('button', { name: 'Удалить' })
    expect(deleteButtons.length).toBeGreaterThan(0)
    for (const button of deleteButtons) expect(button).toBeDisabled()
  })
})
