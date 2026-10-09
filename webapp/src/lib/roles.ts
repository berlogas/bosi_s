/**
 * Подписи ролей для интерфейса.
 *
 * В API и БД роль остаётся техническим значением `researcher` / `admin`:
 * это контракт, менять его нельзя. Пользователь же видит русские слова —
 * «Исследователь» и «Администратор». Здесь единственное место, где живёт
 * перевод, чтобы в разных экранах не разъехалось.
 */

import type { User } from '../api/types'

export const ROLE_LABELS: Record<string, string> = {
  researcher: 'Исследователь',
  admin: 'Администратор',
}

/** Значение роли → подпись; неизвестное значение показываем как есть. */
export function roleLabel(role: string): string {
  return ROLE_LABELS[role] ?? role
}

/** Значение роли → подпись для выпадающих списков. */
export function roleOptions(
  values: readonly string[],
): { value: string; label: string }[] {
  return values.map((value) => ({ value, label: roleLabel(value) }))
}

/**
 * Как обращаться к пользователю: ФИО, если заполнено, иначе логин.
 * ФИО может состоять из пробелов — тогда тоже логин.
 */
export function displayName(user: Pick<User, 'username' | 'full_name'>): string {
  const full = (user.full_name ?? '').trim()
  return full || user.username
}
