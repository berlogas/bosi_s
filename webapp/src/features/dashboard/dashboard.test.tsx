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
import { json, loginAs, mockApi, resetAuth, TEST_ADMIN } from '../../test/helpers'

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

  it('исследователю группы владельцев не показываются', async () => {
    loginAs()
    mockApi({
      'GET /api/sessions': [SESSION],
      'GET /api/health': HEALTH,
      'GET /api/tasks': { tasks: [], active: 0 },
    })

    renderApp()
    expect(await screen.findByText('Баренцево море')).toBeInTheDocument()
    expect(screen.queryByText(/^Иванов Иван \(ivanov\)/)).not.toBeInTheDocument()
    expect(screen.queryByText(/^Сессии всех пользователей/)).not.toBeInTheDocument()
  })
})

describe('дашборд администратора: группировка по владельцу', () => {
  const OWN_SESSIONS = [
    {
      ...SESSION,
      user_id: 'u-admin',
      owner_username: 'admin',
      owner_full_name: 'Админов Админ',
    },
  ]
  const FOREIGN = [
    {
      ...SESSION,
      id: 's-9',
      title: 'Сессия Иванова',
      owner_username: 'ivanov',
      owner_full_name: 'Иванов Иван',
    },
    {
      ...SESSION,
      id: 's-10',
      title: 'Сессия Петрова',
      owner_username: 'petrov',
      owner_full_name: null,
    },
    {
      ...SESSION,
      id: 's-11',
      title: 'Вторая сессия Иванова',
      owner_username: 'ivanov',
      owner_full_name: 'Иванов Иван',
    },
  ]

  function adminMocks(sessions: unknown[]) {
    return {
      'GET /api/sessions': sessions,
      'GET /api/health': HEALTH,
      'GET /api/tasks': { tasks: [], active: 0 },
    }
  }

  it('раскладывает чужие сессии по владельцам, свои — первыми', async () => {
    loginAs(TEST_ADMIN)
    mockApi(adminMocks([...FOREIGN, ...OWN_SESSIONS]))

    renderApp()

    expect(await screen.findByText('Сессии всех пользователей (4)')).toBeInTheDocument()
    // ФИО с логином, без ФИО — только логин, свои группы первыми
    const headers = screen
      .getAllByText(/^.*\(\d\)$/)
      .map((node) => node.textContent)
      .filter((text) => text !== 'Сессии всех пользователей (4)')
    expect(headers).toEqual([
      'Админов Админ (admin) (1)',
      'Иванов Иван (ivanov) (2)',
      'petrov (1)',
    ])

    const cards = screen.getAllByTestId('session-card')
    expect(cards).toHaveLength(4)
    // обе сессии Иванова в одной группе
    const ivanovGroup = screen.getByText('Иванов Иван (ivanov) (2)')
      .parentElement as HTMLElement
    expect(within(ivanovGroup).getByText('Сессия Иванова')).toBeInTheDocument()
    expect(within(ivanovGroup).getByText('Вторая сессия Иванова')).toBeInTheDocument()
    expect(within(ivanovGroup).queryByText('Сессия Петрова')).not.toBeInTheDocument()
  })

  it('на паузе и в архиве тоже сгруппированы', async () => {
    loginAs(TEST_ADMIN)
    mockApi(
      adminMocks([
        ...FOREIGN.slice(0, 1),
        { ...FOREIGN[1], status: 'paused' },
        { ...FOREIGN[2], status: 'archived', archived_at: '2026-10-01T09:00:00+00:00' },
      ]),
    )

    renderApp()

    expect(await screen.findByText('На паузе (1)')).toBeInTheDocument()
    expect(screen.getByText('Архив (1) — только чтение')).toBeInTheDocument()
    expect(screen.getAllByText('petrov (1)')).toHaveLength(1)
  })

  it('админу пустой список не выглядит как «нет своих сессий»', async () => {
    loginAs(TEST_ADMIN)
    mockApi(adminMocks([]))

    renderApp()
    expect(await screen.findByText('Сессий нет — создайте первую.')).toBeInTheDocument()
  })
})

