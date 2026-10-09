/**
 * HTTP-клиент к backend API.
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
  AuditLogEntry,
  CancelTaskResponse,
  ChatQueryResponse,
  DocumentBatchResult,
  DocumentOut,
  DraftAnalysis,
  GenerateRequest,
  GenerateResult,
  MessagePage,
  ProjectDocumentItem,
  ProjectOut,
  ProjectProgress,
  ProjectSection,
  QuickQueryResponse,
  SearchMode,
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
/** Схема openapi: ExportFormat = markdown | docx | zip. */
type ExportFormat = components['schemas']['ExportFormat']
/** Схема openapi: scope сброса состояния. */
type ResetScope = components['schemas']['ResetRequest']['scope']
type ResetPlan = components['schemas']['ResetPlanOut']
type ResetResult = components['schemas']['ResetResultOut']

/** Резервные копии: список + план следующей + результат создания. */
type BackupEntry = components['schemas']['BackupEntryOut']
type BackupPlan = components['schemas']['BackupPlanOut']
type BackupListing = components['schemas']['BackupListOut']
type BackupResult = components['schemas']['BackupResultOut']

/** Inbox: папка-приёмник и журнал прогонов массового добавления. */
type InboxFile = components['schemas']['InboxFileOut']
type InboxRun = components['schemas']['InboxRunOut']
type InboxStatus = components['schemas']['InboxStatusOut']

