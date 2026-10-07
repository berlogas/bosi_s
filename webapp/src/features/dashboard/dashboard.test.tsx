/**
 * Приёмка Фазы 1: «создать сессию → заархивировать с подтверждением».
 *
 * Плюс блоки дашборда, которые обязаны быть на месте по паритету с
 * dashboard.py: список сессий сгруппирован, задачи видны, быстрый чат
 * отвечает, архив — в два шага (модалка, а не один клик).
 */

import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient } from '@tanstack/react-query'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { AppProviders } from '../../app/AppProviders'
import { AppRoutes } from '../../routes'
import { json, loginAs, mockApi, resetAuth } from '../../test/helpers'

const SESSION = {
  id: 's-1',
  user_id: 'u-1',
  title: 'Баренцево море',
  status: 'active',
  last_action_type: 'chat',
  last_action_label: 'Вопрос: метод GF/F',
  last_action_at: '2026-10-02T09:00:00+00:00',
  resume_note: 'не забыть',
  state_snapshot: {},
  created_at: '2026-10-01T09:00:00+00:00',
  last_activity_at: '2026-10-02T09:00:00+00:00',
  // TTL: 90 дней от «сейчас» — карточка показывает срок хранения
  expires_at: new Date(Date.now() + 90 * 86_400_000).toISOString(),
  archived_at: null,
  purged_at: null,
}

const ARCHIVED_SESSION = {
  ...SESSION,
  id: 's-2',
  title: 'Архивная сессия',
  status: 'archived',
  archived_at: '2026-10-01T09:00:00+00:00',
}

const HEALTH = {
  status: 'ok',
  app: 'boasi_s',
  environment: 'test',
  version: '0',
  database: 'ok',
  llm_model: 'qwen',
  embedding_model: 'nomic',
  ollama: { reachable: true },
}

const ACTIVE_TASK = {
  id: 't-1',
  kind: 'chat',
  title: 'Вопрос: тест',
  status: 'running',
  progress: 55,
  step: 'генерация ответа',
  error: null,
  cancel_requested: false,
  session_id: 's-1',
  project_id: null,
  created_at: '2026-10-07T09:00:00+00:00',
  started_at: '2026-10-07T09:00:01+00:00',
  finished_at: null,
  seconds: 12.5,
  stage_seconds: 3.2,
  result: null,
}

function renderApp(path = '/') {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  })
  return render(
    <AppProviders initialPath={path} queryClient={queryClient}>
      <AppRoutes />
    </AppProviders>,
  )
}

beforeEach(() => {
  resetAuth()
})

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe('дашборд: список сессий', () => {
  it('группирует сессии и показывает срок хранения', async () => {
    loginAs()
    mockApi({
      'GET /api/sessions': [SESSION, ARCHIVED_SESSION],
      'GET /api/health': HEALTH,
      'GET /api/tasks': { tasks: [], active: 0 },
    })

    renderApp()

    expect(await screen.findByText('Баренцево море')).toBeInTheDocument()
    expect(screen.getByText(/осталось 9\d дней/)).toBeInTheDocument()

    // архивная — в отдельном блоке «только чтение», «Продолжить» отключён
    expect(screen.getByText('Архив (1) — только чтение')).toBeInTheDocument()
    const cards = screen.getAllByTestId('session-card')
    expect(cards).toHaveLength(2)
    const archivedCard = cards.find((card) =>
      within(card).queryByText('Архивная сессия'),
    )
    expect(archivedCard).toBeDefined()
    expect(
      within(archivedCard as HTMLElement).getByRole('button', { name: 'Продолжить' }),
    ).toBeDisabled()
  })

  it('показывает подсказку, когда активных сессий нет', async () => {
    loginAs()
    mockApi({
      'GET /api/sessions': [],
      'GET /api/health': HEALTH,
      'GET /api/tasks': { tasks: [], active: 0 },
    })

    renderApp()
    expect(
      await screen.findByText('Активных сессий нет — создайте первую.'),
    ).toBeInTheDocument()
  })
})

