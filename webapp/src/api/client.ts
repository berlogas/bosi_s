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
  GlobalDocumentOut,
  MessagePage,
  ProjectDocumentItem,
  ProjectOut,
  ProjectProgress,
  ProjectSection,
  SearchMode,
  SessionDetail,
  SessionOut,
  SessionResume,
  Task,
  TaskListResponse,
  SectionPlan,
  SectionVersion,
  VersionTree,
  SemanticDiff,
  TerminologyGlossaryEntry,
  CompiledManuscript,
  TerminologyCheckResult,
  StyleComplianceResult,
  PreGenerationCheckResult,
  SectionKind,
  SectionPlanStatus,
  BatchRegenerateResult,
} from './types'



type UserOut = components['schemas']['UserOut']
type LoginResponse = components['schemas']['LoginResponse']
type TokenPair = components['schemas']['TokenPair']
type HealthResponse = components['schemas']['HealthResponse']
type SuggestionsResponse = components['schemas']['SuggestionsResponse']
/** Схема openapi: ExportFormat = markdown | docx | zip. */
export type ExportFormat = components['schemas']['ExportFormat']
/** Группа журналов с общим способом изложения: ключ стиля для проекта. */
export type JournalStyleOut = components['schemas']['JournalStyleOut']
/** Шаблон промпта группы: под какие разделы он подходит. */
export type JournalTemplateOut = components['schemas']['JournalTemplateOut']
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

  resumeSession(sessionId: string): Promise<SessionResume> {
    return this.request(`/api/sessions/${sessionId}/resume`, { method: 'POST' })
  }

  // ---------------------------------------------------------------- задачи
  /**
   * URL SSE-канала задач для EventSource.
   *
   * EventSource не умеет задавать HTTP-заголовки, поэтому access-токен уходит
   * в query (`?access_token=`), а не в Authorization. Без токена подписка
   * бессмысленна (401) — возвращаем null, и вызывающий остаётся на поллинге.
   */
  taskEventsUrl(): string | null {
    const access = tokens.getAccess()
    if (!access) return null
    return `/api/tasks/events?access_token=${encodeURIComponent(access)}`
  }

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
  /** Быстрый вопрос по глобальной базе: отдаёт task_id, ответ считает фон. */
  quickQuery(
    query: string,
    options: { k?: number; noCache?: boolean } = {},
  ): Promise<{ task_id: string }> {
    return this.request('/api/chat/quick-query', {
      method: 'POST',
      json: {
        query,
        k: options.k ?? 10,
        max_sources: 5,
        no_cache: options.noCache ?? false,
      },
      // Запрос отвечает сразу: считает LLM в фоне, прогресс и отмена — через
      // /api/tasks/{id}. Долгий таймаут здесь означал бы «всё зависло» вместо
      // «считаем уже десять минут».
      timeoutMs: 30_000,
    })
  }

  /** История быстрых вопросов пользователя: переживает перезагрузку вкладки. */
  quickHistory(limit = 20): Promise<MessagePage> {
    return this.request('/api/chat/quick-history', { query: { limit } })
  }

  /** Очистить всю историю быстрых вопросов пользователя. */
  clearQuickHistory(): Promise<void> {
    return this.request('/api/chat/quick-history', { method: 'DELETE' })
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
      // Считает LLM в этом же запросе; отменять такой вопрос нельзя —
      // для интерактивного сценария есть chatQueryAsync с задачей и отменой.
      timeoutMs: 600_000,
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

  /** Стриминг ответа по токенам через SSE.
   *
   * Вызывает callback `onToken` для каждого фрагмента текста.
   * Возвращает полный ответ, когда поток завершится.
   */
  async chatStream(
    sessionId: string,
    query: string,
    mode: SearchMode = 'hybrid',
    onToken: (token: string) => void,
    onError?: (error: string) => void,
    onDone?: () => void,
  ): Promise<void> {
    const access = tokens.getAccess()
    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
    }
    if (access) headers['Authorization'] = `Bearer ${access}`

    const response = await fetch('/api/chat/stream', {
      method: 'POST',
      headers,
      body: JSON.stringify({
        session_id: sessionId,
        query,
        mode,
        k: 10,
        max_sources: 5,
      }),
    })

    if (!response.ok) {
      throw new Error(`Ошибка стриминга: ${response.status}`)
    }

    const reader = response.body?.getReader()
    if (!reader) {
      throw new Error('Нет тела ответа')
    }

    const decoder = new TextDecoder()
    let buffer = ''

    while (true) {
      const { value, done } = await reader.read()
      if (done) break

      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split('\n\n')
      buffer = lines.pop() ?? ''

      for (const line of lines) {
        if (!line.startsWith('data: ')) continue
        const payload = line.slice('data: '.length).trim()
        if (payload === '[DONE]') {
          onDone?.()
          return
        }
        try {
          const data = JSON.parse(payload)
          if (data.token) {
            onToken(data.token)
          }
          if (data.error) {
            onError?.(data.error)
            return
          }
        } catch {
          // игнорируем битые фрагменты
        }
      }
    }
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
    options: { category?: string; tags?: string[]; forceReindex?: boolean } = {},
  ): Promise<DocumentOut> {
    return this.request(`/api/sessions/${sessionId}/documents/path`, {
      method: 'POST',
      json: {
        path,
        category: options.category,
        tags: options.tags ?? [],
        force_reindex: options.forceReindex ?? false,
      },
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

  /**
   * Фоновая загрузка файлов: отвечает сразу `task_id`, индексация идёт в фоне.
   *
   * Индексация PDF на CPU занимает минуты: синхронный запрос держал бы
   * интерфейс на спиннере без возможности отмены. Прогресс и отмена — через
   * `/api/tasks/{id}`.
   */
  uploadDocumentsAsync(
    sessionId: string,
    files: File[],
    options: {
      category?: string
      tags?: string
      /** % отправленных байтов (0–100); включает XHR-транспорт. */
      onProgress?: (percent: number) => void
      /** Заменить прежние версии документов с теми же именами. */
      replace?: boolean
    } = {},
  ): Promise<{ task_id: string; total: number }> {
    const form = new FormData()
    for (const file of files) form.append('files', file, file.name)
    form.append('category', options.category ?? 'temp_literature')
    form.append('tags', options.tags ?? '')
    form.append('replace', options.replace ? 'true' : 'false')
    return this.request(`/api/sessions/${sessionId}/documents/upload-async`, {
      method: 'POST',
      form,
      // Ответ приходит сразу: файлы сохранены, индексация пошла в фоне.
      timeoutMs: 120_000,
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

  /** Группы журналов: выбор стиля задаёт промпт генерации. */
  journalStyles(): Promise<JournalStyleOut[]> {
    return this.request('/api/journal-styles')
  }

  /** Получить предложенный план разделов для стиля журнала */
  getSuggestedSectionPlan(styleKey: string): Promise<SectionPlan[]> {
    return this.request(`/api/journal-styles/${encodeURIComponent(styleKey)}/suggested-plan`)
  }

  createProject(
    sessionId: string,
    title: string,
    targetJournal?: string,
    language?: string,
  ): Promise<ProjectOut> {
    return this.request(`/api/sessions/${sessionId}/projects`, {
      method: 'POST',
      json: { title, target_journal: targetJournal || null, language: language || 'ru' },
    })
  }

  patchProject(
    sessionId: string,
    projectId: string,
    fields: {
      status?: string
      title?: string
      target_journal?: string
      language?: string
      order?: number
    },
  ): Promise<ProjectOut> {
    return this.request(`/api/sessions/${sessionId}/projects/${projectId}`, {
      method: 'PATCH',
      json: fields,
    })
  }

  setProjectStyleGuide(
    sessionId: string,
    projectId: string,
    documentId: string | null,
  ): Promise<{ project_id: string; style_guide_document_id: string | null }> {
    return this.request(`/api/sessions/${sessionId}/projects/${projectId}/style-guide`, {
      method: 'POST',
      json: { document_id: documentId },
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

  /** Перевести раздел статьи на целевой язык через LLM. */
  translateSection(
    sessionId: string,
    projectId: string,
    sectionName: string,
    targetLanguage: string,
    sourceLanguage?: string,
  ): Promise<ProjectSection> {
    return this.request(
      `/api/sessions/${sessionId}/projects/${projectId}/sections/${encodeURIComponent(sectionName)}/translate`,
      {
        method: 'POST',
        json: {
          target_language: targetLanguage,
          source_language: sourceLanguage,
        },
        timeoutMs: 600_000,
      },
    )
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
  /** Выгрузка статьи: markdown | docx | zip (в zip — библиография и sources). */
  downloadProject(
    sessionId: string,
    projectId: string,
    fmt: ExportFormat,
  ): Promise<{ blob: Blob; filename: string }> {
    return this.downloadFile(
      `/api/sessions/${sessionId}/projects/${projectId}/export`,
      { fmt },
    )
  }

  // ------------------------------------------------------------ SectionPlan / SectionVersion (новая система)
  /** Список планов разделов */
  sectionPlans(sessionId: string, projectId: string): Promise<SectionPlan[]> {
    return this.request(`/api/sessions/${sessionId}/projects/${projectId}/section-plans`)
  }

  /** Создать план раздела */
  createSectionPlan(
    sessionId: string,
    projectId: string,
    payload: { name: string; kind?: SectionKind; order?: number; word_target?: number; notes?: string; language?: string; required?: boolean; depends_on?: string[] },
  ): Promise<{ id: string; name: string }> {
    return this.request(`/api/sessions/${sessionId}/projects/${projectId}/section-plans`, {
      method: 'POST',
      json: payload,
    })
  }

  /** Обновить план раздела */
  updateSectionPlan(
    sessionId: string,
    projectId: string,
    planId: string,
    payload: Partial<{ name: string; kind: SectionKind; order: number; word_target: number; notes: string; language: string; required: boolean; depends_on: string[]; status: SectionPlanStatus }>,
  ): Promise<{ id: string; status: string }> {
    return this.request(`/api/sessions/${sessionId}/projects/${projectId}/section-plans/${planId}`, {
      method: 'PATCH',
      json: payload,
    })
  }

  /** Удалить план раздела */
  deleteSectionPlan(sessionId: string, projectId: string, planId: string): Promise<void> {
    return this.request(`/api/sessions/${sessionId}/projects/${projectId}/section-plans/${planId}`, {
      method: 'DELETE',
    })
  }

  /** Синхронизировать старый JSON в новые SectionPlan */
  syncSectionPlans(sessionId: string, projectId: string): Promise<{ synced: number; plans: Array<{ id: string; name: string }> }> {
    return this.request(`/api/sessions/${sessionId}/projects/${projectId}/section-plans/sync`, {
      method: 'POST',
    })
  }

  /** Генерация раздела v2 (через SectionAgent) */
  generateSectionV2(
    sessionId: string,
    projectId: string,
    payload: {
      section: string
      question: string
      notes?: string
      word_target?: number
      use_cache?: boolean
      kind?: string
    },
  ): Promise<SectionVersion> {
    return this.request(`/api/sessions/${sessionId}/projects/${projectId}/generate-v2`, {
      method: 'POST',
      json: payload,
      timeoutMs: 600_000,
    })
  }

  /** Перевести раздел v2 (новая система) */
  translateSectionV2(
    sessionId: string,
    projectId: string,
    planId: string,
    targetLanguage: string,
    versionId?: string,
  ): Promise<SectionVersion> {
    return this.request(`/api/sessions/${sessionId}/projects/${projectId}/section-plans/${planId}/translate`, {
      method: 'POST',
      json: { target_language: targetLanguage, version_id: versionId },
      timeoutMs: 300_000,
    })
  }

  /** История версий раздела (дерево) */
  sectionHistory(sessionId: string, projectId: string, planId: string): Promise<VersionTree> {
    return this.request(`/api/sessions/${sessionId}/projects/${projectId}/section-plans/${planId}/history`)
  }

  /** Все версии разделов проекта — реальная история генераций. */
  projectSectionVersions(
    sessionId: string,
    projectId: string,
  ): Promise<SectionVersion[]> {
    return this.request(`/api/sessions/${sessionId}/projects/${projectId}/section-versions`)
  }

  /** Сохранить текст раздела, набранный в редакторе. */
  saveSectionContent(
    sessionId: string,
    projectId: string,
    planId: string,
    contentMd: string,
  ): Promise<SectionVersion> {
    return this.request(
      `/api/sessions/${sessionId}/projects/${projectId}/section-plans/${planId}/content`,
      { method: 'PUT', json: { content_md: contentMd } },
    )
  }

  /** Семантический diff двух версий */
  diffSectionVersions(
    sessionId: string,
    projectId: string,
    fromVersion: string,
    toVersion: string,
  ): Promise<SemanticDiff> {
    return this.request(`/api/sessions/${sessionId}/projects/${projectId}/section-versions/diff`, {
      query: { from_version: fromVersion, to_version: toVersion },
    })
  }

  /** Откатить раздел к версии */
  rollbackSection(
    sessionId: string,
    projectId: string,
    planId: string,
    versionId: string,
  ): Promise<SectionVersion> {
    return this.request(`/api/sessions/${sessionId}/projects/${projectId}/section-plans/${planId}/rollback`, {
      method: 'POST',
      json: { version_id: versionId },
    })
  }

  /** Одобрить версию раздела */
  approveSection(
    sessionId: string,
    projectId: string,
    planId: string,
    versionId: string,
  ): Promise<SectionVersion> {
    return this.request(`/api/sessions/${sessionId}/projects/${projectId}/section-plans/${planId}/approve`, {
      method: 'POST',
      json: { version_id: versionId },
    })
  }

  /** Глоссарий терминов */
  getGlossary(sessionId: string, projectId: string): Promise<TerminologyGlossaryEntry[]> {
    return this.request(`/api/sessions/${sessionId}/projects/${projectId}/glossary`)
  }

  /** Добавить термин в глоссарий */
  addGlossaryEntry(
    sessionId: string,
    projectId: string,
    payload: { term: string; translations?: Record<string, string>; definition?: string },
  ): Promise<{ id: string; term: string }> {
    return this.request(`/api/sessions/${sessionId}/projects/${projectId}/glossary`, {
      method: 'POST',
      json: payload,
    })
  }

  /** Удалить термин из глоссария */
  deleteGlossaryEntry(sessionId: string, projectId: string, entryId: string): Promise<void> {
    return this.request(`/api/sessions/${sessionId}/projects/${projectId}/glossary/${entryId}`, {
      method: 'DELETE',
    })
  }

  /** Пакетная перегенерация устаревших разделов */
  batchRegenerateSections(
    sessionId: string,
    projectId: string,
    force = false,
  ): Promise<BatchRegenerateResult> {
    return this.request(`/api/sessions/${sessionId}/projects/${projectId}/batch-regenerate`, {
      method: 'POST',
      json: { force },
      timeoutMs: 1_800_000, // 30 min
    })
  }

  /** Сборка полного манускрипта */
  compileManuscript(
    sessionId: string,
    projectId: string,
    language?: string,
    includeUnapproved = false,
  ): Promise<CompiledManuscript> {
    return this.request(`/api/sessions/${sessionId}/projects/${projectId}/manuscript`, {
      query: { language, include_unapproved: includeUnapproved },
    })
  }

  /** Проверка согласованности терминологии */
  checkTerminologyConsistency(sessionId: string, projectId: string): Promise<TerminologyCheckResult> {
    return this.request(`/api/sessions/${sessionId}/projects/${projectId}/terminology-check`)
  }

  /** Проверка соответствия стилю журнала */
  checkStyleCompliance(
    sessionId: string,
    projectId: string,
    sectionPlanId: string,
    versionId?: string,
  ): Promise<StyleComplianceResult> {
    return this.request(`/api/sessions/${sessionId}/projects/${projectId}/style-compliance`, {
      method: 'POST',
      json: { section_plan_id: sectionPlanId, version_id: versionId },
      timeoutMs: 120_000,
    })
  }

  /** Предварительная проверка перед генерацией */
  preGenerationCheck(
    sessionId: string,
    projectId: string,
    sectionName: string,
    question: string,
    requiredSources = 3,
  ): Promise<PreGenerationCheckResult> {
    return this.request(`/api/sessions/${sessionId}/projects/${projectId}/pre-generation-check`, {
      method: 'POST',
      json: { section_name: sectionName, question, required_sources: requiredSources },
      timeoutMs: 60_000,
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
    options: {
      limit?: number
      offset?: number
      action?: string
      /** Период: ISO-дата, с которой нужны записи. */
      since?: string
    } = {},
  ): Promise<AuditLogEntry[]> {
    return this.request('/api/admin/audit', {
      query: {
        limit: options.limit ?? 200,
        offset: options.offset,
        action: options.action,
        since: options.since,
      },
    })
  }

  adminDocuments(): Promise<DocumentOut[]> {
    return this.request('/api/admin/documents')
  }

  /**
   * Глобальная база знаний для чтения: доступна любому вошедшему, в том числе
   * исследователю, который не может её наполнять. Отдельный маршрут вместо
   * `/api/admin/documents` — там `require_admin`, и список был виден только
   * администратору.
   */
  globalDocuments(
    options: { q?: string | undefined; category?: string | undefined } = {},
  ): Promise<GlobalDocumentOut[]> {
    // Пустой поиск не отправляем: без него первый запрос идёт без фильтра,
    // а с ним — лишний параметр в URL.
    const q = typeof options.q === 'string' ? options.q.trim() || undefined : undefined
    return this.request('/api/documents', {
      query: { q, category: options.category },
    })
  }

  globalDocumentsStats(): Promise<{
    total: number
    storage_bytes: number
    by_category: Record<string, number>
  }> {
    return this.request('/api/documents/stats')
  }

  adminAddPath(path: string, options: { forceReindex?: boolean } = {}): Promise<DocumentOut> {
    return this.request('/api/admin/documents/path', {
      method: 'POST',
      json: { path, force_reindex: options.forceReindex ?? false },
      timeoutMs: 600_000,
    })
  }

  adminUpload(files: File[], tags = '', options: {
    /** % отправленных байтов (0–100); включает XHR-транспорт. */
    onProgress?: (percent: number) => void
    /**
     * Заменить прежние версии документов с теми же именами.
     *
     * Дедуп PaperQA идёт по содержимому, поэтому обновлённый файл иначе
     * лёг бы вторым документом, а старый остался бы в индексе.
     */
    replace?: boolean
  } = {}): Promise<DocumentBatchResult> {
    const form = new FormData()
    for (const file of files) form.append('files', file, file.name)
    form.append('tags', tags)
    form.append('replace', options.replace ? 'true' : 'false')
    return this.request('/api/admin/documents/upload', {
      method: 'POST',
      form,
      timeoutMs: 600_000,
      onProgress: options.onProgress,
    })
  }

  adminDeleteDocument(documentId: string): Promise<void> {
    return this.request(`/api/admin/documents/${documentId}`, { method: 'DELETE' })
  }

  /** Сводка по журналу: всего записей и границы по датам. */
  adminAuditStats(): Promise<{
    total: number
    oldest_at: string | null
    newest_at: string | null
  }> {
    return this.request('/api/admin/audit/stats')
  }

  /** Ссылка на CSV-выгрузку журнала (тот же период, что и в списке). */
  adminAuditExportUrl(since?: string): string {
    const params = new URLSearchParams({ limit: '10000' })
    if (since) params.set('since', since)
    return `/api/admin/audit/export?${params.toString()}`
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

  /**
   * Скачать бинарный ответ (выгрузка статьи). Обычный `request` тут не
   * годится: он пытается разобрать тело как JSON и теряет заголовки.
   * Имя файла берём из Content-Disposition — сервер уже транслитерирует
   * его для latin-1 и отдаёт оригинал в RFC 5987.
   */
  async downloadFile(
    path: string,
    query: Record<string, QueryValue> = {},
  ): Promise<{ blob: Blob; filename: string }> {
    const headers: Record<string, string> = {}
    const access = tokens.getAccess()
    if (access) headers['Authorization'] = `Bearer ${access}`

    const response = await fetch(buildUrl(path, query), {
      method: 'GET',
      headers,
      signal: AbortSignal.timeout(120_000),
    })
    if (!response.ok) {
      throw new ApiError(`Не удалось выгрузить файл (${response.status})`, {
        status: response.status,
      })
    }

    const disposition = response.headers.get('Content-Disposition') ?? ''
    const utf8 = disposition.match(/filename\*=UTF-8''([^;]+)/i)
    const plain = disposition.match(/filename="([^"]+)"/i)
    const filename = decodeURIComponent(utf8?.[1] ?? plain?.[1] ?? 'article')
    return { blob: await response.blob(), filename }
  }

  /** Очистить каталог rejected (причины остаются в журнале). */
  adminClearRejected(): Promise<{ removed: number }> {
    return this.request('/api/admin/inbox/rejected', { method: 'DELETE' })
  }

  /** Очистить весь журнал добавления (все прогоны и строки файлов). */
  adminClearJournal(): Promise<{ removed: number }> {
    return this.request('/api/admin/inbox/journal', { method: 'DELETE' })
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
