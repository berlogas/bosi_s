/**
 * Тесты админки (Фаза 4, паритет admin.py): guard роли, создание и
 * обновление пользователя, глобальная база (путь/файлы/массовая
 * индексация/переиндексация), задачи, таблицы сессий и аудита.
 */

import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient } from '@tanstack/react-query'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { AppProviders } from '../../app/AppProviders'
import { AppRoutes } from '../../routes'
import {
  json,
  loginAs,
  mockApi,
  resetAuth,
  TEST_ADMIN,
  TEST_USER,
} from '../../test/helpers'

const HEALTH = {
  status: 'ok',
  llm_model: 'test-model',
  embedding_model: 'test-embed',
  ollama: {},
}

const USERS = [
  {
    id: 'u-1',
    username: 'ivanov',
    role: 'researcher',
    full_name: 'Иванов И.И.',
    is_active: true,
    email: null,
    last_login_at: null,
  },
  {
    id: 'u-2',
    username: 'petrov',
    role: 'admin',
    full_name: null,
    is_active: true,
    email: null,
    last_login_at: null,
  },
]

const AUDIT = [
  {
    id: 'a-1',
    actor_user_id: 'u-1',
    actor_username: 'ivanov',
    action: 'session.create',
    target_type: 'session',
    target_id: 's-1',
    ip: '127.0.0.1',
    user_agent: null,
    ok: true,
    meta: null,
    created_at: '2026-10-07T10:00:00+00:00',
  },
  {
    id: 'a-2',
    actor_user_id: 'u-2',
    actor_username: 'admin',
    action: 'admin.user.create',
    target_type: 'user',
    target_id: 'u-3',
    ip: '127.0.0.1',
    user_agent: null,
    ok: false,
    meta: null,
    created_at: '2026-10-06T09:00:00+00:00',
  },
]

const ADMIN_DOC = {
  id: 'g-1',
  dockey: 'glob1',
  docname: 'global',
  title: 'Глобальный документ',
  category: 'global_knowledge',
  size_bytes: 4096,
  chunk_count: 12,
}

const ADMIN_TASK = {
  id: 't-1',
  kind: 'indexing',
  title: 'Индексация: файл.txt',
  status: 'running',
  progress: 30,
  step: 'чанки',
  error: null,
  cancel_requested: false,
  session_id: null,
  project_id: null,
  created_at: '2026-10-07T09:00:00+00:00',
  started_at: '2026-10-07T09:00:01+00:00',
  finished_at: null,
  seconds: 5,
  stage_seconds: 2,
  result: null,
}

/** Достать option открытого Mantine Select: dropdown линкуется на label инпута. */
function selectOption(input: HTMLElement, name: string) {
  const label = document.querySelector(`label[for="${input.id}"]`)
  const listbox = label
    ? document.querySelector(`[role="listbox"][aria-labelledby="${label.id}"]`)
    : null
  if (!listbox) throw new Error(`Нет listbox для ${input.id}`)
  return within(listbox as HTMLElement).getByRole('option', {
    name,
    hidden: true,
  })
}

function renderApp(path = '/admin') {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  })
  return render(
    <AppProviders initialPath={path} queryClient={queryClient}>
      <AppRoutes />
    </AppProviders>,
  )
}

function adminRoutes(overrides: Record<string, unknown> = {}) {
  return {
    'GET /api/health': HEALTH,
    'GET /api/tasks': { tasks: [], active: 0 },
    'GET /api/sessions': [],
    'GET /api/admin/users': USERS,
    'GET /api/admin/audit': AUDIT,
    'GET /api/admin/documents': [ADMIN_DOC],
    ...overrides,
  }
}

beforeEach(() => {
  sessionStorage.clear()
})

afterEach(() => {
  vi.unstubAllGlobals()
  resetAuth()
})

