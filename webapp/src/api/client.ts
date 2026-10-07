/**
 * HTTP-клиент к backend API (аналог frontend/boasi_ui/api.py).
 *
 * Транспортный слой: страницы зовут `client.login(...)`, `client.me()` и т.д.
 * Все ошибки приводятся к `ApiError` с русским текстом (см. errors.ts).
 *
 * Ключевое отличие от Streamlit-версии: при 401 выполняется ОДИН общий
 * refresh (параллельные 401 ждут его в очереди), оригинальный запрос
 * повторяется; при провале — очистка токенов и событие `onUnauthorized`.
 */

import { ApiError, explainError } from './errors'
import type { components } from './schema'
import { tokens } from './tokens'
import type {
  CancelTaskResponse,
  QuickQueryResponse,
  SessionDetail,
  SessionOut,
  Task,
  TaskListResponse,
} from './types'

type UserOut = components['schemas']['UserOut']
type LoginResponse = components['schemas']['LoginResponse']
type TokenPair = components['schemas']['TokenPair']
type HealthResponse = components['schemas']['HealthResponse']
type SuggestionsResponse = components['schemas']['SuggestionsResponse']

/** Путь, на котором refresh самому себе не нужен (иначе рекурсия). */
const AUTH_PATHS = new Set(['/api/auth/login', '/api/auth/refresh', '/api/auth/logout'])

const DEFAULT_TIMEOUT_MS = 30_000

export type QueryValue = string | number | boolean | null | undefined

export interface RequestOptions {
  method?: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE'
  /** JSON-тело; одновременно с form нельзя. */
  json?: unknown
  /** multipart/form-data (upload); данные полей — в query/`form`. */
  form?: FormData
  query?: Record<string, QueryValue>
  /** мс; по умолчанию 30 000, как DEFAULT_TIMEOUT в api.py. */
  timeoutMs?: number
  /** внешний AbortSignal (отмена задачи из UI). */
  signal?: AbortSignal
  /** true → вернуть Response целиком (скачивание файлов). */
  raw?: boolean
  /** не пытаться рефрешить токены при 401 (сам refresh/logout). */
  noRefresh?: boolean
}

type UnauthorizedListener = () => void

function buildUrl(path: string, query?: Record<string, QueryValue>): string {
  if (!query) return path
  const params = new URLSearchParams()
  for (const [key, value] of Object.entries(query)) {
    if (value !== undefined && value !== null) params.set(key, String(value))
  }
  const qs = params.toString()
  return qs ? `${path}?${qs}` : path
}

function combineSignals(signals: (AbortSignal | undefined)[]): AbortSignal | undefined {
  const present = signals.filter((s): s is AbortSignal => s !== undefined)
  if (present.length === 0) return undefined
  if (present.length === 1) return present[0]
  return AbortSignal.any(present)
}

class ApiClient {
  private refreshPromise: Promise<boolean> | null = null
  private unauthorizedListeners: UnauthorizedListener[] = []

  /**
   * Подписка на «сессия кончилась»: UI чистит auth-store и уводит на /login.
   * Возвращает функцию отписки.
   */
  onUnauthorized(listener: UnauthorizedListener): () => void {
    this.unauthorizedListeners.push(listener)
    return () => {
      this.unauthorizedListeners = this.unauthorizedListeners.filter(
        (l) => l !== listener,
      )
    }
  }

  private notifyUnauthorized(): void {
    for (const listener of [...this.unauthorizedListeners]) listener()
  }

  /** Базовый запрос без refresh-логики (401 пробрасывается наружу). */
  private async rawRequest(path: string, opts: RequestOptions): Promise<Response> {
    const headers: Record<string, string> = {}
    const access = tokens.getAccess()
    if (access) headers['Authorization'] = `Bearer ${access}`

    let body: BodyInit | undefined
    if (opts.json !== undefined) {
      headers['Content-Type'] = 'application/json'
      body = JSON.stringify(opts.json)
    } else if (opts.form !== undefined) {
      body = opts.form // boundary подставит fetch
    }

    const signal = combineSignals([
      opts.signal,
      AbortSignal.timeout(opts.timeoutMs ?? DEFAULT_TIMEOUT_MS),
    ])

    try {
      return await fetch(buildUrl(path, opts.query), {
        method: opts.method ?? 'GET',
        headers,
        body,
        signal,
      })
    } catch (cause) {
      // Таймаут vs недоступность — тексты разные, иначе юзер не поймёт.
      const aborted = cause instanceof DOMException && cause.name === 'AbortError'
      const timedOut = cause instanceof DOMException && cause.name === 'TimeoutError'
      if (aborted && !timedOut) throw cause // отмена из UI — не ошибка API
      const where = typeof window === 'undefined' ? 'backend' : window.location.origin
      throw new ApiError(
        timedOut
          ? `Backend не ответил за ${Math.round((opts.timeoutMs ?? DEFAULT_TIMEOUT_MS) / 1000)} с. Проверьте, что он запущен.`
          : `Backend недоступен (${where}). Проверьте, что он запущен.`,
      )
    }
  }

  /**
   * Один общий refresh на всех: первый дошедший 401 запускает обновление,
   * остальные ждут тот же промис (иначе ротация refresh-токена вторым
   * запросом отвалила бы первый — бэкенд одноразовые токены хранит).
   */
  private refreshTokens(): Promise<boolean> {
    if (!this.refreshPromise) {
      this.refreshPromise = this.doRefresh().finally(() => {
        this.refreshPromise = null
      })
    }
    return this.refreshPromise
  }

