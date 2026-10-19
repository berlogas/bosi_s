import { expect, test, type Page } from '@playwright/test'

/**
 * Приёмка Фазы 4: админка.
 *
 * Сценарии: guard роли (не-админ не проходит), создание пользователя
 * (валидация пароля), смена роли → PATCH, глобальная база (путь и
 * массовая индексация), вкладки Задачи/Сессии/Аудит.
 *
 * Сеть замокана целиком — бэкенд не нужен.
 */

const HEALTH = {
  status: 'ok',
  llm_model: 'test-model',
  embedding_model: 'test-embed',
  ollama: { reachable: false, models: [], reason: 'mock' },
  build: { build: 'e2e', commit: null, built_at: null, ui: null },
}

const ADMIN = { username: 'admin', role: 'admin', display_name: 'Admin' }
const RESEARCHER = { username: 'user', role: 'researcher', display_name: 'User' }

type Body = unknown | (() => unknown)
type Route = { status?: number; body: Body }

async function mockApi(
  page: Page,
  overrides: Record<string, Route> = {},
): Promise<{ requestLog: string[] }> {
  const requestLog: string[] = []
  const routes: Record<string, Route> = {
    'GET /api/health': { body: HEALTH },
    'GET /api/auth/me': { status: 401, body: { detail: 'Not authenticated' } },
    'POST /api/auth/refresh': {
      body: {
        access_token: 'e2e-access',
        refresh_token: 'e2e-refresh',
        expires_in: 900,
        refresh_expires_in: 86400,
      },
    },
    'POST /api/auth/login': {
      body: {
        user: ADMIN,
        tokens: {
          access_token: 'e2e-access',
          refresh_token: 'e2e-refresh',
          expires_in: 900,
          refresh_expires_in: 86400,
        },
      },
    },
    'GET /api/sessions': { body: [] },
    'GET /api/tasks': { body: { tasks: [], active: 0 } },
    'GET /api/admin/users': {
      body: [
        {
          id: 'u-1',
          username: 'ivanov',
          role: 'researcher',
          full_name: 'Иванов И.И.',
          is_active: true,
          email: null,
          last_login_at: null,
        },
      ],
    },
    'GET /api/admin/audit': { body: [] },
    'GET /api/admin/documents': {
      body: [
        {
          id: 'g-1',
          dockey: 'glob1',
          docname: 'global',
          title: 'Глобальный документ',
          category: 'global_knowledge',
          size_bytes: 2048,
          chunk_count: 7,
        },
      ],
    },
    ...overrides,
  }

  await page.route(
    (url) => url.pathname === '/api' || url.pathname.startsWith('/api/'),
    async (route) => {
      const req = route.request()
      const url = new URL(req.url())
      const key = `${req.method()} ${url.pathname}`
      let handler = routes[key]
      requestLog.push(`${key}${url.search}`)
      const meRoute = routes['GET /api/auth/me']
      const meUnauthorized = !meRoute || (meRoute.status ?? 200) === 401
      if (
        key === 'GET /api/auth/me' &&
        req.headers()['authorization'] &&
        meUnauthorized
      ) {
        handler = { body: ADMIN }
      }
      if (!handler) {
        await route.fulfill({
          status: 404,
          contentType: 'application/json',
          body: JSON.stringify({ detail: `Немокнутый e2e-запрос: ${key}` }),
        })
        return
      }
      const raw = typeof handler.body === 'function' ? handler.body() : handler.body
      await route.fulfill({
        status: handler.status ?? 200,
        contentType: 'application/json',
        body: JSON.stringify(raw ?? null),
      })
    },
  )
  return { requestLog }
}

async function login(
  page: Page,
  user: { username: string; password: string },
): Promise<void> {
  await page.goto('/login')
  await page.getByLabel('Логин').fill(user.username)
  await page.getByLabel('Пароль').fill(user.password)
  await page.getByRole('button', { name: 'Войти' }).click()
}

test('не-админ: guard «Раздел доступен только администратору.»', async ({ page }) => {
  await mockApi(page, {
    'POST /api/auth/login': {
      body: {
        user: RESEARCHER,
        tokens: {
          access_token: 'e2e-access',
          refresh_token: 'e2e-refresh',
          expires_in: 900,
          refresh_expires_in: 86400,
        },
      },
    },
    'GET /api/auth/me': { body: RESEARCHER },
  })

  await login(page, { username: 'user', password: 'password1' })
  await page.goto('/admin')

  await expect(page.getByText('Раздел доступен только администратору.')).toBeVisible()
  await expect(page.getByRole('tab', { name: 'Пользователи' })).toHaveCount(0)
  // ссылка в сайдбаре не показывается не-админу (паритет state.require_auth)
  await expect(page.getByRole('link', { name: 'Администрирование' })).toHaveCount(0)
})