describe('админка', () => {
  it('не-админ видит «Раздел доступен только администратору.»', async () => {
    loginAs(TEST_USER)
    mockApi(adminRoutes())

    renderApp()

    expect(
      await screen.findByText('Раздел доступен только администратору.'),
    ).toBeInTheDocument()
    // вкладки даже не монтируются
    expect(screen.queryByRole('tab', { name: 'Пользователи' })).toBeNull()
  })

  it('вкладки по умолчанию: пользователи с ролями и ФИО', async () => {
    loginAs(TEST_ADMIN)
    mockApi(adminRoutes())

    renderApp()

    expect(await screen.findByRole('tab', { name: 'Пользователи' })).toBeInTheDocument()
    expect(await screen.findByText(/ivanov/)).toBeInTheDocument()
    expect(screen.getByText(/Иванов И.И./)).toBeInTheDocument()
    expect(screen.getByLabelText('Роль: petrov')).toHaveValue('admin')
  })

  it('создание пользователя: кнопкаdisabledпока пароль короче 8', async () => {
    const { calls } = mockApi(
      adminRoutes({
        'POST /api/admin/users': {
          id: 'u-new',
          username: 'sidorov',
          role: 'researcher',
          full_name: null,
          email: null,
          is_active: true,
          last_login_at: null,
        },
      }),
    )
    loginAs(TEST_ADMIN)

    renderApp()
    await screen.findByText(/ivanov/)

    await userEvent.click(screen.getByRole('button', { name: 'Создать пользователя' }))
    await userEvent.type(screen.getByLabelText(/^Логин/), 'sidorov')
    await userEvent.type(screen.getByLabelText(/^Пароль/), 'short')

    const submit = screen.getByRole('button', { name: 'Создать' })
    expect(submit).toBeDisabled()

    await userEvent.type(screen.getByLabelText(/^Пароль/), '12345678')
    expect(submit).toBeEnabled()
    await userEvent.click(submit)

    expect(await screen.findByText('Пользователь создан.')).toBeInTheDocument()
    const call = calls.find(
      (c) => c.url.endsWith('/api/admin/users') && c.init.method === 'POST',
    )
    expect(call).toBeDefined()
    expect(JSON.parse(String(call?.init.body))).toMatchObject({
      username: 'sidorov',
      role: 'researcher',
      password: 'short12345678',
    })
  })

  it('смена роли шлёт PATCH только с role', async () => {
    const { calls } = mockApi(
      adminRoutes({
        'PATCH /api/admin/users/u-1': { ...USERS[0], role: 'admin' },
      }),
    )
    loginAs(TEST_ADMIN)

    renderApp()
    await screen.findByText(/ivanov/)

    const roleInput = screen.getByLabelText('Роль: ivanov')
    await userEvent.click(roleInput)
    await userEvent.click(selectOption(roleInput, 'admin'))
    // две строки пользователей — берём кнопку в строке ivanov
    const row = screen.getByText('ivanov').closest('tr') as HTMLElement
    await userEvent.click(within(row).getByRole('button', { name: 'Сохранить' }))

    await waitFor(() => {
      const call = calls.find(
        (c) => c.init.method === 'PATCH' && c.url.includes('/u-1'),
      )
      expect(call).toBeDefined()
      expect(JSON.parse(String(call?.init.body))).toEqual({ role: 'admin' })
    })
    expect(await screen.findByText('Сохранено.')).toBeInTheDocument()
  })

  it('ошибка создания показывается паритетно (alert)', async () => {
    mockApi(
      adminRoutes({
        'POST /api/admin/users': json(
          { detail: 'Пользователь «x» уже существует' },
          409,
        ),
      }),
    )
    loginAs(TEST_ADMIN)

    renderApp()
    await screen.findByText(/ivanov/)

    await userEvent.click(screen.getByRole('button', { name: 'Создать пользователя' }))
    await userEvent.type(screen.getByLabelText(/^Логин/), 'x')
    await userEvent.type(screen.getByLabelText(/^Пароль/), '12345678')
    await userEvent.click(screen.getByRole('button', { name: 'Создать' }))

    expect(
      await screen.findByText('Пользователь «x» уже существует'),
    ).toBeInTheDocument()
  })

  it('глобальная база: добавление по пути и переиндексация', async () => {
    const { calls } = mockApi(
      adminRoutes({
        'POST /api/admin/documents/path': ADMIN_DOC,
        'POST /api/admin/documents/reindex': { status: 'ok' },
      }),
    )
    loginAs(TEST_ADMIN)

    renderApp()
    await screen.findByRole('tab', { name: 'Глобальная база' })
    await userEvent.click(screen.getByRole('tab', { name: 'Глобальная база' }))

    // документы глобальной базы уже видны
    expect(await screen.findByText(/Глобальный документ/)).toBeInTheDocument()

    // пустой путь — кнопка заблокирована
    expect(screen.getByRole('button', { name: 'Добавить' })).toBeDisabled()

    await userEvent.type(screen.getByLabelText('Путь к файлу'), '/data/x.pdf')
    await userEvent.click(screen.getByRole('button', { name: 'Добавить' }))
    expect(await screen.findByText('Добавлено.')).toBeInTheDocument()
    await waitFor(() => {
      expect(calls.some((c) => c.url.endsWith('/api/admin/documents/path'))).toBe(true)
    })

    await userEvent.click(screen.getByRole('button', { name: 'Переиндексировать всё' }))
    expect(await screen.findByText('Готово.')).toBeInTheDocument()
    expect(calls.some((c) => c.url.endsWith('/reindex'))).toBe(true)
  })

  it('массовая индексация: парсинг путей и ответ задачи', async () => {
    const { calls } = mockApi(
      adminRoutes({
        'POST /api/admin/documents/bulk-async': { task_id: 't-bulk', total: 3 },
      }),
    )
    loginAs(TEST_ADMIN)

    renderApp()
    await userEvent.click(await screen.findByRole('tab', { name: 'Глобальная база' }))

    // пустой ввод — русский warning как в admin.py
    await userEvent.click(screen.getByRole('button', { name: 'Запустить индексацию' }))
    expect(await screen.findByText('Укажите хотя бы один путь.')).toBeInTheDocument()

    await userEvent.type(
      screen.getByLabelText('Пути через запятую или по одному в строке'),
      '/a/1.pdf, /b/2.pdf\n /c/3.pdf',
    )
    await userEvent.click(screen.getByRole('button', { name: 'Запустить индексацию' }))

    expect(await screen.findByText('Задача поставлена: 3 файлов')).toBeInTheDocument()
    const call = calls.find((c) => c.url.endsWith('/bulk-async'))
    expect(call).toBeDefined()
    expect(JSON.parse(String(call?.init.body))).toEqual({
      paths: ['/a/1.pdf', '/b/2.pdf', '/c/3.pdf'],
      tags: [],
    })
  })

  it('вкладка Задачи: панель прогресса и ошибка задачи', async () => {
    loginAs(TEST_ADMIN)
    mockApi(
      adminRoutes({
        'GET /api/tasks': {
          tasks: [
            ADMIN_TASK,
            {
              ...ADMIN_TASK,
              id: 't-2',
              status: 'error',
              error: 'Не удалось проиндексировать',
            },
          ],
          active: 1,
        },
      }),
    )

    renderApp()
    await userEvent.click(await screen.findByRole('tab', { name: 'Задачи' }))

    expect(await screen.findByText(/30%/)).toBeInTheDocument()
    expect(screen.getByText('Не удалось проиндексировать')).toBeInTheDocument()
  })

  it('вкладка Задачи: пустое состояние «Задач нет.»', async () => {
    loginAs(TEST_ADMIN)
    mockApi(adminRoutes())

    renderApp()
    await userEvent.click(await screen.findByRole('tab', { name: 'Задачи' }))

    expect(await screen.findByText('Задач нет.')).toBeInTheDocument()
  })

  it('вкладка Сессии: колонки таблицы', async () => {
    loginAs(TEST_ADMIN)
    mockApi(
      adminRoutes({
        'GET /api/sessions': [
          {
            id: 'abcdefgh-1234',
            user_id: 'user-5678',
            title: 'Баренцево',
            status: 'active',
            last_action_label: 'chat',
            last_activity_at: '2026-10-07T12:34:00+00:00',
            created_at: '2026-10-01T00:00:00+00:00',
            expires_at: '2026-12-01T00:00:00+00:00',
          },
        ],
      }),
    )

    renderApp()
    await userEvent.click(await screen.findByRole('tab', { name: 'Сессии' }))

    const table = await screen.findByRole('table')
    const header = within(table)
      .getAllByRole('columnheader')
      .map((cell) => cell.textContent)
    expect(header).toEqual([
      'id',
      'пользователь',
      'название',
      'статус',
      'действие',
      'активность',
    ])
    expect(within(table).getByText('abcdefgh')).toBeInTheDocument()
    expect(within(table).getByText('2026-10-07 12:34')).toBeInTheDocument()
  })

  it('вкладка Аудит: сортировка по времени и ok', async () => {
    loginAs(TEST_ADMIN)
    mockApi(adminRoutes())

    renderApp()
    await userEvent.click(await screen.findByRole('tab', { name: 'Аудит' }))

    const table = await screen.findByRole('table')
    let cells = within(table).getAllByRole('row')
    // по умолчанию сначала новые
    expect(cells[1]).toHaveTextContent('session.create')
    expect(cells[2]).toHaveTextContent('admin.user.create')
    expect(within(table).getByText('✓')).toBeInTheDocument()
    expect(within(table).getByText('✗')).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: /Время:/ }))
    cells = within(table).getAllByRole('row')
    expect(cells[1]).toHaveTextContent('admin.user.create')
    expect(screen.getByRole('button', { name: /сначала старые/ })).toBeInTheDocument()
  })
})
