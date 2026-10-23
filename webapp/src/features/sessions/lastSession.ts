/**
 * Последняя открытая сессия — для пункта меню «Текущая сессия».
 *
 * Хранится в `sessionStorage`: сессия работы не должна переживать закрытие
 * вкладки, и на общей машине чужие следы не остаются. Внутри значения лежит
 * id пользователя: сессия одного не подставляется другому — та же схема,
 * что в `boasi.project.drafts` и `boasi.chat.task`, где `sessionId` тоже
 * лежит внутри значения и проверяется при чтении.
 *
 * Значение пишется и читается только здесь: пункт меню и выход из аккаунта
 * работают с одним форматом, а разбирать JSON в двух местах не нужно.
 */

const KEY = 'boasi.lastSessionPath'

interface StoredSession {
  path: string
  userId: string
}

/** Путь сессии: `/s/<id>`. */
const SESSION_PATH = /^\/s\/[^/]+$/

/** Прочитать сохранённое значение; битое — как отсутствующее. */
function readStored(): StoredSession | null {
  try {
    const raw = window.sessionStorage.getItem(KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw) as Partial<StoredSession>
    if (typeof parsed.path !== 'string' || !SESSION_PATH.test(parsed.path)) {
      return null
    }
    if (typeof parsed.userId !== 'string' || !parsed.userId) return null
    return { path: parsed.path, userId: parsed.userId }
  } catch {
    // приватный режим браузера и отключённое хранилище: пункт останется
    // серым, но приложение работает
    return null
  }
}

/** Запомненная сессия пользователя; чужая сессия не показывается. */
export function readLastSessionPath(userId: string | null): string | null {
  if (!userId) return null
  const stored = readStored()
  return stored && stored.userId === userId ? stored.path : null
}

/** Запомнить открытую сессию пользователя. */
export function saveLastSessionPath(path: string, userId: string | null): void {
  if (!userId || !SESSION_PATH.test(path)) return
  try {
    window.sessionStorage.setItem(KEY, JSON.stringify({ path, userId }))
  } catch {
    // хранилище недоступно — пункт просто не переживёт перезагрузку
  }
}

/** Забыть сессию: выход из аккаунта или истёкшая сессия. */
export function clearLastSessionPath(): void {
  try {
    window.sessionStorage.removeItem(KEY)
  } catch {
    // нет доступа к sessionStorage — не критично
  }
}
