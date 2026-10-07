/**
 * Запросы админки (Фаза 4): пользователи, аудит, глобальная база,
 * задачи и таблица сессий.
 *
 * Пользователи/аудит/документы — обычные мутации с инвалидацией;
 * задачи поллятся каждые 2 с, пока есть живые (паритет _tasks: там
 * рисуется task_panel и кнопка отмены).
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { client } from '../../api/client'
import { isActiveTask, queryKeys } from '../dashboard/queries'

export const adminKeys = {
  users: ['admin', 'users'] as const,
  audit: ['admin', 'audit'] as const,
  documents: ['admin', 'documents'] as const,
  tasks: ['admin', 'tasks'] as const,
}

export function useAdminUsers() {
  return useQuery({
    queryKey: adminKeys.users,
    queryFn: () => client.adminUsers(),
  })
}

export function useCreateUser() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (fields: {
      username: string
      password: string
      role: string
      full_name?: string
    }) => client.adminCreateUser(fields),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: adminKeys.users })
    },
  })
}

export function useUpdateUser() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({
      userId,
      fields,
    }: {
      userId: string
      fields: { role?: string; password?: string }
    }) => client.adminUpdateUser(userId, fields),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: adminKeys.users })
    },
  })
}

export function useAudit() {
  return useQuery({
    queryKey: adminKeys.audit,
    queryFn: () => client.adminAudit({ limit: 200 }),
  })
}

export function useAdminDocuments() {
  return useQuery({
    queryKey: adminKeys.documents,
    queryFn: () => client.adminDocuments(),
  })
}

function useInvalidateGlobalDocs() {
  const queryClient = useQueryClient()
  return () => {
    void queryClient.invalidateQueries({ queryKey: adminKeys.documents })
    void queryClient.invalidateQueries({ queryKey: adminKeys.tasks })
  }
}

/** Добавление по пути в глобальную базу (паритет admin_add_path). */
export function useAdminAddPath() {
  const invalidate = useInvalidateGlobalDocs()
  return useMutation({
    mutationFn: (path: string) => client.adminAddPath(path),
    onSuccess: invalidate,
  })
}

/** Загрузка файлов в глобальную базу (паритет admin_upload). */
export function useAdminUpload() {
  const invalidate = useInvalidateGlobalDocs()
  return useMutation({
    mutationFn: ({ files, tags }: { files: File[]; tags: string }) =>
      client.adminUpload(files, tags),
    onSuccess: invalidate,
  })
}

export function useAdminDeleteDocument() {
  const invalidate = useInvalidateGlobalDocs()
  return useMutation({
    mutationFn: (documentId: string) => client.adminDeleteDocument(documentId),
    onSuccess: invalidate,
  })
}

export function useAdminReindex() {
  const invalidate = useInvalidateGlobalDocs()
  return useMutation({
    mutationFn: () => client.adminReindex(),
    onSuccess: invalidate,
  })
}

/** Массовая индексация: bulk-async → task_id, дальше поллится в «Задачах». */
export function useBulkIndex() {
  const invalidate = useInvalidateGlobalDocs()
  return useMutation({
    mutationFn: (paths: string[]) => client.submitBulkIndex(paths),
    onSuccess: invalidate,
  })
}

/** Отмена задачи: инвалидируем и общую выдачу, и админ-вкладку. */
export function useAdminCancelTask() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (taskId: string) => client.cancelTask(taskId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.activeTasks })
      void queryClient.invalidateQueries({ queryKey: adminKeys.tasks })
    },
  })
}

/**
 * Все задачи для вкладки «Задачи» (админу отдаётся и чужие).
 * Поллинг по той же схеме, что на дашборде: пока есть живые.
 */
export function useAdminTasks() {
  return useQuery({
    queryKey: adminKeys.tasks,
    queryFn: async () => {
      const body = await client.tasks()
      return body.tasks
    },
    refetchInterval: (query) => {
      const tasks = query.state.data
      if (!tasks) return 2000
      return tasks.some((task) => isActiveTask(task.status)) ? 2000 : false
    },
    refetchIntervalInBackground: false,
  })
}

/** Таблица сессий (паритет _sessions: st.dataframe с колонками). */
export function useSessionsTable() {
  return useQuery({
    queryKey: queryKeys.sessions,
    queryFn: () => client.sessions(),
  })
}
