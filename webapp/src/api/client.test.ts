import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { client } from './client'
import { ApiError, explainError } from './errors'
import { hasStoredSession, tokens } from './tokens'

/** Управляемая подмена fetch. */
function mockFetch(
  routes: (url: string, init: RequestInit) => Response | Promise<Response>,
) {
  const spy = vi.fn((input: RequestInfo | URL, init?: RequestInit) =>
    Promise.resolve(routes(String(input), init ?? {})),
  )
  vi.stubGlobal('fetch', spy)
  return spy
}

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })

const user = {
  id: 'u1',
  username: 'ivan',
  role: 'researcher' as const,
  is_active: true,
}

const pair = (suffix: string) => ({
  access_token: `access-${suffix}`,
  refresh_token: `refresh-${suffix}`,
  token_type: 'bearer',
  expires_in: 1800,
})

beforeEach(() => {
  tokens.clear()
})

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe('ApiError / explainError', () => {
  it('берёт detail и лимит из тела (как _explain в api.py)', () => {
    const explained = explainError(
      409,
      { error: 'limit_exceeded', detail: 'Достигнут лимит сессий', meta: { limit: 5 } },
      '',
    )
    expect(explained.message).toBe('Достигнут лимит сессий (лимит: 5)')
    expect(explained.detail).toBe('Достигнут лимит сессий')
    expect(explained.meta).toEqual({ limit: 5 })
  })

  it('meta: null не роняет разбор (detail пуст → fallback)', () => {
    const explained = explainError(500, { detail: null, meta: null }, '')
    expect(explained.message).toBe('Ошибка 500')
    expect(explained.meta).toBeNull()
  })

  it('detail пуст, но error есть → берём error (как api.py)', () => {
    const explained = explainError(500, { error: 'internal_error', detail: null }, '')
    expect(explained.message).toBe('internal_error')
  })

  it('не-JSON тело → обрезанный текст', () => {
    const explained = explainError(502, undefined, 'x'.repeat(500))
    expect(explained.message).toHaveLength(300)
  })

  it('тело-список → строковое представление', () => {
    const explained = explainError(422, [{ msg: 'field required' }], '')
    expect(explained.message).toContain('field required')
  })
})

describe('клиент: login/me', () => {
  it('login сохраняет токены и возвращает user', async () => {
    mockFetch((url) => {
      if (url.endsWith('/api/auth/login')) return json({ user, tokens: pair('1') })
      throw new Error(`неожиданный запрос: ${url}`)
    })
    const logged = await client.login('ivan', 'secret')
    expect(logged.username).toBe('ivan')
    expect(tokens.getAccess()).toBe('access-1')
    expect(tokens.getRefresh()).toBe('refresh-1')
    expect(hasStoredSession()).toBe(true)
  })

  it('логин с неверным паролем → ApiError с русским текстом', async () => {
    mockFetch(() =>
      json({ error: 'forbidden', detail: 'Неверный логин или пароль', meta: {} }, 403),
    )
    await expect(client.login('ivan', 'wrong')).rejects.toMatchObject({
      name: 'ApiError',
      message: 'Неверный логин или пароль',
      status: 403,
    })
  })
})

describe('клиент: refresh-очередь', () => {
  it('401 → один refresh → повтор запроса', async () => {
    tokens.setPair('stale-access', 'refresh-1')
    let meCalls = 0
    const spy = mockFetch((url, init) => {
      if (url.endsWith('/api/auth/refresh')) return json(pair('2'))
      if (url.endsWith('/api/auth/me')) {
        const auth = (init.headers as Record<string, string>)['Authorization']
        meCalls += 1
        return auth === 'Bearer access-2'
          ? json(user)
          : json({ detail: 'token expired' }, 401)
      }
      throw new Error(`неожиданный запрос: ${url}`)
    })

    const me = await client.me()
    expect(me.username).toBe('ivan')
    expect(meCalls).toBe(2) // первый 401, после refresh — повтор
    expect(tokens.getAccess()).toBe('access-2')
    expect(tokens.getRefresh()).toBe('refresh-2') // ротация
    expect(
      spy.mock.calls.filter(([u]) => String(u).endsWith('/api/auth/refresh')),
    ).toHaveLength(1)
  })

  it('параллельные 401 ждут ОДИН refresh (ротация не гасит соседей)', async () => {
    tokens.setPair('stale', 'refresh-1')
    let refreshCalls = 0
    mockFetch((url, init) => {
      if (url.endsWith('/api/auth/refresh')) {
        refreshCalls += 1
        return json(pair('2'))
      }
      const auth = (init.headers as Record<string, string>)['Authorization']
      return auth === 'Bearer access-2'
        ? json({ ok: true })
        : json({ detail: 'expired' }, 401)
    })

    const results = await Promise.all([
      client.request('/api/sessions'),
      client.request('/api/tasks'),
      client.request('/api/health'),
    ])
    expect(results).toEqual([{ ok: true }, { ok: true }, { ok: true }])
    expect(refreshCalls).toBe(1)
  })

  it('провал refresh → токены очищены, событие onUnauthorized, ApiError 401', async () => {
    tokens.setPair('stale', 'refresh-dead')
    const onUnauthorized = vi.fn()
    const unsubscribe = client.onUnauthorized(onUnauthorized)
    mockFetch((url) => {
      // Реальный бэкенд: отозванный/неизвестный refresh → 404 NotFoundError
      // (repositories/users.py:rotate_refresh_token), не 401.
      if (url.endsWith('/api/auth/refresh'))
        return json(
          { error: 'not_found', detail: 'Refresh-токен не найден или отозван' },
          404,
        )
      return json({ detail: 'expired' }, 401)
    })

    await expect(client.me()).rejects.toMatchObject({ status: 401 })
    expect(onUnauthorized).toHaveBeenCalledTimes(1)
    expect(tokens.getAccess()).toBeNull()
    expect(hasStoredSession()).toBe(false)
    unsubscribe()
  })

  it('нет refresh-токена → сразу 401 без запроса на refresh', async () => {
    const spy = mockFetch(() => json({ detail: 'no token' }, 401))
    await expect(client.me()).rejects.toMatchObject({ status: 401 })
    expect(spy).toHaveBeenCalledTimes(1)
    expect(String(spy.mock.calls[0]?.[0])).not.toContain('/auth/refresh')
  })
})

describe('клиент: сетевые сбои', () => {
  it('backend недоступен → ApiError с подсказкой', async () => {
    vi.stubGlobal('fetch', () => Promise.reject(new TypeError('Failed to fetch')))
    await expect(client.health()).rejects.toSatisfy(
      (e: unknown) => e instanceof ApiError && e.message.includes('Backend недоступен'),
    )
  })

  it('401 на самом login не уходит в refresh-петлю', async () => {
    const spy = mockFetch(() => json({ detail: 'invalid' }, 401))
    await expect(client.login('a', 'b')).rejects.toMatchObject({ status: 401 })
    expect(spy).toHaveBeenCalledTimes(1)
  })
})