export type {
  BackupEntry,
  BackupListing,
  BackupPlan,
  BackupResult,
  InboxFile,
  InboxRun,
  InboxStatus,
  ResetPlan,
  ResetResult,
  ResetScope,
}

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
  /**
   * multipart: процент загрузки (0–100). Наличие колбэка включает
   * XHR-транспорт — fetch не умеет отдавать прогресс отправки тела.
   */
  onProgress?: (percent: number) => void
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

    // прогресс отправки возможен только через XHR (см. RequestOptions.onProgress)
    if (opts.form !== undefined && opts.onProgress) {
      return this.xhrUpload(path, opts, headers)
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
   * multipart через XHR: даёт upload.onprogress (доля отправленных байтов).
   * Ответ собирается в Response, чтобы refresh/explain-логика request()
   * работала без изменений.
   */
  private xhrUpload(
    path: string,
    opts: RequestOptions,
    headers: Record<string, string>,
  ): Promise<Response> {
    const timeoutMs = opts.timeoutMs ?? DEFAULT_TIMEOUT_MS
    const where = typeof window === 'undefined' ? 'backend' : window.location.origin
    return new Promise<Response>((resolve, reject) => {
      const xhr = new XMLHttpRequest()
      xhr.open(opts.method ?? 'POST', buildUrl(path, opts.query))
      for (const [name, value] of Object.entries(headers)) {
        xhr.setRequestHeader(name, value) // без Content-Type: boundary сам
      }
      xhr.timeout = timeoutMs
      xhr.responseType = 'text'
      if (xhr.upload) {
        xhr.upload.onprogress = (event) => {
          if (event.lengthComputable && event.total > 0) {
            opts.onProgress?.(Math.round((event.loaded / event.total) * 100))
          }
        }
      }
      xhr.onload = () => {
        resolve(
          new Response(xhr.responseText || null, {
            status: xhr.status,
            headers: {
              'Content-Type':
                xhr.getResponseHeader('Content-Type') ?? 'application/json',
            },
          }),
        )
      }
      xhr.onerror = () =>
        reject(
          new ApiError(`Backend недоступен (${where}). Проверьте, что он запущен.`),
        )
      xhr.ontimeout = () =>
        reject(
          new ApiError(
            `Backend не ответил за ${Math.round(timeoutMs / 1000)} с. Проверьте, что он запущен.`,
          ),
        )
      xhr.onabort = () =>
        reject(new DOMException('The operation was aborted.', 'AbortError'))
      if (opts.signal) {
        if (opts.signal.aborted) {
          xhr.abort()
        } else {
          opts.signal.addEventListener('abort', () => xhr.abort(), { once: true })
        }
      }
      xhr.send(opts.form ?? null)
    })
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

  /** Убрать завершённые задачи из реестра (только админ). */
  clearFinishedTasks(): Promise<void> {
    return this.request('/api/tasks/clear', { method: 'POST' })
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

  /** История диалога сессии (старшие первыми; limit до 500). */
  messages(
    sessionId: string,
    options: { limit?: number; offset?: number } = {},
  ): Promise<MessagePage> {
    return this.request('/api/chat/messages', {
      query: { session_id: sessionId, limit: options.limit, offset: options.offset },
    })
  }

  /** Удалить сообщение вместе с парой (вопрос+ответ — одна операция). */
  deleteMessage(messageId: string): Promise<void> {
    return this.request(`/api/chat/messages/${messageId}`, { method: 'DELETE' })
  }

  /** Очистить всю переписку сессии (документы и заметки не трогаем). */
  clearMessages(sessionId: string): Promise<void> {
    return this.request('/api/chat/messages', {
      method: 'DELETE',
      query: { session_id: sessionId },
    })
  }

  /** Синхронный вопрос по сессии — ждём ответа (долгий, LLM). */
  chatQuery(
    sessionId: string,
    query: string,
    mode: SearchMode = 'hybrid',
  ): Promise<ChatQueryResponse> {
    return this.request('/api/chat/query', {
      method: 'POST',
      json: { session_id: sessionId, query, mode, k: 10, max_sources: 5 },
      timeoutMs: 600_000, // в api.py у chat timeout=3600
    })
  }

  /** Фоновый вопрос: возвращается task_id, UI опрашивает /api/tasks/{id}. */
  chatQueryAsync(
    sessionId: string,
    query: string,
    mode: SearchMode = 'hybrid',
  ): Promise<{ task_id: string }> {
    return this.request('/api/chat/query-async', {
      method: 'POST',
      json: { session_id: sessionId, query, mode, k: 10, max_sources: 5 },
      timeoutMs: 30_000,
    })
  }

  /** «Точка возврата»: снапшот UI + заметка (автосохранение смены вкладки). */
  saveState(
    sessionId: string,
    payload: {
      snapshot?: Record<string, unknown>
      resume_note?: string | null
      action_label?: string
      force?: boolean
    },
  ): Promise<SessionOut> {
    return this.request(`/api/sessions/${sessionId}/state`, {
      method: 'PUT',
      json: {
        snapshot: payload.snapshot,
        resume_note: payload.resume_note,
        action_label: payload.action_label,
        force: payload.force ?? false,
      },
    })
  }

  // -------------------------------------------------------------- документы
  /** Реестр документов сессии (паритет session_documents в api.py). */
  sessionDocuments(sessionId: string, category?: string): Promise<DocumentOut[]> {
    return this.request(`/api/sessions/${sessionId}/documents`, {
      query: { category },
    })
  }

  /** Добавить файл с диска по пути (ограничен каталогом сессии). */
  addDocumentByPath(
    sessionId: string,
    path: string,
    options: { category?: string; tags?: string[] } = {},
  ): Promise<DocumentOut> {
    return this.request(`/api/sessions/${sessionId}/documents/path`, {
      method: 'POST',
      json: { path, category: options.category, tags: options.tags ?? [] },
      // индексация файла — минуты (upload в api.py тоже щадящий таймаут)
      timeoutMs: 600_000,
    })
  }

  /** Загрузка файлов (multipart) — паритет upload_session_documents. */
  uploadDocuments(
    sessionId: string,
    files: File[],
    options: {
      category?: string
      tags?: string
      /** % отправленных байтов (0–100); включает XHR-транспорт. */
      onProgress?: (percent: number) => void
    } = {},
  ): Promise<DocumentBatchResult> {
    const form = new FormData()
    for (const file of files) form.append('files', file, file.name)
    form.append('category', options.category ?? 'temp_literature')
    form.append('tags', options.tags ?? '')
    return this.request(`/api/sessions/${sessionId}/documents/upload`, {
      method: 'POST',
      form,
      timeoutMs: 600_000,
      onProgress: options.onProgress,
    })
  }

  deleteDocument(sessionId: string, documentId: string): Promise<void> {
    return this.request(`/api/sessions/${sessionId}/documents/${documentId}`, {
      method: 'DELETE',
    })
  }

  // ---------------------------------------------------------------- проекты
  projects(sessionId: string): Promise<ProjectOut[]> {
    return this.request(`/api/sessions/${sessionId}/projects`)
  }

  createProject(
    sessionId: string,
    title: string,
    targetJournal?: string,
  ): Promise<ProjectOut> {
    return this.request(`/api/sessions/${sessionId}/projects`, {
      method: 'POST',
      json: { title, target_journal: targetJournal || null },
    })
  }

  patchProject(
    sessionId: string,
    projectId: string,
    fields: { status?: string; title?: string; target_journal?: string },
  ): Promise<ProjectOut> {
    return this.request(`/api/sessions/${sessionId}/projects/${projectId}`, {
      method: 'PATCH',
      json: fields,
    })
  }

  deleteProject(sessionId: string, projectId: string): Promise<void> {
    return this.request(`/api/sessions/${sessionId}/projects/${projectId}`, {
      method: 'DELETE',
    })
  }

  sections(sessionId: string, projectId: string): Promise<ProjectSection[]> {
    return this.request(`/api/sessions/${sessionId}/projects/${projectId}/sections`)
  }

  /** Ручная правка раздела (content_md / notes / word_target). */
  saveSection(
    sessionId: string,
    projectId: string,
    name: string,
    fields: { content_md?: string; notes?: string },
  ): Promise<ProjectSection> {
    return this.request(
      `/api/sessions/${sessionId}/projects/${projectId}/sections/${encodeURIComponent(name)}`,
      { method: 'PUT', json: fields },
    )
  }

  projectDocuments(
    sessionId: string,
    projectId: string,
  ): Promise<ProjectDocumentItem[]> {
    return this.request(`/api/sessions/${sessionId}/projects/${projectId}/documents`)
  }

  bindDocument(
    sessionId: string,
    projectId: string,
    documentId: string,
    role: string = 'reference',
  ): Promise<void> {
    return this.request(`/api/sessions/${sessionId}/projects/${projectId}/documents`, {
      method: 'POST',
      json: { document_id: documentId, role },
    })
  }

  unbindDocument(
    sessionId: string,
    projectId: string,
    documentId: string,
  ): Promise<void> {
    return this.request(
      `/api/sessions/${sessionId}/projects/${projectId}/documents/${documentId}`,
      { method: 'DELETE' },
    )
  }

  /** Генерация раздела/анализ — синхронный, ждём (LLM, минуты). */
  generate(
    sessionId: string,
    projectId: string,
    payload: GenerateRequest,
  ): Promise<GenerateResult> {
    return this.request(`/api/sessions/${sessionId}/projects/${projectId}/generate`, {
      method: 'POST',
      json: payload,
      timeoutMs: 600_000,
    })
  }

  /** Разбор черновика без LLM: быстрый, детерминированный. */
  draftAnalysis(sessionId: string, projectId: string): Promise<DraftAnalysis> {
    return this.request(
      `/api/sessions/${sessionId}/projects/${projectId}/draft-analysis`,
    )
  }

  projectProgress(sessionId: string, projectId: string): Promise<ProjectProgress> {
    return this.request(`/api/sessions/${sessionId}/projects/${projectId}/progress`)
  }

  /** Экспорт статьи — отдаёт готовый файл (blob скачивается в UI). */
  exportProjectRaw(
    sessionId: string,
    projectId: string,
    fmt: ExportFormat,
  ): Promise<Response> {
    return this.request(`/api/sessions/${sessionId}/projects/${projectId}/export`, {
      query: { fmt },
      raw: true,
      timeoutMs: 120_000,
    })
  }

  // ------------------------------------------------------------ админка
  adminUsers(): Promise<UserOut[]> {
    return this.request('/api/admin/users')
  }

  adminCreateUser(fields: {
    username: string
    password: string
    role: string
    full_name?: string
    email?: string
  }): Promise<UserOut> {
    return this.request('/api/admin/users', { method: 'POST', json: fields })
  }

  adminUpdateUser(
    userId: string,
    fields: {
      username?: string
      full_name?: string
      role?: string
      password?: string
      is_active?: boolean
      email?: string
    },
  ): Promise<UserOut> {
    return this.request(`/api/admin/users/${userId}`, {
      method: 'PATCH',
      json: fields,
    })
  }

  /**
   * Удаление пользователя. Необратимо: вместе с учёткой каскадно удаляются
   * его сессии, сообщения, документы и проекты (ondelete=CASCADE).
   */
  adminDeleteUser(userId: string): Promise<void> {
    return this.request(`/api/admin/users/${userId}`, { method: 'DELETE' })
  }

  adminAudit(
    options: { limit?: number; offset?: number; action?: string } = {},
  ): Promise<AuditLogEntry[]> {
    return this.request('/api/admin/audit', {
      query: {
        limit: options.limit ?? 200,
        offset: options.offset,
        action: options.action,
      },
    })
  }

  adminDocuments(): Promise<DocumentOut[]> {
    return this.request('/api/admin/documents')
  }

  adminAddPath(path: string): Promise<DocumentOut> {
    return this.request('/api/admin/documents/path', {
      method: 'POST',
      json: { path },
      timeoutMs: 600_000,
    })
  }

  adminUpload(files: File[], tags = ''): Promise<DocumentBatchResult> {
    const form = new FormData()
    for (const file of files) form.append('files', file, file.name)
    form.append('tags', tags)
    return this.request('/api/admin/documents/upload', {
      method: 'POST',
      form,
      timeoutMs: 600_000,
    })
  }

  adminDeleteDocument(documentId: string): Promise<void> {
    return this.request(`/api/admin/documents/${documentId}`, { method: 'DELETE' })
  }

  adminReindex(): Promise<{ status?: string }> {
    return this.request('/api/admin/documents/reindex', {
      method: 'POST',
      timeoutMs: 600_000,
    })
  }

  // ------------------------------------------------------------------ inbox
  /** Что лежит в папке-приёмнике: включает кнопку в UI. */
  adminInboxStatus(): Promise<InboxStatus> {
    return this.request('/api/admin/inbox/status')
  }

  /** Обработать содержимое inbox. Долгая операция — увеличенный таймаут. */
  adminInboxScan(): Promise<{ run: InboxRun; inbox_dir: string }> {
    return this.request('/api/admin/inbox/scan', {
      method: 'POST',
      timeoutMs: 600_000,
    })
  }

  /** Журнал прогонов: последние по дате, с файлами внутри. */
  adminInboxRuns(limit = 20): Promise<InboxRun[]> {
    return this.request('/api/admin/inbox/runs', { query: { limit } })
  }

  /** Очистить каталог rejected (причины остаются в журнале). */
  adminClearRejected(): Promise<{ removed: number }> {
    return this.request('/api/admin/inbox/rejected', { method: 'DELETE' })
  }

  // --------------------------------------------------------------- сброс
  /** План сброса: что именно будет удалено. Ничего не меняет. */
  adminResetPreview(scope: ResetScope, includeModels = false): Promise<ResetPlan> {
    return this.request('/api/admin/reset/preview', {
      query: { scope, include_models: includeModels },
    })
  }

  /** Выполнить сброс. Требует точной фразы подтверждения из плана. */
  adminReset(fields: {
    scope: ResetScope
    confirm: string
    include_models?: boolean
  }): Promise<ResetResult> {
    return this.request('/api/admin/reset', {
      method: 'POST',
      json: fields,
      timeoutMs: 600_000,
    })
  }

  // -------------------------------------------------------- резервные копии
  /** Список копий и план следующей (что и сколько займёт). */
  adminBackups(): Promise<BackupListing> {
    return this.request('/api/admin/backup', { timeoutMs: 60_000 })
  }

  /**
   * Снять копию. На больших данных операция долгая, поэтому таймаут
   * увеличен до 10 минут — как и у реиндексации.
   */
  adminCreateBackup(keep?: number): Promise<BackupResult> {
    return this.request('/api/admin/backup', {
      method: 'POST',
      json: { keep },
      timeoutMs: 600_000,
    })
  }

  adminDeleteBackup(name: string): Promise<void> {
    return this.request(`/api/admin/backup/${encodeURIComponent(name)}`, {
      method: 'DELETE',
    })
  }
}

export const client = new ApiClient()