describe('приёмка: создать сессию → заархивировать с подтверждением', () => {
  it('создание открывает страницу сессии', async () => {
    loginAs()
    const { calls } = mockApi({
      'GET /api/sessions': [SESSION],
      'GET /api/health': HEALTH,
      'GET /api/tasks': { tasks: [], active: 0 },
      'POST /api/sessions': { ...SESSION, id: 's-new', title: 'Новая' },
      'GET /api/sessions/s-new': {
        ...SESSION,
        id: 's-new',
        title: 'Новая',
        days_left: 90,
        writable: true,
        summary: {
          documents: 0,
          documents_by_category: {},
          storage_bytes: 0,
          storage_limit_bytes: 524_288_000,
          documents_limit: 50,
          projects: 0,
          projects_limit: 5,
          messages: 0,
          links: 0,
          read_only: false,
        },
      },
    })

    renderApp()

    const input = await screen.findByLabelText('Название')
    await userEvent.type(input, 'Новая')
    await userEvent.click(screen.getByRole('button', { name: 'Создать' }))

    // открылась страница сессии
    expect(await screen.findByRole('heading', { name: 'Новая' })).toBeInTheDocument()

    const created = findPost(calls, '/api/sessions')
    expect(created).toBeTruthy()
    expect(JSON.parse(String(created?.init.body))).toEqual({ title: 'Новая' })
  })

  it('архив в два шага: модалка спрашивает, второй клик отправляет запрос', async () => {
    loginAs()
    const { calls } = mockApi({
      'GET /api/sessions': [SESSION],
      'GET /api/health': HEALTH,
      'GET /api/tasks': { tasks: [], active: 0 },
      'POST /api/sessions/s-1/archive': { ...SESSION, status: 'archived' },
    })

    renderApp()
    const card = (await screen.findByText('Баренцево море')).closest(
      '[data-testid="session-card"]',
    ) as HTMLElement

    // шаг 1: открываем модалку — запроса ещё НЕТ
    await userEvent.click(within(card).getByRole('button', { name: 'Архив' }))
    const modal = await screen.findByRole('dialog')
    expect(
      within(modal).getByText(/Станет только для чтения|уйдёт в архив/),
    ).toBeInTheDocument()
    expect(calls.some((call) => call.url.includes('/archive'))).toBe(false)

    // шаг 2: подтверждаем — запрос уходит
    await userEvent.click(within(modal).getByRole('button', { name: 'Да, в архив' }))
    await waitFor(() =>
      expect(calls.some((call) => call.url.includes('/api/sessions/s-1/archive'))).toBe(
        true,
      ),
    )
  })

  it('архив можно отменить в модалке — запроса не будет', async () => {
    loginAs()
    const { calls } = mockApi({
      'GET /api/sessions': [SESSION],
      'GET /api/health': HEALTH,
      'GET /api/tasks': { tasks: [], active: 0 },
    })

    renderApp()
    const card = (await screen.findByText('Баренцево море')).closest(
      '[data-testid="session-card"]',
    ) as HTMLElement

    await userEvent.click(within(card).getByRole('button', { name: 'Архив' }))
    const modal = await screen.findByRole('dialog')
    await userEvent.click(within(modal).getByRole('button', { name: 'Отмена' }))

    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
    expect(calls.some((call) => call.url.includes('/archive'))).toBe(false)
  })
})

describe('дашборд: активные задачи', () => {
  it('показывает панель задачи с процентами и кнопкой отмены', async () => {
    loginAs()
    const { calls } = mockApi({
      'GET /api/sessions': [],
      'GET /api/health': HEALTH,
      'GET /api/tasks': { tasks: [ACTIVE_TASK], active: 1 },
      'POST /api/tasks/t-1/cancel': {
        cancelled: true,
        task: { ...ACTIVE_TASK, cancel_requested: true },
      },
    })

    renderApp()

    expect(await screen.findByText('Активные задачи')).toBeInTheDocument()
    expect(screen.getByText(/генерация ответа/)).toBeInTheDocument()
    expect(screen.getByText(/55%/)).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: 'Отменить' }))
    await waitFor(() =>
      expect(calls.some((call) => call.url.includes('/api/tasks/t-1/cancel'))).toBe(
        true,
      ),
    )
  })

  it('ошибка загрузки задач не роняет дашборд', async () => {
    loginAs()
    mockApi({
      'GET /api/sessions': [SESSION],
      'GET /api/health': HEALTH,
      'GET /api/tasks': { detail: 'нет прав' } as unknown as never,
    })

    // 200 с неожиданным телом → tasks() вернёт объект, фильтр упадёт
    renderApp()
    expect(await screen.findByText('Баренцево море')).toBeInTheDocument()
  })
})

