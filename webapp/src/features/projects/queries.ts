/**
 * Запросы вкладки «Проекты» (Фаза 3, паритет project_editor.py).
 *
 * CRUD проекта, разделы, привязка документов, генерация (синхронная —
 * Streamlit тоже ждёт со спиннером), разбор черновика и экспорт.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { client } from '../../api/client'
import type { ExportFormat, GenerateRequest } from '../../api/types'

export const projectKeys = {
  list: (sessionId: string) => ['projects', sessionId] as const,
  sections: (sessionId: string, projectId: string) =>
    ['project-sections', sessionId, projectId] as const,
  documents: (sessionId: string, projectId: string) =>
    ['project-documents', sessionId, projectId] as const,
  progress: (sessionId: string, projectId: string) =>
    ['project-progress', sessionId, projectId] as const,
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
    }
  }
}

export function useCreateProject(sessionId: string) {
  const invalidate = useInvalidateProject(sessionId)
  return useMutation({
    mutationFn: ({ title, journal }: { title: string; journal: string }) =>
      client.createProject(sessionId, title, journal),
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
      fields: { status?: string; title?: string; target_journal?: string }
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

export function useSections(sessionId: string | null, projectId: string | null) {
  return useQuery({
    queryKey: projectKeys.sections(sessionId ?? '', projectId ?? ''),
    queryFn: () => client.sections(sessionId as string, projectId as string),
    enabled: sessionId !== null && projectId !== null,
  })
}

export function useSaveSection(sessionId: string, projectId: string) {
  const invalidate = useInvalidateProject(sessionId)
  return useMutation({
    mutationFn: ({ name, contentMd }: { name: string; contentMd: string }) =>
      client.saveSection(sessionId, projectId, name, { content_md: contentMd }),
    onSuccess: () => invalidate(projectId),
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
export function useGenerate(sessionId: string, projectId: string) {
  const invalidate = useInvalidateProject(sessionId)
  return useMutation({
    mutationFn: (payload: GenerateRequest) =>
      client.generate(sessionId, projectId, payload),
    // раздел мог записаться — разделы и прогресс читаем заново
    onSuccess: () => invalidate(projectId),
  })
}

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
