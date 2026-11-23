/**
 * Контекст для хлебных крошек — позволяет вкладкам (проекты, чат, документы)
 * сообщать текущий вложенный контекст (проект, раздел, документ и т.д.).
 */

import { createContext, useContext } from 'react'

export interface BreadcrumbContextValue {
  /** ID активного проекта (вкладка Проекты) */
  activeProjectId: string | null
  /** Название активного проекта */
  activeProjectTitle: string | null
  /** Название активного раздела проекта */
  activeSectionName: string | null
  /** Установить активный проект */
  setActiveProject: (id: string | null, title?: string | null) => void
  /** Установить активный раздел */
  setActiveSection: (name: string | null) => void
  /** Сбросить контекст вкладки */
  reset: () => void
}

export const BreadcrumbContext = createContext<BreadcrumbContextValue | null>(null)

export function useBreadcrumbContext(): BreadcrumbContextValue {
  const ctx = useContext(BreadcrumbContext)
  if (!ctx) {
    throw new Error('useBreadcrumbContext must be used within BreadcrumbProvider')
  }
  return ctx
}
