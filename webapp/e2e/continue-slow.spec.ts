import { expect, test } from '@playwright/test'

/**
 * Регрессия: «Продолжить» открывал пустое окно.
 *
 * Гонка: ответ `PUT /state` (SessionOut, без `summary`) приходил раньше
 * `GET /api/sessions/{id}` и подменял кэш detail объектом без `summary` —
 * `SessionPage` падал, React размонтировал дерево, страница оставалась пустой
 * до F5. Медленный detail воспроизводит эту гонку надёжно.
 */

test.setTimeout(120_000)

test('«Продолжить» открывает страницу даже при медленном detail', async ({ page }) => {
  const errors: string[] = []
  page.on('console', (m) => errors.push(`[${m.type()}] ${m.text()}`))
  page.on('pageerror', (e) => errors.push(`pageerror: ${e.message}\n${e.stack ?? ''}`))
  page.on('crash', () => errors.push('CRASH страницы'))

  const delay = Number(process.env.DETAIL_DELAY ?? 4000)

  await page.addInitScript(() => {
    const w = window as unknown as { __caught: string[] }
    w.__caught = []
    window.addEventListener('error', (event) => {
      w.__caught.push(`error: ${event.message} @ ${event.filename}:${event.lineno}`)
    })
    window.addEventListener('unhandledrejection', (event) => {
      w.__caught.push(`rejection: ${String(event.reason)}`)
    })
  })

  await page.route(
    (url) => url.pathname === '/api' || url.pathname.startsWith('/api/'),
    async (route) => {
      const req = route.request()
      const { pathname } = new URL(req.url())
      const key = `${req.method()} ${pathname}`
      const withAuth = Boolean(req.headers()['authorization'])
      if (key === 'GET /api/sessions/s-1' || key === 'GET /api/sessions/s-1/messages') {
        await new Promise((r) => setTimeout(r, delay))
      }
      const SESSION = {
        id: 's-1',
        user_id: 'u-1',
        owner_username: 'ivanov',
        owner_full_name: null,
        title: 'Медленная сессия',
        status: 'active',
        last_action_type: 'chat',
        last_action_label: 'Вопрос',
        last_action_at: '2026-10-06T12:00:00+00:00',
        resume_note: null,
        state_snapshot: {},
        created_at: '2026-10-01T00:00:00+00:00',
        last_activity_at: '2026-10-06T12:00:00+00:00',
        expires_at: '2026-12-30T00:00:00+00:00',
        archived_at: null,
        purged_at: null,
      }
      const bodies: Record<string, unknown> = {
        'GET /api/health': {
          status: 'ok',
          app: 'boasi_s',
          environment: 'e2e',
          version: '0',
          database: 'ok',
          llm_model: 'm',
          embedding_model: 'e',
          ollama: { reachable: false },
        },
        'GET /api/sessions': [SESSION],
        'GET /api/tasks': { tasks: [], active: 0 },
        'GET /api/sessions/s-1': {
          ...SESSION,
          days_left: 84,
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
        'GET /api/sessions/s-1/messages': { messages: [], total: 0 },
        'PUT /api/sessions/s-1/state': SESSION,
        'POST /api/auth/login': {
          user: { id: 'u-1', username: 'ivanov', role: 'researcher', is_active: true },
          tokens: {
            access_token: 'a',
            refresh_token: 'r',
            expires_in: 900,
            refresh_expires_in: 86400,
          },
        },
      }
      const body =
        key === 'GET /api/auth/me'
          ? withAuth
            ? { id: 'u-1', username: 'ivanov', role: 'researcher', is_active: true }
            : undefined
          : (bodies[key] as unknown)
      if (body === undefined && key !== 'GET /api/auth/me') {
        await route.fulfill({
          status: 404,
          contentType: 'application/json',
          body: JSON.stringify({ detail: `нет мока: ${key}` }),
        })
        return
      }
      await route.fulfill({
        status: key === 'GET /api/auth/me' && !withAuth ? 401 : 200,
        contentType: 'application/json',
        body: JSON.stringify(body ?? { detail: 'Not authenticated' }),
      })
    },
  )

  await page.goto('/login')
  await page.getByLabel('Логин').fill('ivanov')
  await page.getByLabel('Пароль').fill('researcher-pass-123')
  await page.getByRole('button', { name: 'Войти' }).click()
  await page.getByTestId('session-card').waitFor()

  await page.getByRole('button', { name: 'Продолжить' }).click()
  // ждём ВСЕ загрузки (detail + история) с задержкой
  await page.waitForTimeout(delay * 3)
  const body = await page.locator('body').innerText()
  const caught = await page.evaluate(
    () => (window as unknown as { __caught: string[] }).__caught,
  )

  // страница не «зависла» в загрузке и не размонтировалась React-ошибкой
  await expect(page).toHaveURL(/\/s\/s-1\/chat$/)
  await expect(page.getByRole('heading', { name: 'Медленная сессия' })).toBeVisible()
  expect(body).toContain('Документы:')
  expect(caught, `ошибки в странице: ${caught.join(' | ')}`).toEqual([])
})
