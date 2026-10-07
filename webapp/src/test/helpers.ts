/**
 * Общие фикстуры для RTL-тестов: авторизация и подмена fetch.
 */

import { vi } from 'vitest'

import { tokens } from '../api/tokens'
import { useAuth } from '../features/auth/authStore'

export const TEST_USER = {
  id: 'u-1',
  username: 'ivanov',
  role: 'researcher' as const,
  is_active: true,
}

export const TEST_ADMIN = {
  id: 'u-admin',
  username: 'admin',
  role: 'admin' as const,
  is_active: true,
}

export function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

/** Войти без сети: напрямую положить состояние auth-store и токены. */
export function loginAs(user: typeof TEST_USER | typeof TEST_ADMIN = TEST_USER): void {
  tokens.setPair('test-access', 'test-refresh')
  useAuth.setState({
    user,
    status: 'authenticated',
    loginError: null,
    loginBusy: false,
  })
}

export function resetAuth(): void {
  tokens.clear()
  useAuth.setState({
    user: null,
    status: 'anonymous',
    loginError: null,
    loginBusy: false,
  })
}

type Route = (url: string, init: RequestInit) => Response | Promise<Response>

/**
 * Подмена fetch роутером: `routes` — объект «метод+путь → ответ».
 * Незнакомые GET/POST ловятся и падают с понятной ошибкой в тесте.
 */
export function mockApi(routes: Record<string, Route | unknown>) {
  const calls: { url: string; init: RequestInit }[] = []

  const spy = vi.fn((input: RequestInfo | URL, init: RequestInit = {}) => {
    const url = String(input)
    calls.push({ url, init })

    // путь без query: «/api/sessions» не должен матчить «/api/sessions/s-1»
    const pathname = url.split('?')[0] ?? url
    for (const [key, handler] of Object.entries(routes)) {
      const [method = 'GET', path = ''] = key.split(' ')
      const requestMethod = (init.method ?? 'GET').toUpperCase()
      if (requestMethod !== method.toUpperCase()) continue
      if (pathname !== path && !url.includes(`${path}?`)) continue
      if (typeof handler === 'function') {
        return Promise.resolve(handler(url, init) as Response)
      }
      // handler может быть уже готовым Response (например, json(..., 503))
      return Promise.resolve(handler instanceof Response ? handler : json(handler))
    }

    return Promise.reject(
      new Error(`Немокнутый запрос в тесте: ${init.method ?? 'GET'} ${url}`),
    )
  })

  vi.stubGlobal('fetch', spy)
  return { spy, calls }
}

/** Найти вызов fetch по подстроку пути. */
export function findCall(calls: { url: string; init: RequestInit }[], path: string) {
  return calls.find((call) => call.url.includes(path))
}