  private async doRefresh(): Promise<boolean> {
    const refresh = tokens.getRefresh()
    if (!refresh) return false
    try {
      const response = await this.rawRequest('/api/auth/refresh', {
        method: 'POST',
        json: { refresh_token: refresh },
        noRefresh: true,
      })
      if (!response.ok) return false
      const pair = (await response.json()) as TokenPair
      tokens.setPair(pair.access_token, pair.refresh_token)
      return true
    } catch {
      // Сеть/таймаут на refresh: не гасим сессию — возможно, backend
      // перезапускается. Следующий запрос попробует ещё раз.
      return false
    }
  }

  async request<T>(path: string, opts: RequestOptions = {}): Promise<T> {
    let response = await this.rawRequest(path, opts)

    if (
      response.status === 401 &&
      !opts.noRefresh &&
      !AUTH_PATHS.has(path) &&
      tokens.getRefresh() !== null
    ) {
      const refreshed = await this.refreshTokens()
      if (refreshed) {
        response = await this.rawRequest(path, opts)
      } else {
        tokens.clear()
        this.notifyUnauthorized()
        throw new ApiError('Сессия истекла. Войдите заново.', { status: 401 })
      }
    }

    if (!response.ok) {
      if (response.status === 401) {
        // refresh нечего делать (нет токена / это сам auth-путь)
        throw new ApiError('Сессия истекла. Войдите заново.', { status: 401 })
      }
      const rawText = await response.text().catch(() => '')
      let body: unknown
      try {
        body = rawText ? JSON.parse(rawText) : undefined
      } catch {
        body = undefined
      }
      const explained = explainError(response.status, body, rawText)
      throw new ApiError(explained.message, {
        status: response.status,
        detail: explained.detail,
        meta: explained.meta,
      })
    }

    if (opts.raw) return response as unknown as T
    if (response.status === 204) return null as T

    const text = await response.text()
    if (!text) return null as T
    try {
      return JSON.parse(text) as T
    } catch {
      return text as T
    }
  }

  // ------------------------------------------------------------------ auth
  async login(username: string, password: string): Promise<UserOut> {
    const body = await this.request<LoginResponse>('/api/auth/login', {
      method: 'POST',
      json: { username, password },
      noRefresh: true,
    })
    tokens.setPair(body.tokens.access_token, body.tokens.refresh_token)
    return body.user
  }

  async logout(): Promise<void> {
    const refresh = tokens.getRefresh()
    if (refresh) {
      try {
        await this.request<null>('/api/auth/logout', {
          method: 'POST',
          json: { refresh_token: refresh },
          noRefresh: true,
        })
      } catch {
        // выход не должен падать из-за сети (как в api.py)
      }
    }
    tokens.clear()
  }

  me(): Promise<UserOut> {
    return this.request('/api/auth/me')
  }

  health(): Promise<HealthResponse> {
    return this.request('/api/health', { timeoutMs: 10_000 })
  }

  // -------------------------------------------------------------- сессии
  sessions(): Promise<SessionOut[]> {
    return this.request('/api/sessions')
  }

  createSession(title: string): Promise<SessionOut> {
    return this.request('/api/sessions', { method: 'POST', json: { title } })
  }

  sessionDetail(sessionId: string): Promise<SessionDetail> {
    return this.request(`/api/sessions/${sessionId}`)
  }

  patchSession(
    sessionId: string,
    fields: Record<string, unknown>,
  ): Promise<SessionOut> {
    return this.request(`/api/sessions/${sessionId}`, { method: 'PATCH', json: fields })
  }

  archiveSession(sessionId: string, note?: string): Promise<SessionOut> {
    return this.request(`/api/sessions/${sessionId}/archive`, {
      method: 'POST',
      query: note ? { note } : undefined,
    })
  }

  pauseSession(sessionId: string, note?: string): Promise<SessionOut> {
    return this.request(`/api/sessions/${sessionId}/pause`, {
      method: 'POST',
      query: note ? { note } : undefined,
    })
  }

  resumeSession(sessionId: string): Promise<SessionDetail> {
    return this.request(`/api/sessions/${sessionId}/resume`, { method: 'POST' })
  }

  // ---------------------------------------------------------------- задачи
  tasks(
    options: { sessionId?: string; activeOnly?: boolean } = {},
  ): Promise<TaskListResponse> {
    return this.request('/api/tasks', {
      query: {
        session_id: options.sessionId,
        active_only: options.activeOnly,
      },
    })
  }

  task(taskId: string): Promise<Task> {
    return this.request(`/api/tasks/${taskId}`)
  }

  cancelTask(taskId: string): Promise<CancelTaskResponse> {
    return this.request(`/api/tasks/${taskId}/cancel`, { method: 'POST' })
  }

  // ------------------------------------------------------------------ чат
  /** Быстрый вопрос по глобальной базе — долгий (LLM), щадящий таймаут. */
  quickQuery(
    query: string,
    options: { k?: number; noCache?: boolean } = {},
  ): Promise<QuickQueryResponse> {
    return this.request('/api/chat/quick-query', {
      method: 'POST',
      json: {
        query,
        k: options.k ?? 10,
        max_sources: 5,
        no_cache: options.noCache ?? false,
      },
      // LLM отвечает минуты; в api.py у quick_query timeout=3600
      timeoutMs: 600_000,
    })
  }

  async suggestQueries(query: string): Promise<string[]> {
    const body = await this.request<SuggestionsResponse>('/api/chat/suggest-queries', {
      query: { query },
      timeoutMs: 60_000,
    })
    return body.suggestions ?? []
  }
}

export const client = new ApiClient()
