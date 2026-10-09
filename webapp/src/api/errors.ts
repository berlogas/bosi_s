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

/** Русские тексты вместо стандартных HTTP-причин. */
const STATUS_TEXT_RU: Record<number, string> = {
  400: 'Некорректный запрос',
  401: 'Требуется вход',
  403: 'Доступ запрещён',
  404: 'Не найдено',
  405: 'Метод не поддерживается',
  409: 'Конфликт состояния',
  413: 'Файл слишком большой',
  415: 'Неподдерживаемый тип данных',
  422: 'Некорректные данные запроса',
  429: 'Слишком много запросов',
  500: 'Внутренняя ошибка сервера',
  502: 'Сервис недоступен',
  503: 'Сервис временно недоступен',
  504: 'Сервис не отвечает',
}

/**
 * Стандартные фразы серверов и прокси («Not Found», «Method Not Allowed»).
 * Совпадение — по вхождению, регистр не важен: такие ответы приходят
 * plain-текстом, минуя JSON-обработчик на бэкенде (например, когда
 * запрос попал в nginx или в StaticFiles).
 */
const STD_PHRASES = [
  'not found',
  'no such file or directory',
  'page not found',
  'method not allowed',
  'bad request',
  'unauthorized',
  'forbidden',
  'conflict',
  'internal server error',
  'bad gateway',
  'service unavailable',
  'gateway timeout',
  'request timeout',
  'unsupported media type',
  'unprocessable entity',
  'too many requests',
]

/**
 * Перевести служебный английский текст. Наши собственные сообщения
 * («Сессия не найдена», «Папка-приёмник не найдена») не трогаем —
 * они информативнее общего «Не найдено».
 */
export function translateErrorText(text: string, status: number): string {
  const lower = text.trim().toLowerCase()
  if (!lower) return STATUS_TEXT_RU[status] ?? `Ошибка ${status}`
  const isStd = STD_PHRASES.some((phrase) => lower.includes(phrase))
  if (isStd) return STATUS_TEXT_RU[status] ?? text
  return text
}

/** Собрать понятный текст из тела ошибки — 1-в-1 как `_explain` в api.py. */
export function explainError(
  status: number,
  body: unknown,
  rawText: string,
): { message: string; detail: string | null; meta: Record<string, unknown> | null } {
  const fallback = STATUS_TEXT_RU[status] ?? `Ошибка ${status}`

  // Тело не-JSON: текст (обрезанный) либо общий fallback.
  if (body === undefined) {
    const raw = rawText.slice(0, 300)
    const detail = raw ? translateErrorText(raw, status) : null
    return { message: detail ?? fallback, detail, meta: null }
  }

  // Тело — список/строка: repr, как str(body) в Python.
  // Важно: массив в JS — typeof 'object', но это не dict → ветка _repr_.
  if (Array.isArray(body) || typeof body !== 'object' || body === null) {
    const text = (typeof body === 'string' ? body : JSON.stringify(body)).slice(
      0,
      300,
    )
    const detail = text ? translateErrorText(text, status) : null
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

  const base = detail ? translateErrorText(detail, status) : fallback
  return {
    message:
      limit !== undefined && limit !== null
        ? `${base} (лимит: ${String(limit)})`
        : base,
    detail,
    meta,
  }
}
