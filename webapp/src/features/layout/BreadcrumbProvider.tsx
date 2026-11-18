/**
 * Провайдер контекста хлебных крошек.
 * Оборачивает содержимое вкладки сессии, позволяя вложенным компонентам
 * обновлять крошки (активный проект, раздел и т.д.).
 */

import { useState, useCallback, useMemo } from 'react'
import { BreadcrumbContext, type BreadcrumbContextValue } from './BreadcrumbContext'

export function BreadcrumbProvider({
  children,
}: {
  children: React.ReactNode
}) {
  const [activeProjectId, setActiveProjectId] = useState<string | null>(null)
  const [activeProjectTitle, setActiveProjectTitle] = useState<string | null>(null)
  const [activeSectionName, setActiveSectionName] = useState<string | null>(null)

  const setActiveProject = useCallback((id: string | null, title?: string | null) => {
    setActiveProjectId(id)
    setActiveProjectTitle(title ?? null)
    if (id === null) {
      setActiveSectionName(null)
    }
  }, [])

  const setActiveSection = useCallback((name: string | null) => {
    setActiveSectionName(name)
  }, [])

  const reset = useCallback(() => {
    setActiveProjectId(null)
    setActiveProjectTitle(null)
    setActiveSectionName(null)
  }, [])

  const value = useMemo<BreadcrumbContextValue>(() => ({
    activeProjectId,
    activeProjectTitle,
    activeSectionName,
    setActiveProject,
    setActiveSection,
    reset,
  }), [activeProjectId, activeProjectTitle, activeSectionName, setActiveProject, setActiveSection, reset])

  return (
    <BreadcrumbContext.Provider value={value}>
      {children}
    </BreadcrumbContext.Provider>
  )
}