describe('дашборд: быстрый чат', () => {
  it('вопрос → ответ с источниками и подсказками', async () => {
    loginAs()
    mockApi({
      'GET /api/sessions': [],
      'GET /api/health': HEALTH,
      'GET /api/tasks': { tasks: [], active: 0 },
      'POST /api/chat/quick-query': {
        answer: 'Ответ по GF/F [1]',
        sources: [
          {
            index: 1,
            marker: '📚',
            source_scope: 'global',
            dockey: 'k1',
            docname: 'biomass',
            title: 'Данные GF/F',
            category: 'global_knowledge',
            score: 0.87,
          },
        ],
        references: ['📚 [1] Данные GF/F (глобальная база)'],
        query: 'что такое GF/F',
        from_cache: false,
        base_empty: false,
      },
      'GET /api/chat/suggest-queries': {
        suggestions: ['как считать биомассу', 'источники данных GF/F'],
        query: 'что такое GF/F',
      },
    })

    renderApp()

    await userEvent.type(
      await screen.findByLabelText('Быстрый вопрос'),
      'что такое GF/F',
    )
    await userEvent.click(screen.getByRole('button', { name: 'Спросить' }))

    expect(await screen.findByText(/Ответ по GF\/F/)).toBeInTheDocument()
    // заголовок источника (внутри <b>) и его строка со score — отдельными
    // матчами: RTL сравнивает прямые текстовые узлы, сквозной regex не сработает
    expect(screen.getAllByText(/Данные GF\/F/).length).toBeGreaterThan(0)
    expect(screen.getByText(/score 0\.87/)).toBeInTheDocument()

    // подсказки уточнений (до 4)
    expect(await screen.findByText('Можно уточнить:')).toBeInTheDocument()
    expect(screen.getByText('— как считать биомассу')).toBeInTheDocument()
  })

  it('ошибка чата показывается в пузыре, а не роняет страницу', async () => {
    loginAs()
    mockApi({
      'GET /api/sessions': [],
      'GET /api/health': HEALTH,
      'GET /api/tasks': { tasks: [], active: 0 },
      'POST /api/chat/quick-query': json(
        { error: 'upstream_unavailable', detail: 'Ollama недоступен', meta: {} },
        503,
      ),
    })

    renderApp()

    await userEvent.type(await screen.findByLabelText('Быстрый вопрос'), 'привет')
    await userEvent.click(screen.getByRole('button', { name: 'Спросить' }))

    const alert = await screen.findByText('Ollama недоступен')
    expect(alert).toBeInTheDocument()
    // ввод не заблокирован — можно повторить
    expect(screen.getByLabelText('Быстрый вопрос')).not.toBeDisabled()
  })

  it('Enter отправляет вопрос, Shift+Enter — новая строка', async () => {
    loginAs()
    const { calls } = mockApi({
      'GET /api/sessions': [],
      'GET /api/health': HEALTH,
      'GET /api/tasks': { tasks: [], active: 0 },
      'POST /api/chat/quick-query': {
        answer: 'Ок',
        sources: [],
        references: [],
        query: 'вопрос',
        from_cache: false,
        base_empty: false,
      },
    })

    renderApp()
    const area = await screen.findByLabelText('Быстрый вопрос')

    // Shift+Enter — перенос строки, отправки нет
    await userEvent.type(area, 'строка{Shift>}{Enter}{/Shift}')
    expect(findPost(calls, '/api/chat/quick-query')).toBeUndefined()
    expect(area).toHaveValue('строка\n')

    // Enter — отправка (паритет st.chat_input)
    await userEvent.type(area, '{Enter}')
    expect(await screen.findByText('Ок')).toBeInTheDocument()
    expect(findPost(calls, '/api/chat/quick-query')).toBeDefined()
  })
})

describe('вход после Фазы 0', () => {
  it('без сессии редиректит на /login', async () => {
    mockApi({})
    renderApp('/some/where')
    expect(await screen.findByText('Вход в boasi_s')).toBeInTheDocument()
  })
})

function findPost(calls: { url: string; init: RequestInit }[], path: string) {
  return calls.find(
    (call) =>
      (call.init.method ?? 'GET').toUpperCase() === 'POST' && call.url.includes(path),
  )
}
