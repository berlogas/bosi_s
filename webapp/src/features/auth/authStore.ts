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

export const useAuth = create<AuthState>((set) => ({
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
    set({ user: null, status: 'anonymous', loginError: null })
  },

  dropSession() {
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
