/**
 * Auth-состояние (zustand).
 *
 * Пользователь восстанавливается при старте приложения через `bootstrap()`:
 * если refresh-токен пережил перезагрузку вкладки — client.me() молча
 * обновит access и вернёт пользователя; иначе уводим на экран входа.
 */

import { create } from 'zustand'

import { client } from '../../api/client'
import type { components } from '../../api/schema'
import { hasStoredSession } from '../../api/tokens'
import { clearLastSessionPath } from '../sessions/lastSession'

type User = components['schemas']['UserOut']

export type AuthStatus = 'boot' | 'anonymous' | 'authenticated'

interface AuthState {
  user: User | null
  status: AuthStatus
  /** Текст ошибки входа (показывается на форме). */
  loginError: string | null
  loginBusy: boolean

  bootstrap: () => Promise<void>
  login: (username: string, password: string) => Promise<boolean>
  logout: () => Promise<void>
  /** «Сессия истекла» от клиента: чистим всё без сетевого logout. */
  dropSession: () => void
}

/** Единоразовость bootstrap: StrictMode в dev зовёт эффект дважды. */
let bootstrapStarted = false

/**
 * Сброс пользовательских кэшей при смене входа.
 *
 * Кэш запросов не привязан к пользователю (ключи вроде `['sessions']`):
 * без сброса следующий вошедший в ту же вкладку видел данные предыдущего —
 * дашборд грузился из памяти до истечения `staleTime`. Регистрирует его
 * провайдеры (`AppProviders`): сам store про QueryClient не знает.
 */
type IdentityReset = () => void
let resetIdentityCaches: IdentityReset | null = null

/** Зарегистрировать сброс кэшей; возвращает функцию отписки. */
export function setIdentityCacheReset(reset: IdentityReset): () => void {
  resetIdentityCaches = reset
  return () => {
    if (resetIdentityCaches === reset) resetIdentityCaches = null
  }
}

export const useAuth = create<AuthState>((set, get) => ({
  user: null,
  status: 'boot',
  loginError: null,
  loginBusy: false,

  async bootstrap() {
    if (bootstrapStarted) return
    bootstrapStarted = true
    if (!hasStoredSession()) {
      set({ status: 'anonymous' })
      return
    }
    try {
      const user = await client.me()
      set({ user, status: 'authenticated' })
    } catch {
      // просроченный/отозванный refresh — тихо на экран входа
      set({ user: null, status: 'anonymous' })
    }
  },

  async login(username, password) {
    set({ loginBusy: true, loginError: null })
    try {
      const user = await client.login(username, password)
      // Чистим кэш до смены состояния: дашборд нового пользователя не должен
      // ни на кадр показать данные предыдущего.
      if (get().user?.id !== user.id) resetIdentityCaches?.()
      set({ user, status: 'authenticated', loginBusy: false, loginError: null })
      return true
    } catch (cause) {
      const message =
        cause instanceof Error ? cause.message : 'Не удалось войти. Попробуйте ещё раз.'
      set({ loginBusy: false, loginError: message })
      return false
    }
  },

  async logout() {
    await client.logout()
    // Запомненная сессия принадлежала ушедшему: в той же вкладке её нельзя
    // предлагать следующему пользователю.
    clearLastSessionPath()
    resetIdentityCaches?.()
    set({ user: null, status: 'anonymous', loginError: null })
  },

  dropSession() {
    clearLastSessionPath()
    resetIdentityCaches?.()
    set({
      user: null,
      status: 'anonymous',
      loginError: 'Сессия истекла. Войдите заново.',
    })
  },
}))

/** Зарегистрировать единственный слушатель onUnauthorized (вызвать один раз). */
export function watchSessionExpiry(): () => void {
  return client.onUnauthorized(() => {
    useAuth.getState().dropSession()
  })
}
