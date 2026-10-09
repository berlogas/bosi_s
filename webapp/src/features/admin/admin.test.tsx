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

/** Достать option открытого Mantine Select.
 *  Линка списка идёт либо на сам input (без видимой подписи), либо на label. */
function selectOption(input: HTMLElement, name: string) {
  const label = document.querySelector(`label[for="${input.id}"]`)
  const listbox =
    document.querySelector(`[role="listbox"][aria-labelledby="${input.id}"]`) ??
    (label
      ? document.querySelector(`[role="listbox"][aria-labelledby="${label.id}"]`)
      : null) ??
    document.querySelector('[role="listbox"]')
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

const AUDIT_STATS = {
  total: 1234,
  oldest_at: '2026-01-05T10:00:00+00:00',
  newest_at: '2026-10-09T10:00:00+00:00',
}

const INBOX_STATUS = {
  inbox_dir: '/data/inbox',
  exists: true,
  files: 2,
  usable_files: 2,
  unsupported_files: 0,
  bytes: 2048,
  busy: false,
}

const INBOX_RUNS = [
  {
    id: 'run-1',
    trigger: 'manual',
    status: 'done',
    inbox_dir: '/data/inbox',
    scanned: 2,
    indexed: 1,
    archived: 1,
    rejected: 1,
    replaced: 0,
    failed: 0,
    error: null,
    started_at: '2026-10-09T10:00:00+00:00',
    finished_at: '2026-10-09T10:00:12+00:00',
    files: [
      {
        id: 'f-1',
        rel_path: 'годовой отчёт.pdf',
        abs_path: '/data/inbox/годовой отчёт.pdf',
        size_bytes: 1024,
        sha256: 'abc',
        status: 'archived',
        stage: 'archived',
        reason_code: null,
        reason_text: null,
        attempts: 1,
        document_id: 'd-1',
        final_path: '/data/documents/library/2026-10/годовой отчёт.pdf',
        created_at: '2026-10-09T10:00:00+00:00',
        updated_at: '2026-10-09T10:00:12+00:00',
      },
      {
        id: 'f-2',
        rel_path: 'скан.jpg',
        abs_path: '/data/inbox/скан.jpg',
        size_bytes: 1024,
        sha256: 'def',
        status: 'rejected',
        stage: 'rejected',
        reason_code: 'unsupported_extension',
        reason_text: 'Неподдерживаемый тип файла: .jpg',
        attempts: 1,
        document_id: null,
        final_path: '/data/rejected/2026-10-09/скан.jpg',
        created_at: '2026-10-09T10:00:00+00:00',
        updated_at: '2026-10-09T10:00:12+00:00',
      },
    ],
  },
]

function adminRoutes(overrides: Record<string, unknown> = {}) {
  return {
    'GET /api/health': HEALTH,
    'GET /api/tasks': { tasks: [], active: 0 },
    'GET /api/sessions': [],
    'GET /api/admin/users': USERS,
    'GET /api/admin/audit': AUDIT,
    'GET /api/admin/documents': [ADMIN_DOC],
    'GET /api/admin/audit/stats': AUDIT_STATS,
    'GET /api/admin/inbox/status': INBOX_STATUS,
    'GET /api/admin/inbox/runs': INBOX_RUNS,
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
    expect(await screen.findByLabelText('Логин: ivanov')).toBeInTheDocument()
    expect(screen.getByLabelText('ФИО: ivanov')).toHaveValue('Иванов И.И.')
    expect(screen.getByRole('combobox', { name: 'Роль: petrov' })).toHaveValue('admin')
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
    await screen.findByLabelText('Логин: ivanov')

    await userEvent.click(screen.getByRole('button', { name: 'Создать пользователя' }))
    await userEvent.type(screen.getByLabelText('Логин'), 'sidorov')
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
    await screen.findByLabelText('Логин: ivanov')

    const roleInput = screen.getByRole('combobox', { name: 'Роль: ivanov' })
    await userEvent.click(roleInput)
    await userEvent.click(selectOption(roleInput, 'admin'))
    // две строки пользователей — берём кнопку в строке ivanov
    const row = screen.getByLabelText('Логин: ivanov').closest('tr') as HTMLElement
    await userEvent.click(within(row).getByRole('button', { name: 'Сохранить' }))

    await waitFor(() => {
      const call = calls.find(
        (c) => c.init.method === 'PATCH' && c.url.includes('/u-1'),
      )
      expect(call).toBeDefined()
      expect(JSON.parse(String(call?.init.body))).toEqual({ role: 'admin' })
    })
    expect(await screen.findByText(/Сохранено: ivanov/)).toBeInTheDocument()
  })

  it('смена логина и ФИО шлёт PATCH с username и full_name', async () => {
    const { calls } = mockApi(
      adminRoutes({
        'PATCH /api/admin/users/u-1': {
          ...USERS[0],
          username: 'ivanov.i',
          full_name: 'Иванов Иван Иванович',
        },
      }),
    )
    loginAs(TEST_ADMIN)

    renderApp()
    const loginInput = await screen.findByLabelText('Логин: ivanov')
    await userEvent.clear(loginInput)
    await userEvent.type(loginInput, 'ivanov.i')
    const fullNameInput = screen.getByLabelText('ФИО: ivanov')
    await userEvent.clear(fullNameInput)
    await userEvent.type(fullNameInput, 'Иванов Иван Иванович')

    const row = loginInput.closest('tr') as HTMLElement
    await userEvent.click(within(row).getByRole('button', { name: 'Сохранить' }))

    await waitFor(() => {
      const call = calls.find(
        (c) => c.init.method === 'PATCH' && c.url.includes('/u-1'),
      )
      expect(JSON.parse(String(call?.init.body))).toEqual({
        role: 'researcher',
        username: 'ivanov.i',
        full_name: 'Иванов Иван Иванович',
      })
    })
    // после сохранения поле подстраивается под ответ сервера
    await waitFor(() => expect(loginInput).toHaveValue('ivanov.i'))
  })

  it('короткий логин не даёт сохранить и подсказывает причину', async () => {
    const { calls } = mockApi(adminRoutes())
    loginAs(TEST_ADMIN)

    renderApp()
    const loginInput = await screen.findByLabelText('Логин: ivanov')
    await userEvent.clear(loginInput)
    await userEvent.type(loginInput, 'i')

    const row = loginInput.closest('tr') as HTMLElement
    expect(within(row).getByRole('button', { name: 'Сохранить' })).toBeDisabled()
    expect(within(row).getByText(/минимум 2 символа/)).toBeInTheDocument()
    expect(calls.find((c) => c.init.method === 'PATCH')).toBeUndefined()
  })

  it('снятие активности шлёт PATCH с is_active=false', async () => {
    const { calls } = mockApi(
      adminRoutes({
        'PATCH /api/admin/users/u-1': { ...USERS[0], is_active: false },
      }),
    )
    loginAs(TEST_ADMIN)

    renderApp()
    await screen.findByLabelText('Логин: ivanov')
    await userEvent.click(screen.getByLabelText('Активен: ivanov'))

    await waitFor(() => {
      const call = calls.find(
        (c) => c.init.method === 'PATCH' && c.url.includes('/u-1'),
      )
      expect(JSON.parse(String(call?.init.body))).toEqual({
        role: 'researcher',
        is_active: false,
      })
    })
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
    await screen.findByLabelText('Логин: ivanov')

    await userEvent.click(screen.getByRole('button', { name: 'Создать пользователя' }))
    await userEvent.type(screen.getByLabelText('Логин'), 'x')
    await userEvent.type(screen.getByLabelText(/^Пароль/), '12345678')
    await userEvent.click(screen.getByRole('button', { name: 'Создать' }))

    expect(
      await screen.findByText('Пользователь «x» уже существует'),
    ).toBeInTheDocument()
  })

  it('удаление: кнопка в строке, каскад-предупреждение и DELETE', async () => {
    const { calls } = mockApi(
      adminRoutes({
        // 204 без тела — как отдаёт backend на удаление пользователя
        'DELETE /api/admin/users/u-1': new Response(null, { status: 204 }),
      }),
    )
    loginAs(TEST_ADMIN)

    renderApp()
    await screen.findByLabelText('Логин: ivanov')

    const row = screen.getByLabelText('Логин: ivanov').closest('tr') as HTMLElement
    await userEvent.click(within(row).getByRole('button', { name: 'Удалить: ivanov' }))

    // предупреждение про каскад видно до отправки запроса
    expect(await screen.findByText(/Действие необратимо/)).toBeInTheDocument()
    expect(
      screen.getByText(/сессии, сообщения, документы и проекты/),
    ).toBeInTheDocument()
    expect(calls.some((c) => c.init.method === 'DELETE')).toBe(false)

    await userEvent.click(screen.getByRole('button', { name: 'Удалить безвозвратно' }))

    await waitFor(() => {
      expect(
        calls.some(
          (c) => c.init.method === 'DELETE' && c.url.endsWith('/api/admin/users/u-1'),
        ),
      ).toBe(true)
    })
    // окно закрылось
    await waitFor(() => {
      expect(screen.queryByText(/Действие необратимо/)).toBeNull()
    })
  })

  it('удаление: отмена не шлёт запрос', async () => {
    const { calls } = mockApi(adminRoutes())
    loginAs(TEST_ADMIN)

    renderApp()
    await screen.findByLabelText('Логин: ivanov')

    const row = screen.getByLabelText('Логин: ivanov').closest('tr') as HTMLElement
    await userEvent.click(within(row).getByRole('button', { name: 'Удалить: ivanov' }))
    await userEvent.click(await screen.findByRole('button', { name: 'Отмена' }))

    await waitFor(() => {
      expect(screen.queryByText(/Действие необратимо/)).toBeNull()
    })
    expect(calls.some((c) => c.init.method === 'DELETE')).toBe(false)
  })

  it('удаление себя запрещено: кнопка задизейблена', async () => {
    mockApi(
      adminRoutes({
        'GET /api/admin/users': [TEST_ADMIN, ...USERS],
      }),
    )
    loginAs(TEST_ADMIN)

    renderApp()
    await screen.findByLabelText('Логин: ivanov')

    // строка самого администратора (TEST_ADMIN.id === u-admin)
    expect(screen.getByRole('button', { name: 'Удалить: admin' })).toBeDisabled()
    // чужие — доступны
    expect(screen.getByRole('button', { name: 'Удалить: ivanov' })).toBeEnabled()
  })

  it('удаление: ошибка 409 показывается в модалке', async () => {
    mockApi(
      adminRoutes({
        'DELETE /api/admin/users/u-1': json(
          { detail: 'Нельзя удалить самого себя' },
          409,
        ),
      }),
    )
    loginAs(TEST_ADMIN)

    renderApp()
    await screen.findByLabelText('Логин: ivanov')

    const row = screen.getByLabelText('Логин: ivanov').closest('tr') as HTMLElement
    await userEvent.click(within(row).getByRole('button', { name: 'Удалить: ivanov' }))
    await userEvent.click(
      await screen.findByRole('button', { name: 'Удалить безвозвратно' }),
    )

    expect(await screen.findByText('Нельзя удалить самого себя')).toBeInTheDocument()
  })

  it('глобальная база: после загрузки файлов поле очищается', async () => {
    mockApi(
      adminRoutes({
        'POST /api/admin/documents/upload': { added: ['a.pdf'], failed: [] },
      }),
    )
    loginAs(TEST_ADMIN)

    renderApp()
    await userEvent.click(await screen.findByRole('tab', { name: 'Глобальная база' }))

    await screen.findByLabelText('Или файлы')
    const fileInput = document.querySelector('input[type="file"]') as HTMLInputElement
    await userEvent.upload(fileInput, new File(['x'], 'a.pdf'))

    const upload = screen.getByRole('button', { name: 'Загрузить' })
    await waitFor(() => expect(upload).toBeEnabled())
    await userEvent.click(upload)

    expect(await screen.findByText('Добавлено 1')).toBeInTheDocument()
    // выбор очищен: ни названия файла, ни активной кнопки «Загрузить»
    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'Загрузить' })).toBeDisabled(),
    )
    expect(screen.queryByText('a.pdf')).toBeNull()
  })

  it('массовое добавление: кнопка активна при файлах и шлёт scan', async () => {
    const { calls } = mockApi(
      adminRoutes({
        'POST /api/admin/inbox/scan': {
          run: INBOX_RUNS[0],
          inbox_dir: '/data/inbox',
        },
      }),
    )
    loginAs(TEST_ADMIN)

    renderApp()
    await userEvent.click(await screen.findByRole('tab', { name: 'Глобальная база' }))

    const button = await screen.findByRole('button', {
      name: 'Запустить массовое добавление',
    })
    expect(await screen.findByText(/В папке: 2/)).toBeInTheDocument()
    await userEvent.click(button)

    expect(await screen.findByText(/Готово: проиндексировано 1/)).toBeInTheDocument()
    expect(
      calls.some((c) => c.init.method === 'POST' && c.url.endsWith('/inbox/scan')),
    ).toBe(true)
  })

  it('массовое добавление: кнопка заблокирована, когда папка пуста', async () => {
    mockApi(
      adminRoutes({
        'GET /api/admin/inbox/status': {
          ...INBOX_STATUS,
          files: 0,
          usable_files: 0,
        },
      }),
    )
    loginAs(TEST_ADMIN)

    renderApp()
    await userEvent.click(await screen.findByRole('tab', { name: 'Глобальная база' }))

    const button = await screen.findByRole('button', {
      name: 'Запустить массовое добавление',
    })
    await waitFor(() => expect(button).toBeDisabled())
  })

  it('журнал добавления показывает отчёт с причинами отказа', async () => {
    mockApi(adminRoutes())
    loginAs(TEST_ADMIN)

    renderApp()
    await userEvent.click(await screen.findByRole('tab', { name: 'Глобальная база' }))

    expect(await screen.findByText('годовой отчёт.pdf')).toBeInTheDocument()
    expect(screen.getByText('принят')).toBeInTheDocument()
    expect(screen.getByText('отклонён')).toBeInTheDocument()
    // причина спрятана за «почему?» — по кнопке раскрывается
    await userEvent.click(screen.getByRole('button', { name: 'почему?' }))
    expect(screen.getByText('Неподдерживаемый тип файла: .jpg')).toBeInTheDocument()
  })

  it('«Пути через запятую» больше нет — ввод путей заменён папкой-приёмником', async () => {
    mockApi(adminRoutes())
    loginAs(TEST_ADMIN)

    renderApp()
    await userEvent.click(await screen.findByRole('tab', { name: 'Глобальная база' }))

    expect(
      screen.queryByLabelText('Пути через запятую или по одному в строке'),
    ).toBeNull()
  })

  it('переиндексация осталась у списка документов, а не у массового добавления', async () => {
    mockApi(
      adminRoutes({
        'POST /api/admin/documents/reindex': { status: 'ok' },
      }),
    )
    loginAs(TEST_ADMIN)

    renderApp()
    await userEvent.click(await screen.findByRole('tab', { name: 'Глобальная база' }))

    const reindex = await screen.findByRole('button', {
      name: 'Переиндексировать всё',
    })
    // кнопка стоит после заголовка списка документов, а не в блоке inbox
    const documentsHeading = screen.getByText('Документы глобальной базы')
    const inboxHeading = screen.getByText('Массовое добавление')
    const order = documentsHeading.compareDocumentPosition(reindex)
    expect(order & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    expect(
      inboxHeading.compareDocumentPosition(reindex) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy()
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

  it('вкладка Задачи: фильтр по статусу оставляет только активные', async () => {
    loginAs(TEST_ADMIN)
    mockApi(
      adminRoutes({
        'GET /api/tasks': {
          tasks: [
            ADMIN_TASK,
            { ...ADMIN_TASK, id: 't-2', status: 'done', title: 'Готовая' },
            { ...ADMIN_TASK, id: 't-3', status: 'error', title: 'Ошибка' },
          ],
          active: 1,
        },
      }),
    )

    renderApp()
    await userEvent.click(await screen.findByRole('tab', { name: 'Задачи' }))

    expect(await screen.findByText(/Показано 3 из 3/)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('combobox', { name: /Фильтр: статус/ }))
    await userEvent.click(selectOption(
      screen.getByRole('combobox', { name: /Фильтр: статус/ }), 'Активные',
    ))

    expect(await screen.findByText(/Показано 1 из 3/)).toBeInTheDocument()
    expect(screen.queryByText('Готовая')).toBeNull()
  })

  it('вкладка Задачи: фильтр по пользователю', async () => {
    loginAs(TEST_ADMIN)
    mockApi(
      adminRoutes({
        'GET /api/tasks': {
          tasks: [
            { ...ADMIN_TASK, id: 't-1', user_id: 'u-1', title: 'Иванова' },
            { ...ADMIN_TASK, id: 't-2', user_id: 'u-2', title: 'Петрова' },
          ],
          active: 2,
        },
      }),
    )

    renderApp()
    await userEvent.click(await screen.findByRole('tab', { name: 'Задачи' }))

    const userFilter = await screen.findByRole('combobox', {
      name: /Фильтр: пользователь/,
    })
    await userEvent.click(userFilter)
    await userEvent.click(selectOption(userFilter, 'petrov'))

    expect(await screen.findByText(/Показано 1 из 2/)).toBeInTheDocument()
    expect(screen.queryByText('Иванова')).toBeNull()
  })

  it('вкладка Задачи: автор задачи показан по имени', async () => {
    loginAs(TEST_ADMIN)
    mockApi(
      adminRoutes({
        'GET /api/tasks': {
          tasks: [{ ...ADMIN_TASK, user_id: 'u-1', title: 'С индексацией' }],
          active: 1,
        },
      }),
    )

    renderApp()
    await userEvent.click(await screen.findByRole('tab', { name: 'Задачи' }))

    expect(await screen.findByText('Автор: ivanov')).toBeInTheDocument()
  })

  it('вкладка Задачи: очистка завершённых с подтверждением', async () => {
    const { calls } = mockApi(
      adminRoutes({
        'GET /api/tasks': {
          tasks: [
            ADMIN_TASK,
            { ...ADMIN_TASK, id: 't-2', status: 'done', title: 'Готовая' },
          ],
          active: 1,
        },
        'POST /api/tasks/clear': new Response(null, { status: 204 }),
      }),
    )
    loginAs(TEST_ADMIN)

    renderApp()
    await userEvent.click(await screen.findByRole('tab', { name: 'Задачи' }))

    await userEvent.click(await screen.findByRole('button', {
      name: 'Очистить завершённые',
    }))
    // без подтверждения запрос не уходит
    expect(calls.some((c) => c.url.endsWith('/api/tasks/clear'))).toBe(false)

    await userEvent.click(screen.getByRole('button', { name: 'Очистить' }))
    await waitFor(() =>
      expect(
        calls.some(
          (c) => c.init.method === 'POST' && c.url.endsWith('/api/tasks/clear'),
        ),
      ).toBe(true),
    )
  })

  it('вкладка Задачи: ссылки на сессию и документы задачи', async () => {
    loginAs(TEST_ADMIN)
    mockApi(
      adminRoutes({
        'GET /api/tasks': {
          tasks: [
            {
              ...ADMIN_TASK,
              status: 'done',
              title: 'Загрузка документов',
              session_id: 'abcdefgh',
              user_id: 'u-1',
              result: { added: [{ id: 'd-1', title: 'Годовой отчёт' }] },
            },
          ],
          active: 0,
        },
      }),
    )

    renderApp()
    await userEvent.click(await screen.findByRole('tab', { name: 'Задачи' }))

    expect(
      await screen.findByRole('button', {
        name: 'Открыть сессию задачи Загрузка документов',
      }),
    ).toBeInTheDocument()
    expect(
      screen.getByRole('button', {
        name: 'Документы задачи Загрузка документов',
      }),
    ).toBeInTheDocument()
  })


  it('вкладка Задачи: пустое состояние «Задач нет.»', async () => {
    loginAs(TEST_ADMIN)
    mockApi(adminRoutes())

    renderApp()
    await userEvent.click(await screen.findByRole('tab', { name: 'Задачи' }))

    expect(await screen.findByText('Задач нет.')).toBeInTheDocument()
  })

  it('вкладка Сессии: сессии сгруппированы по пользователям', async () => {
    loginAs(TEST_ADMIN)
    mockApi(
      adminRoutes({
        'GET /api/sessions': [
          {
            id: 'abcdefgh-1234',
            user_id: 'u-1',
            title: 'Баренцево',
            status: 'active',
            last_action_label: 'chat',
            last_activity_at: '2026-10-07T12:34:00+00:00',
            created_at: '2026-10-01T00:00:00+00:00',
            expires_at: '2026-12-01T00:00:00+00:00',
          },
          {
            id: '11112222-aaaa',
            user_id: 'u-2',
            title: 'Статья про моржей',
            status: 'archived',
            last_action_label: 'edit',
            last_activity_at: '2026-10-06T10:00:00+00:00',
            created_at: '2026-10-02T00:00:00+00:00',
            expires_at: '2026-12-01T00:00:00+00:00',
          },
        ],
      }),
    )

    renderApp()
    await userEvent.click(await screen.findByRole('tab', { name: 'Сессии' }))

    // группы по логинам из списка пользователей (u-1=ivanov, u-2=petrov)
    // (логины есть и в соседних вкладках/сайдбаре — ищем именно группы).
    // Роль region есть и у Accordion.Item, и у его панели, поэтому берём
    // группу от заголовка аккордеона, а не поиском по роли.
    const control = await screen.findByRole('button', { name: /ivanov/ })
    const group = control.closest('[role="region"]') as HTMLElement
    expect(group).toHaveAttribute('aria-label', 'ivanov')
    expect(screen.getAllByText('petrov').length).toBeGreaterThan(0)
    expect(screen.getAllByText('1 сессия').length).toBeGreaterThan(0)

    // первая группа раскрыта по умолчанию: таблица видна сразу
    expect(await screen.findByRole('table')).toBeInTheDocument()
    // закрываем и раскрываем обратно — таблица восстанавливается
    await userEvent.click(control)
    expect(screen.queryByRole('table')).toBeNull()
    await userEvent.click(control)
    await screen.findByRole('table')
    const table2 = await screen.findByRole('table')
    const header = within(table2)
      .getAllByRole('columnheader')
      .map((cell) => cell.textContent)
    expect(header).toEqual(['id', 'название', 'статус', 'действие', 'активность'])
    expect(within(table2).getByText('abcdefgh')).toBeInTheDocument()
    expect(within(table2).getByText('2026-10-07 12:34')).toBeInTheDocument()
  })

  it('вкладка Аудит: сводка и период фильтруют выборку', async () => {
    loginAs(TEST_ADMIN)
    const { calls } = mockApi(adminRoutes())

    renderApp()
    await userEvent.click(await screen.findByRole('tab', { name: 'Аудит' }))

    // сводка: видно, что ретрация работает и сколько всего записей
    expect(await screen.findByText(/всего записей: 1234/)).toBeInTheDocument()
    expect(screen.getByText(/самые старые от/)).toBeInTheDocument()
    expect(calls.some((c) => c.url.includes('/audit/stats'))).toBe(true)

    // «Всё время» — запрос без since
    const firstList = calls.find((c) => c.url.includes('/api/admin/audit?'))
    expect(firstList?.url).not.toContain('since')

    const period = screen.getByRole('combobox', { name: /Фильтр: период/ })
    await userEvent.click(period)
    await userEvent.click(selectOption(period, '7 дней'))

    await waitFor(() => {
      const call = calls.find(
        (c) => c.url.includes('/api/admin/audit?') && c.url.includes('since='),
      )
      expect(call).toBeDefined()
      expect(call?.url).toContain('limit=200')
    })
  })

  it('вкладка Аудит: кнопка выгрузки CSV и ссылка с текущим периодом', async () => {
    loginAs(TEST_ADMIN)
    mockApi(adminRoutes())

    renderApp()
    await userEvent.click(await screen.findByRole('tab', { name: 'Аудит' }))

    const link = await screen.findByRole('link', {
      name: 'Выгрузить журнал в CSV',
    })
    expect(link).toHaveAttribute('href', expect.stringContaining('/api/admin/audit/export'))

    const period = screen.getByRole('combobox', { name: /Фильтр: период/ })
    await userEvent.click(period)
    await userEvent.click(selectOption(period, '30 дней'))

    await waitFor(() =>
      expect(screen.getByRole('link', { name: 'Выгрузить журнал в CSV' }))
        .toHaveAttribute('href', expect.stringContaining('since=')),
    )
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
