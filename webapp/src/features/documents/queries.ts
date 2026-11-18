/**
 * Запросы вкладки «Документы» (Фаза 3, паритет documents_tab из workspace.py).
 *
 * Список сгруппирован по категориям, добавление по пути и загрузка файлов —
 * мутации с инвалидацией списка и лимитов сессии (summary в detail).
 */

import { useEffect, useRef } from 'react'
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

export function useSessionStyleGuideDocuments(sessionId: string | null) {
  return useQuery({
    queryKey: ['documents', sessionId, 'style_guide'] as const,
    queryFn: () => client.sessionDocuments(sessionId as string, 'style_guide'),
    enabled: sessionId !== null,
  })
}

/**
 * Активные задачи сессии — прогресс индексации (план Фазы 3).
 * Поллинг 2 с, пока есть живые: загрузка файлов на диске индексируется
 * пачкой, юзеру важно видеть, что индекс ещё собирается.
 */
export function useSessionIndexingTasks(sessionId: string | null) {
  const queryClient = useQueryClient()
  // Задачи, чьё завершение мы уже учли: иначе каждый опрос заново
  // инвалидировал бы список документов (опрос → инвалидация → опрос).
  const accounted = useRef<Set<string>>(new Set())

  const query = useQuery({
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

  // Индексация завершилась — список документов изменился.
  useEffect(() => {
    const tasks = query.data ?? []
    const finished = tasks.filter(
      (task) =>
        (task.status === 'done' || task.status === 'error') &&
        !accounted.current.has(task.id),
    )
    if (finished.length === 0) return
    for (const task of finished) accounted.current.add(task.id)
    void queryClient.invalidateQueries({
      queryKey: documentKeys.list(sessionId ?? ''),
    })
  }, [query.data, queryClient, sessionId])

  return query
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
      forceReindex = false,
    }: {
      path: string
      category: string
      tags: string[]
      /** Переиндексировать, даже если документ уже в индексе. */
      forceReindex?: boolean
    }) => client.addDocumentByPath(sessionId, path, { category, tags, forceReindex }),
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
      onProgress,
    }: {
      files: File[]
      category: string
      tags: string
      /** % отправленных байтов — из DocumentsTab (XHR onprogress). */
      onProgress?: (percent: number) => void
    }) => client.uploadDocuments(sessionId, files, { category, tags, onProgress }),
    onSuccess: invalidate,
  })
}

/**
 * Фоновая загрузка файлов: сервер отвечает сразу `task_id`, индексация идёт
 * в фоне, прогресс виден в панели задач.
 *
 * Список документов обновляет `useSessionIndexingTasks`, когда задача дошла
 * до конца, — здесь только сбрасываем счётчик отправки.
 */
export function useUploadDocumentsAsync(sessionId: string) {
  const invalidate = useInvalidateDocuments(sessionId)
  return useMutation({
    mutationFn: ({
      files,
      category,
      tags,
      onProgress,
      replace = false,
    }: {
      files: File[]
      category: string
      tags: string
      /** % отправленных байтов — из DocumentsTab (XHR onprogress). */
      onProgress?: (percent: number) => void
      /** Заменить прежние версии документов с теми же именами. */
      replace?: boolean
    }) => client.uploadDocumentsAsync(sessionId, files, { category, tags, onProgress, replace }),
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
