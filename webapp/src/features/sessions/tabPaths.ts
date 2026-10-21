/**
 * Вкладки сессии: идентификаторы и адреса.
 *
 * Вынесено из SessionPage, чтобы карточка на дашборде могла открыть
 * сохранённую вкладку после `resume`, не импортируя саму страницу.
 */

export const TABS = ['documents', 'projects', 'chat', 'notes'] as const
export type TabId = (typeof TABS)[number]

/** Вкладка из адреса; всё незнакомое — чат (как раньше в SessionPage). */
export function tabIdFromPath(pathname: string): TabId {
  const segment = pathname.split('/').pop()
  return (TABS as readonly string[]).includes(segment ?? '')
    ? (segment as TabId)
    : 'chat'
}

/** Вкладка из точки возврата (`state_snapshot.tab`), иначе чат. */
export function tabFromState(state: Record<string, unknown> | undefined): TabId {
  const value = state?.tab
  return typeof value === 'string' && (TABS as readonly string[]).includes(value)
    ? (value as TabId)
    : 'chat'
}

export function sessionTabPath(sessionId: string, tab: TabId): string {
  return `/s/${sessionId}/${tab}`
}
