/**
 * Запросы вкладки «Документы» (Фаза 3, паритет documents_tab из workspace.py).
 *
 * Список сгруппирован по категориям, добавление по пути и загрузка файлов —
 * мутации с инвалидацией списка и лимитов сессии (summary в detail).
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { client } from '../../api/client'
import { isActiveTask, queryKeys } from '../dashboard/queries'

export const documentKeys = {
  list: (sessionId: string) => ['documents', sessionId] as const,
  sessionTasks: (sessionId: string) => ['tasks', 'session', sessionId] as const,
}

export function useSessionDocuments(sessionId: string | null) {
  return useQuery({
    queryKey: documentKeys.list(sessionId ?? ''),
    queryFn: () => client.sessionDocuments(sessionId as string),
    enabled: sessionId !== null,
  })
}

/**
 * Активные задачи сессии — прогресс индексации (план Фазы 3).
 * Поллинг 2 с, пока есть живые: загрузка файлов на диске индексируется
 * пачкой, юзеру важно видеть, что индекс ещё собирается.
 */
export function useSessionIndexingTasks(sessionId: string | null) {
  return useQuery({
    queryKey: documentKeys.sessionTasks(sessionId ?? ''),
    queryFn: async () => {
      const body = await client.tasks({ sessionId: sessionId as string })
      return body.tasks.filter(
        (task) => isActiveTask(task.status) || task.kind === 'indexing',
      )
    },
    enabled: sessionId !== null,
    refetchInterval: (query) => {
      const tasks = query.state.data
      if (!tasks) return 2000
      return tasks.some((task) => isActiveTask(task.status)) ? 2000 : false
    },
    refetchIntervalInBackground: false,
  })
}

/**
 * Общий колбэк: список документов и лимиты сессии меняются вместе.
 * Задачи тоже инвалидируем: refetchInterval у пустого списка возвращает
 * false (поллинг остановлен), без ручного refetch панель индексации
 * после загрузки так и не появилась бы.
 */
function useInvalidateDocuments(sessionId: string) {
  const queryClient = useQueryClient()
  return () => {
    void queryClient.invalidateQueries({
      queryKey: documentKeys.list(sessionId),
    })
    void queryClient.invalidateQueries({
      queryKey: queryKeys.sessionDetail(sessionId),
    })
    void queryClient.invalidateQueries({ queryKey: queryKeys.sessions })
    void queryClient.invalidateQueries({
      queryKey: documentKeys.sessionTasks(sessionId),
    })
  }
}

/** Добавить файл с диска по пути (внутри каталога сессии). */
export function useAddDocumentByPath(sessionId: string) {
  const invalidate = useInvalidateDocuments(sessionId)
  return useMutation({
    mutationFn: ({
      path,
      category,
      tags,
    }: {
      path: string
      category: string
      tags: string[]
    }) => client.addDocumentByPath(sessionId, path, { category, tags }),
    onSuccess: invalidate,
  })
}

/** Загрузка файлов: индексация может занять минуты (таймаут в клиенте). */
export function useUploadDocuments(sessionId: string) {
  const invalidate = useInvalidateDocuments(sessionId)
  return useMutation({
    mutationFn: ({
      files,
      category,
      tags,
    }: {
      files: File[]
      category: string
      tags: string
    }) => client.uploadDocuments(sessionId, files, { category, tags }),
    onSuccess: invalidate,
  })
}

export function useDeleteDocument(sessionId: string) {
  const invalidate = useInvalidateDocuments(sessionId)
  return useMutation({
    mutationFn: (documentId: string) => client.deleteDocument(sessionId, documentId),
    onSuccess: invalidate,
  })
}
