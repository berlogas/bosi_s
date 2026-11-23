/**
 * Запросы вкладки «Проекты» (Фаза 3, паритет project_editor.py).
 *
 * CRUD проекта, разделы, привязка документов, генерация (синхронная —
 * Streamlit тоже ждёт со спиннером), разбор черновика и экспорт.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { client } from '../../api/client'
import type { ExportFormat } from '../../api/client'

export const projectKeys = {
  journalStyles: () => ['journal-styles'] as const,
  list: (sessionId: string) => ['projects', sessionId] as const,
  sections: (sessionId: string, projectId: string) =>
    ['project-sections', sessionId, projectId] as const,
  documents: (sessionId: string, projectId: string) =>
    ['project-documents', sessionId, projectId] as const,
  progress: (sessionId: string, projectId: string) =>
    ['project-progress', sessionId, projectId] as const,
}

/**
 * Группы журналов и их шаблоны промптов.
 *
 * Не зависит от сессии: справочник общий и нужен уже при создании проекта.
 * Кэш долгий — группы добавляют файлами на диске, а не правкой каждого клиента.
 */
export function useJournalStyles() {
  return useQuery({
    queryKey: projectKeys.journalStyles(),
    queryFn: () => client.journalStyles(),
    staleTime: 30 * 60 * 1000,
  })
}

export function useProjects(sessionId: string | null) {
  return useQuery({
    queryKey: projectKeys.list(sessionId ?? ''),
    queryFn: () => client.projects(sessionId as string),
    enabled: sessionId !== null,
  })
}

function useInvalidateProject(sessionId: string) {
  const queryClient = useQueryClient()
  return (projectId?: string) => {
    void queryClient.invalidateQueries({ queryKey: projectKeys.list(sessionId) })
    if (projectId) {
      void queryClient.invalidateQueries({
        queryKey: projectKeys.sections(sessionId, projectId),
      })
      void queryClient.invalidateQueries({
        queryKey: projectKeys.progress(sessionId, projectId),
      })
      void queryClient.invalidateQueries({
        queryKey: projectKeys.documents(sessionId, projectId),
      })
      void queryClient.invalidateQueries({
        queryKey: ['project-versions', sessionId, projectId],
      })
    }
  }
}

export function useCreateProject(sessionId: string) {
  const invalidate = useInvalidateProject(sessionId)
  return useMutation({
    mutationFn: ({
      title,
      journal,
      language,
    }: {
      title: string
      journal: string
      language: string
    }) => client.createProject(sessionId, title, journal, language),
    onSuccess: (project) => invalidate(project.id),
  })
}

export function usePatchProject(sessionId: string) {
  const invalidate = useInvalidateProject(sessionId)
  return useMutation({
    mutationFn: ({
      projectId,
      fields,
    }: {
      projectId: string
      fields: {
        status?: string
        title?: string
        target_journal?: string
        language?: string
      }
    }) => client.patchProject(sessionId, projectId, fields),
    onSuccess: (project) => invalidate(project.id),
  })
}

export function useDeleteProject(sessionId: string) {
  const invalidate = useInvalidateProject(sessionId)
  return useMutation({
    mutationFn: (projectId: string) => client.deleteProject(sessionId, projectId),
    onSuccess: () => invalidate(),
  })
}

export function useProjectDocuments(
  sessionId: string | null,
  projectId: string | null,
) {
  return useQuery({
    queryKey: projectKeys.documents(sessionId ?? '', projectId ?? ''),
    queryFn: () => client.projectDocuments(sessionId as string, projectId as string),
    enabled: sessionId !== null && projectId !== null,
  })
}

export function useBindDocument(sessionId: string, projectId: string) {
  const invalidate = useInvalidateProject(sessionId)
  return useMutation({
    mutationFn: ({ documentId, role }: { documentId: string; role: string }) =>
      client.bindDocument(sessionId, projectId, documentId, role),
    onSuccess: () => invalidate(projectId),
  })
}

export function useUnbindDocument(sessionId: string, projectId: string) {
  const invalidate = useInvalidateProject(sessionId)
  return useMutation({
    mutationFn: (documentId: string) =>
      client.unbindDocument(sessionId, projectId, documentId),
    onSuccess: () => invalidate(projectId),
  })
}

export function useProjectProgress(sessionId: string | null, projectId: string | null) {
  return useQuery({
    queryKey: projectKeys.progress(sessionId ?? '', projectId ?? ''),
    queryFn: () => client.projectProgress(sessionId as string, projectId as string),
    enabled: sessionId !== null && projectId !== null,
  })
}

/** Генерация раздела/анализ — синхронная, результат сразу в руках. */
/**
 * Экспорт статьи: ответ — файл, поэтому качаем blob'ом (обычный request
 * разбирает тело как JSON). Имя файла берём из Content-Disposition, чтобы
 * в архиве было «Название статьи.docx», а не «article.docx».
 */
export function useExportProject(sessionId: string) {
  return useMutation({
    mutationFn: ({ projectId, format }: { projectId: string; format: ExportFormat }) =>
      client.downloadProject(sessionId, projectId, format),
    onSuccess: ({ blob, filename }) => {
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = filename
      link.click()
      URL.revokeObjectURL(url)
    },
  })
}

export function useSetProjectStyleGuide(sessionId: string) {
  const invalidate = useInvalidateProject(sessionId)
  return useMutation({
    mutationFn: ({
      projectId,
      documentId,
    }: {
      projectId: string
      documentId: string | null
    }) => client.setProjectStyleGuide(sessionId, projectId, documentId),
    onSuccess: () => invalidate(),
  })
}

/** Перевод раздела на целевой язык через бэкенд (LLM). */
/** Переупорядочивание проектов — отправляет новый order для затронутых проектов. */
export function useReorderProjects(sessionId: string) {
  const invalidate = useInvalidateProject(sessionId)
  return useMutation({
    mutationFn: ({ projectId, order }: { projectId: string; order: number }) =>
      client.patchProject(sessionId, projectId, { order }),
    onSuccess: () => invalidate(),
  })
}