test('создание пользователя: валидация пароля и success', async ({ page }) => {
  const { requestLog } = await mockApi(page, {
    'POST /api/admin/users': {
      status: 201,
      body: {
        id: 'u-2',
        username: 'sidorov',
        role: 'researcher',
        full_name: null,
        email: null,
        is_active: true,
        last_login_at: null,
      },
    },
    'GET /api/admin/users': {
      body: () =>
        requestLog.some(
          (line) => line.endsWith('/api/admin/users') && line.includes('POST'),
        )
          ? [
              {
                id: 'u-2',
                username: 'sidorov',
                role: 'researcher',
                full_name: null,
                email: null,
                is_active: true,
                last_login_at: null,
              },
            ]
          : [
              {
                id: 'u-1',
                username: 'ivanov',
                role: 'researcher',
                full_name: 'Иванов И.И.',
                is_active: true,
                email: null,
                last_login_at: null,
              },
            ],
    },
  })

  await login(page, { username: 'admin', password: 'password1' })
  await page.goto('/admin')
  // Логин лежит в value поля редактирования, а не в тексте ячейки, поэтому
  // getByText его не находит: ищем по доступному имени поля.
  await expect(page.getByRole('textbox', { name: 'Логин: ivanov' })).toHaveValue(
    'ivanov',
  )

  await page.getByRole('button', { name: 'Создать пользователя' }).click()
  // /^Логин/ без exact ловит ещё и поле строки ivanov («Логин: ivanov»)
  await page.getByRole('textbox', { name: 'Логин', exact: true }).fill('sidorov')
  await page.getByRole('textbox', { name: 'Пароль', exact: true }).fill('short')

  const submit = page.getByRole('button', { name: 'Создать', exact: true })
  await expect(submit).toBeDisabled()

  await page.getByRole('textbox', { name: 'Пароль', exact: true }).fill('longenough1')
  await expect(submit).toBeEnabled()
  await submit.click()

  await expect(page.getByText('Пользователь создан.')).toBeVisible()
  expect(
    requestLog.some(
      (line) => line.endsWith('/api/admin/users') && line.includes('POST'),
    ),
  ).toBe(true)
})

