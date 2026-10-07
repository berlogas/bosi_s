/**
 * Хранение токенов.
 *
 * По плану миграции (раздел 5A): access — только в памяти, refresh —
 * в localStorage, чтобы первые 30 минут сессии переживали обновление
 * вкладки. localStorage может бросить в приватном режиме — тогда
 * работаем «как Streamlit»: держим refresh в памяти до закрытия вкладки.
 */

const REFRESH_KEY = 'boasi.refresh_token'

let accessToken: string | null = null
// Зеркало refresh в памяти: переживает закрытие localStorage, когда тот
// недоступен (приватный режим), и не читает хранилище на каждый запрос.
let memoryRefresh: string | null = null

function readStoredRefresh(): string | null {
  try {
    return window.localStorage.getItem(REFRESH_KEY)
  } catch {
    return null
  }
}

function writeStoredRefresh(token: string | null): void {
  try {
    if (token === null) {
      window.localStorage.removeItem(REFRESH_KEY)
    } else {
      window.localStorage.setItem(REFRESH_KEY, token)
    }
  } catch {
    /* приватный режим — живём на memoryRefresh */
  }
}

export const tokens = {
  getAccess(): string | null {
    return accessToken
  },

  /** access из свежего login/refresh. */
  setAccess(token: string): void {
    accessToken = token
  },

  getRefresh(): string | null {
    return memoryRefresh ?? readStoredRefresh()
  },

  /** Сохранить пару после login/refresh (refresh ротируется на каждом обновлении). */
  setPair(access: string, refresh: string): void {
    accessToken = access
    memoryRefresh = refresh
    writeStoredRefresh(refresh)
  },

  clear(): void {
    accessToken = null
    memoryRefresh = null
    writeStoredRefresh(null)
  },
}

/** Есть ли хоть какой-то шанс восстановить сессию без повторного входа. */
export function hasStoredSession(): boolean {
  return memoryRefresh !== null || readStoredRefresh() !== null
}
