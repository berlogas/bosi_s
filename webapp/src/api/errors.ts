/**
 * Единая ошибка API для всего интерфейса.
 *
 * Повторяет контракт backend-клиента `ApiError`: UI показывает
 * `message` (русский текст), а `detail`/`meta` уходят в раскрытие подробностей.
 * `meta` несёт лимиты бэкенда — из него рисуется «(лимит: N)».
 */

export interface ApiErrorInit {
  status?: number | null
  detail?: string | null
  meta?: Record<string, unknown> | null
}

export class ApiError extends Error {
  /** HTTP-статус; null — ответ не получен (сеть, таймаут). */
  readonly status: number | null
  /** Техническая деталь из тела ответа (для раскрытия в UI). */
  readonly detail: string | null
  /** Метаданные бэкенда: лимиты, retry_after и т.п. */
  readonly meta: Record<string, unknown> | null

  constructor(message: string, init: ApiErrorInit = {}) {
    super(message)
    this.name = 'ApiError'
    this.status = init.status ?? null
    this.detail = init.detail ?? null
    this.meta = init.meta ?? null
  }

  /** «Сессия истекла» — сигнатура, по которой UI уводит на экран входа. */
  get isAuthError(): boolean {
    return this.status === 401
  }
}

/** Собрать понятный текст из тела ошибки — 1-в-1 как `_explain` в api.py. */
export function explainError(
  status: number,
  body: unknown,
  rawText: string,
): { message: string; detail: string | null; meta: Record<string, unknown> | null } {
  const fallback = `Ошибка ${status}`

  // Тело не-JSON: текст (обрезанный) либо общий fallback.
  if (body === undefined) {
    const detail = rawText.slice(0, 300) || null
    return { message: detail ?? fallback, detail, meta: null }
  }

  // Тело — список/строка: repr, как str(body) в Python.
  // Важно: массив в JS — typeof 'object', но это не dict → ветка _repr_.
  if (Array.isArray(body) || typeof body !== 'object' || body === null) {
    const detail = (typeof body === 'string' ? body : JSON.stringify(body)).slice(
      0,
      300,
    )
    return { message: detail || fallback, detail, meta: null }
  }

  const record = body as Record<string, unknown>
  // detail=None && error есть → берем error, как `body.get("detail") or
  // body.get("error")` в api.py; если оба пусты — fallback («Ошибка N").
  const rawDetail = record['detail'] ?? record['error']
  const detail =
    typeof rawDetail === 'string' && rawDetail.length > 0 ? rawDetail : null
  const rawMeta = record['meta']
  const meta =
    typeof rawMeta === 'object' && rawMeta !== null
      ? (rawMeta as Record<string, unknown>)
      : null
  const limit = meta?.['limit']

  const base = detail || fallback
  return {
    message:
      limit !== undefined && limit !== null
        ? `${base} (лимит: ${String(limit)})`
        : base,
    detail,
    meta,
  }
}
