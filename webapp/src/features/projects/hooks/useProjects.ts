import { useProjects as useProjectsQuery, useJournalStyles, useCreateProject, usePatchProject, useDeleteProject, useReorderProjects } from '../queries'
import { useMemo, useCallback } from 'react'

import type { ProjectOut } from '../../../api/types'

interface UseProjectsReturn {
  projects: ReturnType<typeof useProjectsQuery>
  styles: ReturnType<typeof useJournalStyles>
  create: ReturnType<typeof useCreateProject>
  patch: ReturnType<typeof usePatchProject>
  remove: ReturnType<typeof useDeleteProject>
  reorder: ReturnType<typeof useReorderProjects>

  // Computed
  list: ProjectOut[]
  filteredList: (searchQuery: string) => ProjectOut[]
  selected: ProjectOut | null
  journalChoices: { value: string; label: string }[]
}

/**
 * Hook для работы со списком проектов.
 * Добавляет проекции select для оптимизации рендера списка.
 */
export function useProjects(sessionId: string | null) {
  const projects = useProjectsQuery(sessionId)
  const styles = useJournalStyles()
  const create = useCreateProject(sessionId as string)
  const patch = usePatchProject(sessionId as string)
  const remove = useDeleteProject(sessionId as string)
  const reorder = useReorderProjects(sessionId as string)

  // Проекция только нужных полей для списка (оптимизация)
  const list = useMemo(() => projects.data ?? [], [projects.data])

  const filteredList = useCallback(
    (searchQuery: string) => {
      if (!searchQuery.trim()) return list
      const query = searchQuery.toLowerCase()
      return list.filter(
        (project) =>
          project.title.toLowerCase().includes(query) ||
          ((project.sections as Array<{ name: string }> | undefined)?.some?.((s) => s.name.toLowerCase().includes(query)) ?? false),
      )
    },
    [list]
  )

  const journalChoices = useMemo(
    () => (styles.data ?? []).map((item) => ({ value: item.key, label: item.title })),
    [styles.data]
  )

  return {
    projects,
    styles,
    create,
    patch,
    remove,
    reorder,
    list,
    filteredList,
    selected: null, // Will be set by parent
    journalChoices,
  } satisfies UseProjectsReturn
}

/**
 * Hook для получения только названий проектов (для автокомплита и т.д.)
 */
export function useProjectTitles(sessionId: string | null) {
  const { data } = useProjectsQuery(sessionId)
  return useMemo(
    () => (data ?? []).map((p) => ({ id: p.id, title: p.title })),
    [data]
  )
}