import { expect, type Page, test } from '@playwright/test'

// Проверки делят одну БД: тесты идут строго по очереди, иначе один
// удаляет сессии, пока второй уже смотрит на дашборд.
test.describe.configure({ mode: 'serial' })

/**
 * Многопользовательский режим на живом стенде: два исследователя в двух
 * окнах браузера одновременно.
 *
 * Проверяем то, что не видно в тестах одного пользователя:
 *   — дашборд каждого показывает только свои сессии;
 *   — открытая чужой сессию по прямой ссылке не подгружается (404, а не пустое
 *     окно — ровно тот баг, который чинили в `continue-slow.spec.ts`);
 *   — переключение пользователя в одном окне не влияет на второе.
 */

const PASSWORD = 'mu-pass-123'
/** Админ стенда для e2e: заводится скриптом, пароль тот же mu-pass-123. */
const ADMIN_LOGIN = 'mu_admin'

/**
 * Удаляет сессии пользователя через API, чтобы прогон не зависел от
 * состояния БД: иначе сессии прошлых прогонов ломали бы проверки
 * «в списке только своя» (strict mode violation на повторах текста).
 */
async function dropSessions(page: Page) {
  const deleted = await page.evaluate(async () => {
    // access-токен живёт в памяти модуля, поэтому берём refresh из
    // localStorage и меняем его на новую пару
    const key = Object.keys(localStorage).find((k) => k.includes('refresh'))
    const refresh = key ? localStorage.getItem(key) : null
    if (!refresh) return 0
    const pair = await fetch('/api/auth/refresh', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ refresh_token: refresh }),
    })
    if (!pair.ok) return 0
    const { access_token: access, refresh_token: next } = await pair.json()
    // refresh-токен одноразовый: обменяв его здесь, обязаны записать новый
    // обратно, иначе после перезагрузки клиент вылетит на /login
    if (key && next) localStorage.setItem(key, next)
    const auth = { Authorization: `Bearer ${access}` }
    const list = await fetch('/api/sessions', { headers: auth })
    if (!list.ok) return 0
    const sessions = await list.json()
    for (const session of sessions) {
      await fetch(`/api/sessions/${session.id}`, { method: 'DELETE', headers: auth })
    }
    return sessions.length
  })
  await page.reload()
  // карточек может не быть вовсе — это нормально, важно что запрос прошёл
  await expect(page.getByText(/Активных сессий нет|Сессий нет/)).toBeVisible()
  return deleted
}

async function signIn(page: Page, username: string) {
  await page.goto('/login')
  await page.getByLabel('Логин').fill(username)
  await page.getByLabel('Пароль').fill(PASSWORD)
  await page.getByRole('button', { name: 'Войти' }).click()
  await expect(page).toHaveURL(/\/$/)
}

async function newSession(page: Page, title: string) {
  await page.getByLabel('Название').fill(title)
  await page.getByRole('button', { name: 'Создать' }).click()
  await page.waitForURL(/\/s\//)
  const url = page.url()
  await page.getByRole('button', { name: '← Информационная панель' }).click()
  await page.getByTestId('session-card').first().waitFor()
  return url
}

test('два исследователя: сессии не пересекаются', async ({ browser }) => {
  const contextA = await browser.newContext()
  const contextB = await browser.newContext()
  const ivan = await contextA.newPage()
  const petr = await contextB.newPage()

  const errors: string[] = []
  for (const page of [ivan, petr]) {
    page.on('pageerror', (e) => errors.push(`pageerror: ${e.message}`))
  }

  await signIn(ivan, 'mu_ivan')
  await signIn(petr, 'mu_petr')

  // чистим остатки прошлых прогонов: у каждого своя история
  await dropSessions(ivan)
  await dropSessions(petr)

  // каждый создаёт по сессии и уходит обратно на дашборд
  const ivanUrl = await newSession(ivan, 'Сессия Ивана')
  const petrUrl = await newSession(petr, 'Сессия Петра')

  // дашборд Ивана: своя сессия есть, чужая — нет
  await expect(ivan.getByText('Сессия Ивана')).toBeVisible()
  expect(await ivan.getByText('Сессия Петра').count()).toBe(0)

  // дашборд Петра — зеркально
  await expect(petr.getByText('Сессия Петра')).toBeVisible()
  expect(await petr.getByText('Сессия Ивана').count()).toBe(0)

  // заголовки списков у исследователей прежние — без групп владельцев
  await expect(ivan.getByRole('heading', { name: /^Мои сессии/ })).toBeVisible()

  // Петр открывает сессию Ивана по прямой ссылке
  await petr.goto(ivanUrl)
  await expect(petr.getByText('Сессия не найдена')).toBeVisible()

  // и наоборот
  await ivan.goto(petrUrl)
  await expect(ivan.getByText('Сессия не найдена')).toBeVisible()

  // каждая сессия у своего владельца открывается нормально
  await ivan.goto(ivanUrl)
  await expect(ivan.getByRole('heading', { name: 'Сессия Ивана' })).toBeVisible()
  await petr.goto(petrUrl)
  await expect(petr.getByRole('heading', { name: 'Сессия Петра' })).toBeVisible()

  expect(errors, `ошибки в браузере:\n${errors.join('\n')}`).toEqual([])

  await contextA.close()
  await contextB.close()
})

test('админ в третьем окне видит обе сессии по владельцам', async ({ browser }) => {
  const contextA = await browser.newContext()
  const contextB = await browser.newContext()
  const contextAdmin = await browser.newContext()
  const ivan = await contextA.newPage()
  const petr = await contextB.newPage()
  const admin = await contextAdmin.newPage()

  await signIn(ivan, 'mu_ivan')
  await signIn(petr, 'mu_petr')
  await dropSessions(ivan)
  await dropSessions(petr)
  await newSession(ivan, 'Сессия Ивана')
  await newSession(petr, 'Сессия Петра')

  await signIn(admin, ADMIN_LOGIN)
  await admin.reload()
  await expect(
    admin.getByRole('heading', { name: /^Сессии всех пользователей/ }),
  ).toBeVisible()
  await expect(
    admin.getByRole('heading', { name: /^Сессии всех пользователей/ }),
  ).toBeVisible()
  await expect(admin.getByText(/^mu_ivan \(\d\)$/)).toBeVisible()
  await expect(admin.getByText(/^mu_petr \(\d\)$/)).toBeVisible()

  // админ может открыть чужую сессию (для аудита), и она живая
  const card = admin.getByTestId('session-card').filter({ hasText: 'Сессия Ивана' })
  await card.getByRole('button', { name: 'Продолжить' }).click()
  await expect(admin.getByRole('heading', { name: 'Сессия Ивана' })).toBeVisible()

  await contextA.close()
  await contextB.close()
  await contextAdmin.close()
})

test('выход и вход другим пользователем в том же окне', async ({ page }) => {
  await signIn(page, 'mu_ivan')
  await dropSessions(page)
  await newSession(page, 'Сессия Ивана')

  await page.getByRole('button', { name: 'Выйти' }).click()
  await expect(page).toHaveURL(/\/login/)

  await signIn(page, 'mu_petr')
  await dropSessions(page)
  await expect(page.getByText('Сессия Ивана')).toHaveCount(0)
  await page.goto('/')
  await page.waitForTimeout(500)
  expect(await page.getByText('Сессия Ивана').count()).toBe(0)
})
