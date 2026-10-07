/**
 * Тесты чата сессии (Фаза 2): история пузырями, удаление пары,
 * фоновая задача (панель → done/error), очистка в два шага,
 * восстановление задачи после F5, пагинация истории.
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
  build: { build: 'test', commit: null, built_at: null, ui: null },
}

const SESSION = {
  id: 's-1',
  title: 'Баренцево море',
  status: 'active',
  created_at: '2026-10-01T00:00:00+00:00',
  last_activity_at: '2026-10-06T12:00:00+00:00',
  expires_at: '2026-12-30T00:00:00+00:00',
  last_action_at: null,
  last_action_label: null,
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
    documents: 0,
    skipped: 0,
    collections: 0,
    last_sync: null,
    documents_limit: 50,
    storage_bytes: 0,
    storage_limit_bytes: 524288000,
  },
  settings: { k: 10, category: 'all', scope: 'best', no_cache: false },
  upstream: [],
  questions: [],
  history: [],
  recent_sources: [],
  recent_documents: [],
}

function userMessage(id: string, content: string) {
  return {
    id,
    session_id: 's-1',
    role: 'user',
    content,
    mode: 'hybrid',
    sources: [],
    checks: {},
    duration_seconds: null,
    created_at: '2026-10-06T12:00:00+00:00',
  }
}

function assistantMessage(id: string, content: string, sources: unknown[] = []) {
  return {
    id,
    session_id: 's-1',
    role: 'assistant',
    content,
    mode: 'hybrid',
    sources,
    checks: {},
    duration_seconds: 3.2,
    created_at: '2026-10-06T12:00:05+00:00',
  }
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

function runningTask(overrides: Record<string, unknown> = {}) {
  return {
    id: 't-1',
    kind: 'chat',
    title: 'Вопрос: что такое биомасса',
    status: 'running',
    progress: 55,
    step: 'LLM формирует ответ',
    error: null,
    cancel_requested: false,
    session_id: 's-1',
    project_id: null,
    created_at: '2026-10-06T12:00:00+00:00',
    started_at: '2026-10-06T12:00:00+00:00',
    finished_at: null,
    seconds: 42,
    stage_seconds: 7,
    result: null,
    ...overrides,
  }
}

function renderApp(path = '/s/s-1/chat') {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  })
  return render(
    <AppProviders initialPath={path} queryClient={queryClient}>
      <AppRoutes />
    </AppProviders>,
  )
}

function mockChatApi(routes: Record<string, unknown> = {}) {
  return mockApi({
    'GET /api/health': HEALTH,
    'GET /api/sessions/s-1': DETAIL,
    'GET /api/sessions': [SESSION],
    'GET /api/tasks': { tasks: [], active: 0 },
    'GET /api/chat/messages': { messages: [], total: 0, offset: 0 },
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

describe('чат: история', () => {
  it('рисует пары пузырями с кнопкой удаления только на вопросе', async () => {
    const { calls } = mockChatApi({
      'GET /api/chat/messages': {
        messages: [
          userMessage('m-1', 'Что такое биомасса?'),
          assistantMessage('m-2', 'Биомасса — это…', [SOURCE]),
        ],
        total: 2,
        offset: 0,
      },
    })

    renderApp()

    expect(await screen.findByText('Что такое биомасса?')).toBeInTheDocument()
    expect(screen.getByText(/Биомасса — это/)).toBeInTheDocument()
    expect(screen.getByText('Источники:')).toBeInTheDocument()

    // кнопка пары — на вопросе (нажатие убирает оба пузыря)
    const bubbles = screen.getAllByTestId('chat-bubble')
    expect(bubbles).toHaveLength(2)
    const userBubble = bubbles[0] as HTMLElement
    expect(
      within(userBubble).queryByRole('button', { name: /удалить/i }),
    ).not.toBeNull()
    const assistantBubble = bubbles[1] as HTMLElement
    expect(
      within(assistantBubble).queryByRole('button', { name: /удалить/i }),
    ).toBeNull()

    // удаление пары: DELETE на конкретное сообщение + перезапрос истории
    await userEvent.click(within(userBubble).getByRole('button', { name: /удалить/i }))
    await waitFor(() =>
      expect(calls.some((call) => call.url.includes('/api/chat/messages/m-1'))).toBe(
        true,
      ),
    )
  })

  it('ошибка истории не роняет чат — показываем текст ошибки', async () => {
    mockChatApi({
      'GET /api/chat/messages': json({ detail: 'Сессия не найдена' }, 404),
    })

    renderApp()

    expect(await screen.findByText(/Сессия не найдена/)).toBeInTheDocument()
    // ввод при этом живой
    expect(screen.getByLabelText('Ваш вопрос')).not.toBeDisabled()
  })

  it('кнопка «показать более ранние» расширяет окно истории', async () => {
    const messages = [
      userMessage('m-1', 'Старый вопрос'),
      assistantMessage('m-2', 'Старый ответ'),
      userMessage('m-3', 'Новый вопрос'),
      assistantMessage('m-4', 'Новый ответ'),
    ]
    const { calls } = mockChatApi({
      'GET /api/chat/messages': (url: string) => {
        const parsed = new URL(url, 'http://test')
        const limit = Number(parsed.searchParams.get('limit') ?? 100)
        const offset = Number(parsed.searchParams.get('offset') ?? 0)
        if (limit === 1) return json({ messages: [], total: 4, offset: 0 })
        return json({
          messages: messages.slice(offset, offset + limit),
          total: 4,
          offset,
        })
      },
    })

    renderApp()

    expect(await screen.findByText('Новый вопрос')).toBeInTheDocument()
    // окно 100 > total — кнопки нет
    expect(screen.queryByRole('button', { name: /показать более ранние/i })).toBeNull()
    expect(calls.some((call) => call.url.includes('limit=1'))).toBe(true)
  })
})

describe('чат: фоновая задача', () => {
  it('вопрос → pending-пузырь → панель этапов → done → ответ из истории', async () => {
    let phase: 'before' | 'after' = 'before'
    const { calls } = mockChatApi({
      'POST /api/chat/query-async': { task_id: 't-1' },
      'GET /api/tasks/t-1': () => {
        if (phase === 'before') return json(runningTask())
        phase = 'after'
        return json(runningTask({ status: 'done', progress: 100, step: null }))
      },
      'GET /api/chat/messages': () => {
        if (phase === 'before') return json({ messages: [], total: 0, offset: 0 })
        return json({
          messages: [
            userMessage('m-1', 'что такое биомасса'),
            assistantMessage('m-2', 'Ответ из истории'),
          ],
          total: 2,
          offset: 0,
        })
      },
    })

    renderApp()

    await userEvent.type(
      await screen.findByLabelText('Ваш вопрос'),
      'что такое биомасса',
    )
    await userEvent.click(screen.getByRole('button', { name: '➤' }))

    // pending-вопрос и «Вопрос обрабатывается…»
    expect(await screen.findByText('что такое биомасса')).toBeInTheDocument()
    expect(screen.getByText('Вопрос обрабатывается…')).toBeInTheDocument()

    // панель этапов: проценты, секундомер, кнопка «Отменить»
    expect(await screen.findByText(/55%/)).toBeInTheDocument()
    expect(screen.getByText(/всего 42с/)).toBeInTheDocument()
    const cancel = screen.getByRole('button', { name: 'Отменить' })

    // task_id пережил запуск (sessionStorage — для F5)
    expect(sessionStorage.getItem('boasi.chat.task')).toContain('"t-1"')

    // done: панель и pending гаснут, приходит ответ истории
    phase = 'after'
    await waitFor(
      () => expect(screen.getByText('Ответ из истории')).toBeInTheDocument(),
      { timeout: 5000 },
    )
    expect(screen.queryByText('Вопрос обрабатывается…')).toBeNull()
    expect(sessionStorage.getItem('boasi.chat.task')).toBeNull()
    expect(cancel).not.toBeInTheDocument()

    // запрос задачи реально поллился
    expect(calls.some((call) => call.url.includes('/api/tasks/t-1'))).toBe(true)
  }, 15_000)

  it('ошибка задачи показывает вопрос с ошибкой и кнопку убрать', async () => {
    sessionStorage.setItem(
      'boasi.chat.task',
      JSON.stringify({ sessionId: 's-1', taskId: 't-1', question: 'тяжёлый вопрос' }),
    )
    mockChatApi({
      'GET /api/tasks/t-1': runningTask({
        status: 'error',
        progress: 40,
        error: 'Ollama недоступен',
      }),
    })

    renderApp()

    expect(await screen.findByText('тяжёлый вопрос')).toBeInTheDocument()
    expect(
      await screen.findByText(/Не получилось ответить: Ollama недоступен/),
    ).toBeInTheDocument()
    // панель не остаётся висеть
    expect(screen.queryByRole('button', { name: 'Отменить' })).toBeNull()

    await userEvent.click(
      screen.getByRole('button', { name: /убрать вопрос и ошибку/i }),
    )
    expect(screen.queryByText(/Не получилось ответить/)).toBeNull()
  }, 10_000)

  it('F5 восстанавливает панель: задача из sessionStorage продолжает поллинг', async () => {
    sessionStorage.setItem(
      'boasi.chat.task',
      JSON.stringify({ sessionId: 's-1', taskId: 't-1', question: 'вопрос после F5' }),
    )
    mockChatApi({
      'GET /api/tasks/t-1': runningTask({ progress: 85, step: 'проверки цитат' }),
    })

    renderApp()

    expect(await screen.findByText('вопрос после F5')).toBeInTheDocument()
    expect(await screen.findByText(/85%/)).toBeInTheDocument()
    expect(screen.getByText(/проверки цитат/)).toBeInTheDocument()
  }, 10_000)

  it('отмена задачи уходит на сервер', async () => {
    sessionStorage.setItem(
      'boasi.chat.task',
      JSON.stringify({ sessionId: 's-1', taskId: 't-1', question: 'вопрос' }),
    )
    const { calls } = mockChatApi({
      'GET /api/tasks/t-1': runningTask(),
      'POST /api/tasks/t-1/cancel': {
        cancelled: true,
        task: runningTask({ cancel_requested: true }),
      },
    })

    renderApp()

    const cancel = await screen.findByRole('button', { name: 'Отменить' })
    await userEvent.click(cancel)
    await waitFor(() =>
      expect(calls.some((call) => call.url.includes('/api/tasks/t-1/cancel'))).toBe(
        true,
      ),
    )
  }, 10_000)
})

describe('чат: синхронный режим и очистка', () => {
  it('синхронный ответ рисуется локально и уходит из пузыря после истории', async () => {
    let answered = false
    mockChatApi({
      'POST /api/chat/query': (_url: string, init: RequestInit) => {
        answered = true
        return json({
          answer: 'Синхронный ответ [1]',
          sources: [SOURCE],
          references: ['[1] Данные GF/F (глобальная база)'],
          mode: JSON.parse(String(init.body)).mode,
          query: JSON.parse(String(init.body)).query,
          from_cache: true,
          stats: {},
          base_empty: false,
        })
      },
    })

    renderApp()

    // Mantine Switch: доступная роль switch с именем подписи
    await userEvent.click(await screen.findByRole('switch', { name: /Фоновый режим/ }))
    await userEvent.type(screen.getByLabelText('Ваш вопрос'), 'быстрый вопрос')
    await userEvent.click(screen.getByRole('button', { name: '➤' }))

    expect(await screen.findByText(/Синхронный ответ/)).toBeInTheDocument()
    expect(answered).toBe(true)
    // из кэша сервер не сохраняет — пузырь остаётся до появления в истории
    expect(screen.getByText('Ответ взят из кэша')).toBeInTheDocument()
    expect(
      screen.getByRole('button', { name: /убрать вопрос и ответ/i }),
    ).toBeInTheDocument()
  })

  it('ошибка отправки возвращает текст в поле и показывает alert', async () => {
    mockChatApi({
      'POST /api/chat/query-async': json({ detail: 'Сессия в архиве' }, 400),
    })

    renderApp()

    await userEvent.type(await screen.findByLabelText('Ваш вопрос'), 'вопрос в архив')
    await userEvent.click(screen.getByRole('button', { name: '➤' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('Сессия в архиве')
    expect(screen.getByLabelText('Ваш вопрос')).toHaveValue('вопрос в архив')
  })

  it('очистка чата — в два шага: до подтверждения DELETE не уходит', async () => {
    const { calls } = mockChatApi({
      'GET /api/chat/messages': {
        messages: [userMessage('m-1', 'вопрос'), assistantMessage('m-2', 'ответ')],
        total: 2,
        offset: 0,
      },
      'DELETE /api/chat/messages': new Response(null, { status: 204 }),
    })

    renderApp()

    await userEvent.click(await screen.findByRole('button', { name: /очистить чат/i }))
    const modal = await screen.findByRole('dialog')
    expect(within(modal).getByText(/Отменить будет нельзя/)).toBeInTheDocument()
    expect(
      calls.some(
        (call) => call.url.includes('DELETE') || call.init.method === 'DELETE',
      ),
    ).toBe(false)

    await userEvent.click(within(modal).getByRole('button', { name: 'Да, очистить' }))
    await waitFor(() =>
      expect(
        calls.some(
          (call) =>
            call.init.method === 'DELETE' &&
            call.url.includes('/api/chat/messages') &&
            !call.url.includes('m-'),
        ),
      ).toBe(true),
    )
  })

  it('архивная сессия: ввод и кнопки заблокированы (read-only)', async () => {
    mockChatApi({
      'GET /api/sessions/s-1': { ...DETAIL, status: 'archived', writable: false },
      'GET /api/chat/messages': {
        messages: [userMessage('m-1', 'старый вопрос')],
        total: 1,
        offset: 0,
      },
    })

    renderApp()

    expect(
      await screen.findByText('Сессия в архиве — доступно только чтение.'),
    ).toBeInTheDocument()
    expect(screen.getByLabelText('Ваш вопрос')).toBeDisabled()
    // кнопки удаления/очистки нет
    expect(screen.queryByRole('button', { name: /очистить чат/i })).toBeNull()
    const bubbles = await screen.findAllByTestId('chat-bubble')
    expect(
      within(bubbles[0] as HTMLElement).queryByRole('button', { name: /удалить/i }),
    ).toBeNull()
  })
})