describe('дашборд: кнопка «Продолжить» открывает рабочую страницу', () => {
  it('клик по «Продолжить» показывает страницу сессии с вкладками', async () => {
    loginAs()
    const detail = {
      ...SESSION,
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
    }
    mockApi({
      'GET /api/sessions': [SESSION],
      'GET /api/sessions/s-1': detail,
      'GET /api/sessions/s-1/messages': { messages: [], total: 0 },
      'GET /api/health': HEALTH,
      'GET /api/tasks': { tasks: [], active: 0 },
      'PUT /api/sessions/s-1/state': detail,
    })

    renderApp()

    await userEvent.click(await screen.findByRole('button', { name: 'Продолжить' }))

    expect(
      await screen.findByRole('heading', { name: 'Баренцево море' }),
    ).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'Чат' })).toBeInTheDocument()
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
  /** Задача быстрого вопроса: kind=chat, сессии нет — работа по глобальной базе. */
  const quickTask = (patch: Record<string, unknown> = {}) => ({
    id: 'q-1',
    kind: 'chat',
    title: 'Быстрый вопрос: что такое GF/F',
    status: 'running',
    progress: 55,
    step: 'генерация ответа (LLM)',
    error: null,
    cancel_requested: false,
    user_id: 'u-1',
    session_id: null,
    project_id: null,
    created_at: '2026-10-07T09:00:00+00:00',
    started_at: '2026-10-07T09:00:01+00:00',
    finished_at: null,
    seconds: 42.5,
    stage_seconds: 3.2,
    result: null,
    ...patch,
  })

  const ANSWER = {
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
        relevance: 0.87,
      },
    ],
    references: ['📚 [1] Данные GF/F (глобальная база)'],
    query: 'что такое GF/F',
    from_cache: false,
    base_empty: false,
  }

  /** Пустая история, пока задача не дописала обмен. */
  const quickHistory = (messages: unknown[] = []) => ({
    messages,
    total: messages.length,
  })

  it('вопрос → панель этапов с отменой → ответ с источниками и подсказками', async () => {
    loginAs()
    // первый опрос задачи — «считаем», второй — «готово»: так видно и панель
    // этапов, и ответ из Task.result
    let polls = 0
    const { calls } = mockApi({
      'GET /api/sessions': [],
      'GET /api/health': HEALTH,
      'GET /api/tasks': { tasks: [], active: 0 },
      'GET /api/chat/quick-history': () => {
        // история пополняется только после завершения задачи
        if (polls < 2) return json(quickHistory())
        return json(
          quickHistory([
            {
              id: 'm-1',
              session_id: null,
              role: 'user',
              content: 'что такое GF/F',
              sources: [],
              checks: {},
              duration_seconds: null,
              created_at: '2026-10-07T09:00:00+00:00',
            },
            {
              id: 'm-2',
              session_id: null,
              role: 'assistant',
              content: ANSWER.answer,
              sources: ANSWER.sources,
              checks: { citations: { ok: true } },
              duration_seconds: 42.5,
              created_at: '2026-10-07T09:00:42+00:00',
            },
          ]),
        )
      },
      // маршрут отвечает мгновенно: считает фон, а не этот запрос
      'POST /api/chat/quick-query': { task_id: 'q-1' },
      'GET /api/tasks/q-1': () => {
        polls += 1
        if (polls === 1) return json(quickTask())
        return json(
          quickTask({ status: 'done', progress: 100, step: null, result: ANSWER }),
        )
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

    // вопрос ушёл фоном: вместо спиннера — этапы с процентами и отменой
    expect(await screen.findByText(/55%/)).toBeInTheDocument()
    expect(screen.getByText(/генерация ответа/)).toBeInTheDocument()
    expect(screen.getByText(/всего 42с/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Отменить' })).toBeInTheDocument()
    expect(calls.some((call) => call.url.includes('/api/tasks/q-1'))).toBe(true)

    // ответ из Task.result, затем перечитывание истории — без дублей.
    // Смена статуса приходит со следующим опросом задачи (2 с), поэтому
    // ждём с запасом, как в тестах чата сессии.
    await waitFor(
      () => expect(screen.getByText(/Ответ по GF\/F/)).toBeInTheDocument(),
      { timeout: 5000 },
    )
    await waitFor(() => expect(screen.getAllByText('что такое GF/F')).toHaveLength(1))
    expect(screen.queryByRole('button', { name: 'Отменить' })).toBeNull()

    // В UI показывается релевантность («релевантность 87%»), а не взвешенный
    // score ранжирования: у глобального источника score = relevance × 0.4,
    // и эти числа не совпадают.
    expect(screen.getAllByText(/Данные GF\/F/).length).toBeGreaterThan(0)
    expect(screen.getByText(/релевантность 87%/)).toBeInTheDocument()
    expect(screen.queryByText(/score /)).not.toBeInTheDocument()

    // подсказки уточнений (до 4)
    expect(
      await screen.findByText('Можно уточнить:', {}, { timeout: 5000 }),
    ).toBeInTheDocument()
    expect(screen.getByText('— как считать биомассу')).toBeInTheDocument()
  }, 15_000)

  it('отмена задачи убирает ожидание и говорит, что вопрос отменён', async () => {
    loginAs()
    let cancelled = false
    const { calls } = mockApi({
      'GET /api/sessions': [],
      'GET /api/health': HEALTH,
      'GET /api/tasks': { tasks: [], active: 0 },
      'GET /api/chat/quick-history': quickHistory(),
      'POST /api/chat/quick-query': { task_id: 'q-1' },
      'GET /api/tasks/q-1': () =>
        json(
          quickTask(
            cancelled ? { status: 'cancelled', step: 'отменено пользователем' } : {},
          ),
        ),
      'POST /api/tasks/q-1/cancel': () => {
        cancelled = true
        return json({ cancelled: true, task: quickTask({ cancel_requested: true }) })
      },
    })

    renderApp()

    await userEvent.type(
      await screen.findByLabelText('Быстрый вопрос'),
      'тяжёлый вопрос',
    )
    await userEvent.click(screen.getByRole('button', { name: 'Спросить' }))

    await userEvent.click(await screen.findByRole('button', { name: 'Отменить' }))

    expect(calls.some((call) => call.url.includes('/api/tasks/q-1/cancel'))).toBe(true)
    // отмена приходит со следующим опросом задачи
    await waitFor(
      () => expect(screen.getByText('Вопрос отменён')).toBeInTheDocument(),
      { timeout: 5000 },
    )
    expect(screen.queryByRole('button', { name: 'Отменить' })).toBeNull()
    // ввод снова живой — можно спросить заново
    expect(screen.getByLabelText('Быстрый вопрос')).not.toBeDisabled()
  }, 15_000)

  it('ошибка задачи показывает вопрос с ошибкой, а не молчание', async () => {
    loginAs()
    mockApi({
      'GET /api/sessions': [],
      'GET /api/health': HEALTH,
      'GET /api/tasks': { tasks: [], active: 0 },
      'GET /api/chat/quick-history': quickHistory(),
      'POST /api/chat/quick-query': { task_id: 'q-1' },
      'GET /api/tasks/q-1': quickTask({
        status: 'error',
        error: 'RuntimeError: Ollama недоступен',
      }),
    })

    renderApp()

    await userEvent.type(await screen.findByLabelText('Быстрый вопрос'), 'привет')
    await userEvent.click(screen.getByRole('button', { name: 'Спросить' }))

    expect(
      await screen.findByText(/Ollama недоступен/, {}, { timeout: 5000 }),
    ).toBeInTheDocument()
    // ввод не заблокирован — можно повторить
    expect(screen.getByLabelText('Быстрый вопрос')).not.toBeDisabled()
  })

  it('ошибка отправки видна сразу, до всякой задачи', async () => {
    loginAs()
    mockApi({
      'GET /api/sessions': [],
      'GET /api/health': HEALTH,
      'GET /api/tasks': { tasks: [], active: 0 },
      'GET /api/chat/quick-history': quickHistory(),
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
    expect(screen.getByLabelText('Быстрый вопрос')).not.toBeDisabled()
  })

  it('переписка поднимается с сервера: перезагрузка страницы её не стирает', async () => {
    loginAs()
    const { calls } = mockApi({
      'GET /api/sessions': [],
      'GET /api/health': HEALTH,
      'GET /api/tasks': { tasks: [], active: 0 },
      'GET /api/chat/quick-history': quickHistory([
        {
          id: 'm-9',
          session_id: null,
          role: 'user',
          content: 'прошлый вопрос',
          sources: [],
          checks: {},
          duration_seconds: null,
          created_at: '2026-10-06T09:00:00+00:00',
        },
        {
          id: 'm-10',
          session_id: null,
          role: 'assistant',
          content: 'прошлый ответ [1]',
          sources: ANSWER.sources,
          checks: {},
          duration_seconds: 12.5,
          created_at: '2026-10-06T09:00:12+00:00',
        },
      ]),
    })

    renderApp()

    expect(await screen.findByText('прошлый вопрос')).toBeInTheDocument()
    // метка цитаты [1] рисуется отдельной кнопкой, поэтому ищем по началу фразы
    expect(screen.getByText(/прошлый ответ/)).toBeInTheDocument()
    expect(screen.getAllByText(/Данные GF\/F/).length).toBeGreaterThan(0)
    // без нового вопроса сеть не дёргается
    expect(findPost(calls, '/api/chat/quick-query')).toBeUndefined()
  })

  it('Enter отправляет вопрос, Shift+Enter — новая строка', async () => {
    loginAs()
    const { calls } = mockApi({
      'GET /api/sessions': [],
      'GET /api/health': HEALTH,
      'GET /api/tasks': { tasks: [], active: 0 },
      'GET /api/chat/quick-history': quickHistory(),
      'POST /api/chat/quick-query': { task_id: 'q-1' },
      'GET /api/tasks/q-1': quickTask({
        status: 'done',
        progress: 100,
        step: null,
        result: {
          ...ANSWER,
          answer: 'Ок',
          sources: [],
          references: [],
          base_empty: true,
        },
      }),
    })

    renderApp()
    const area = await screen.findByLabelText('Быстрый вопрос')

    // Shift+Enter — перенос строки, отправки нет
    await userEvent.type(area, 'строка{Shift>}{Enter}{/Shift}')
    expect(findPost(calls, '/api/chat/quick-query')).toBeUndefined()
    expect(area).toHaveValue('строка\n')

    // Enter — отправка (паритет st.chat_input)
    await userEvent.type(area, '{Enter}')
    await waitFor(() => expect(screen.getByText('Ок')).toBeInTheDocument(), {
      timeout: 5000,
    })
    expect(findPost(calls, '/api/chat/quick-query')).toBeDefined()
  }, 15_000)

  it('«Очистить чат» убирает переписку в два шага', async () => {
    loginAs()
    const { calls } = mockApi({
      'GET /api/sessions': [],
      'GET /api/health': HEALTH,
      'GET /api/tasks': { tasks: [], active: 0 },
      'GET /api/chat/quick-history': quickHistory([
        {
          id: 'm-9',
          session_id: null,
          role: 'user',
          content: 'прошлый вопрос',
          sources: [],
          checks: {},
          duration_seconds: null,
          created_at: '2026-10-06T09:00:00+00:00',
        },
      ]),
      'DELETE /api/chat/quick-history': json({}),
    })

    renderApp()

    await userEvent.click(
      await screen.findByRole('button', { name: /Очистить чат/ }),
    )
    expect(
      await screen.findByText(
        'Удалить всю историю быстрых вопросов? Отменить будет нельзя.',
      ),
    ).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Да, очистить' }))

    await waitFor(() => {
      const call = calls.find(
        (c) =>
          c.url.includes('/api/chat/quick-history') &&
          (c.init.method ?? 'GET').toUpperCase() === 'DELETE',
      )
      expect(call).toBeDefined()
    })
    // подтверждение закрылось после успеха — модалка уходит с транзишеном
    await waitFor(() => {
      expect(
        screen.queryByText(
          'Удалить всю историю быстрых вопросов? Отменить будет нельзя.',
        ),
      ).toBeNull()
    })
  })

  it('при пустой истории кнопки «Очистить чат» нет', async () => {
    loginAs()
    mockApi({
      'GET /api/sessions': [],
      'GET /api/health': HEALTH,
      'GET /api/tasks': { tasks: [], active: 0 },
      'GET /api/chat/quick-history': quickHistory(),
    })

    renderApp()

    expect(
      await screen.findByText(
        'Спросите что-нибудь по базе знаний — ответ появится здесь.',
      ),
    ).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Очистить чат/ })).toBeNull()
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
