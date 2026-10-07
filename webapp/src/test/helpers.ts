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
type RouteResolver = (url: string, init: RequestInit) => Promise<Response>
type ProgressHandler = (event: {
  lengthComputable: boolean
  loaded: number
  total: number
}) => void

/**
 * Подмена fetch роутером: `routes` — объект «метод+путь → ответ».
 * Незнакомые GET/POST ловятся и падают с понятной ошибкой в тесте.
 *
 * Заодно ставит фейковый XMLHttpRequest — путь загрузки с прогрессом
 * (client.xhrUpload) ходит через XHR, иначе роутер его не видит.
 */
export function mockApi(routes: Record<string, Route | unknown>) {
  const calls: { url: string; init: RequestInit }[] = []

  const resolveRoute = (url: string, init: RequestInit): Promise<Response> => {
    calls.push({ url, init })

    // путь без query: «/api/sessions» не должен матчить «/api/sessions/s-1»
    const pathname = url.split('?')[0] ?? url
    for (const [key, handler] of Object.entries(routes)) {
      const [method = 'GET', path = ''] = key.split(' ')
      const requestMethod = (init.method ?? 'GET').toUpperCase()
      if (requestMethod !== method.toUpperCase()) continue
      if (pathname !== path && !url.includes(`${path}?`)) continue
      if (typeof handler === 'function') {
        return Promise.resolve(handler(url, init))
      }
      // handler может быть уже готовым Response (например, json(..., 503))
      return Promise.resolve(handler instanceof Response ? handler : json(handler))
    }

    return Promise.reject(
      new Error(`Немокнутый запрос в тесте: ${init.method ?? 'GET'} ${url}`),
    )
  }

  const spy = vi.fn((input: RequestInfo | URL, init: RequestInit = {}) =>
    resolveRoute(String(input), init),
  )
  vi.stubGlobal('fetch', spy)
  vi.stubGlobal('XMLHttpRequest', fakeXhrClass(resolveRoute))
  return { spy, calls }
}

/** Минимальный XHR: прогресс отправки + onload/onerror поверх роутера. */
function fakeXhrClass(resolveRoute: RouteResolver) {
  return class FakeXhr {
    upload: { onprogress: ProgressHandler | null } = { onprogress: null }
    onload: (() => void) | null = null
    onerror: (() => void) | null = null
    ontimeout: (() => void) | null = null
    onabort: (() => void) | null = null
    status = 0
    responseText = ''
    timeout = 0
    responseType = ''
    private method = 'GET'
    private url = ''
    private headers: Record<string, string> = {}

    open(method: string, url: string): void {
      this.method = method
      this.url = url
    }

    setRequestHeader(name: string, value: string): void {
      this.headers[name] = value
    }

    getResponseHeader(name: string): string | null {
      return name.toLowerCase() === 'content-type' ? 'application/json' : null
    }

    abort(): void {
      this.onabort?.()
    }

    send(body: BodyInit | null): void {
      // как в браузере: прогресс идёт до ответа сервера
      this.upload.onprogress?.({ lengthComputable: true, loaded: 50, total: 100 })
      void resolveRoute(this.url, { method: this.method, headers: this.headers, body })
        .then(async (response) => {
          this.status = response.status
          this.responseText = await response.text()
          this.upload.onprogress?.({
            lengthComputable: true,
            loaded: 100,
            total: 100,
          })
          this.onload?.()
        })
        .catch(() => this.onerror?.())
    }
  }
}

/** Найти вызов fetch по подстроку пути. */
export function findCall(calls: { url: string; init: RequestInit }[], path: string) {
  return calls.find((call) => call.url.includes(path))
}