test('глобальная база: путь, папка-приёмник и переиндексация', async ({ page }) => {
  const { requestLog } = await mockApi(page, {
    'POST /api/admin/documents/path': {
      body: {
        id: 'g-2',
        dockey: 'glob2',
        docname: 'new',
        title: 'Новый файл',
        category: 'global_knowledge',
        size_bytes: 1024,
        chunk_count: 3,
      },
    },
    'GET /api/admin/documents': {
      body: () =>
        requestLog.some((line) => line.endsWith('/documents/path'))
          ? [
              {
                id: 'g-1',
                dockey: 'glob1',
                docname: 'global',
                title: 'Глобальный документ',
                category: 'global_knowledge',
                size_bytes: 2048,
                chunk_count: 7,
              },
              {
                id: 'g-2',
                dockey: 'glob2',
                docname: 'new',
                title: 'Новый файл',
                category: 'global_knowledge',
                size_bytes: 1024,
                chunk_count: 3,
              },
            ]
          : [
              {
                id: 'g-1',
                dockey: 'glob1',
                docname: 'global',
                title: 'Глобальный документ',
                category: 'global_knowledge',
                size_bytes: 2048,
                chunk_count: 7,
              },
            ],
    },
    // Массовое добавление идёт через папку-приёмник: отдельного поля со
    // списком путей в интерфейсе больше нет.
    'GET /api/admin/inbox/status': {
      body: {
        inbox_dir: '/data/inbox',
        exists: true,
        files: 2,
        usable_files: 2,
        unsupported_files: 0,
        bytes: 4096,
        busy: false,
      },
    },
    'GET /api/admin/inbox/runs': { body: [] },
    'POST /api/admin/inbox/scan': {
      body: {
        run: {
          id: 'r-1',
          trigger: 'manual',
          status: 'done',
          inbox_dir: '/data/inbox',
          scanned: 2,
          indexed: 2,
          archived: 2,
          rejected: 0,
          replaced: 0,
          failed: 0,
          error: null,
          started_at: '2026-10-07T09:00:00+00:00',
          finished_at: '2026-10-07T09:00:05+00:00',
        },
        inbox_dir: '/data/inbox',
      },
    },
    'POST /api/admin/documents/reindex': { body: { task_id: 't-r' } },
  })

  await login(page, { username: 'admin', password: 'password1' })
  await page.goto('/admin')
  await page.getByRole('tab', { name: 'Глобальная база' }).click()

  await expect(page.getByText(/Глобальный документ/)).toBeVisible()
  await expect(page.getByRole('button', { name: 'Добавить' })).toBeDisabled()

  await page.getByLabel('Путь к файлу').fill('/data/new.pdf')
  await page.getByRole('button', { name: 'Добавить' }).click()
  await expect(page.getByText('Добавлено.')).toBeVisible({ timeout: 15_000 })
  await expect(page.getByText(/Новый файл/)).toBeVisible({ timeout: 15_000 })

  // папка-приёмник: файлы видно, кнопка запуска разблокирована
  await expect(page.getByText(/В папке: 2 \(принимаемых 2\)/)).toBeVisible()
  const scan = page.getByRole('button', { name: 'Запустить массовое добавление' })
  await expect(scan).toBeEnabled()
  await scan.click()
  await expect(page.getByText(/проиндексировано 2, отклонено 0/)).toBeVisible({
    timeout: 15_000,
  })

  await page.getByRole('button', { name: 'Переиндексировать всё' }).click()
  await expect(page.getByText('Готово.')).toBeVisible({ timeout: 15_000 })

  expect(requestLog.some((line) => line.endsWith('/documents/path'))).toBe(true)
  expect(requestLog.some((line) => line.endsWith('/inbox/scan'))).toBe(true)
  expect(requestLog.some((line) => line.endsWith('/documents/reindex'))).toBe(true)
})

test('вкладки Задачи, Сессии и Аудит', async ({ page }) => {
  await mockApi(page, {
    'GET /api/tasks': {
      body: {
        tasks: [
          {
            id: 't-1',
            kind: 'indexing',
            title: 'Индексация: файл.txt',
            status: 'running',
            progress: 45,
            step: 'чанки',
            error: null,
            cancel_requested: false,
            session_id: null,
            project_id: null,
            created_at: '2026-10-07T09:00:00+00:00',
            started_at: '2026-10-07T09:00:01+00:00',
            finished_at: null,
            seconds: 6,
            stage_seconds: 2,
            result: null,
          },
        ],
        active: 1,
      },
    },
    'GET /api/sessions': {
      body: [
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
      ],
    },
    'GET /api/admin/audit': {
      body: [
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
      ],
    },
  })

  await login(page, { username: 'admin', password: 'password1' })
  await page.goto('/admin')

  // Задачи: панель прогресса
  await page.getByRole('tab', { name: 'Задачи' }).click()
  await expect(page.getByText(/45%/)).toBeVisible()

  // Сессии: сгруппированы по пользователям (ivanov — из списка users)
  await page.getByRole('tab', { name: 'Сессии' }).click()
  // Имя региона-аккордеона — логин целиком, а панель внутри него называется
  // «ivanov, 1 сессия»: без exact локатор находит оба и падает strict mode.
  await expect(page.getByRole('region', { name: 'ivanov', exact: true })).toBeVisible()
  await expect(page.getByText('1 сессия')).toBeVisible()
  // Панель может быть раскрыта по умолчанию: без проверки клик по кнопке её
  // закрывает, и следующая проверка падает на отсутствии таблицы.
  const sessionsToggle = page.getByRole('button', { name: /ivanov/ })
  if ((await sessionsToggle.getAttribute('aria-expanded')) === 'false') {
    await sessionsToggle.click()
  }
  const table = page.getByRole('table')
  await expect(table.getByText('abcdefgh')).toBeVisible()
  await expect(table.getByText('2026-10-07 12:34')).toBeVisible()

  // Аудит: строка и признак ok
  await page.getByRole('tab', { name: 'Аудит' }).click()
  await expect(page.getByText('session.create')).toBeVisible()
  await expect(page.getByText('✓')).toBeVisible()
})
