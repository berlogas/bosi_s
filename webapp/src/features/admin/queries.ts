/**
 * Запросы админки (Фаза 4): пользователи, аудит, глобальная база,
 * задачи и таблица сессий.
 *
 * Пользователи/аудит/документы — обычные мутации с инвалидацией;
 * задачи поллятся каждые 2 с, пока есть живые (паритет _tasks: там
 * рисуется task_panel и кнопка отмены).
 */

import { notifications } from '@mantine/notifications'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { client } from '../../api/client'
import type { ResetScope } from '../../api/client'
import { isActiveTask, queryKeys } from '../dashboard/queries'

export const adminKeys = {
  users: ['admin', 'users'] as const,
  audit: ['admin', 'audit'] as const,
  documents: ['admin', 'documents'] as const,
  tasks: ['admin', 'tasks'] as const,
  reset: ['admin', 'reset'] as const,
  backups: ['admin', 'backups'] as const,
  inbox: ['admin', 'inbox'] as const,
  inboxRuns: ['admin', 'inbox', 'runs'] as const,
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
      fields: {
        username?: string
        full_name?: string
        role?: string
        password?: string
        is_active?: boolean
      }
    }) => client.adminUpdateUser(userId, fields),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: adminKeys.users })
    },
  })
}

/**
 * Удаление пользователя. Действие необратимо (каскад по сессиям и
 * документам), поэтому подтверждение живёт в UI, здесь — только запрос.
 * После успеха перечитываем список пользователей и аудит (в нём появится
 * запись admin.user.delete).
 */
export function useDeleteUser() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (userId: string) => client.adminDeleteUser(userId),
    onSuccess: (_data, userId) => {
      void queryClient.invalidateQueries({ queryKey: adminKeys.users })
      void queryClient.invalidateQueries({ queryKey: adminKeys.audit })
      notifications.show({
        title: 'Пользователь удалён',
        message: userId,
        color: 'red',
      })
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

// ------------------------------------------------------------------ inbox
/** Что лежит в папке-приёмнике: включаем кнопку массового добавления. */
export function useInboxStatus() {
  return useQuery({
    queryKey: adminKeys.inbox,
    queryFn: () => client.adminInboxStatus(),
  })
}

/** Журнал прогонов (последние). Обновляется после скана. */
export function useInboxRuns() {
  return useQuery({
    queryKey: adminKeys.inboxRuns,
    queryFn: () => client.adminInboxRuns(),
  })
}

/**
 * Обработка inbox. Долгая операция: сервер вернёт прогон с отчётом по
 * каждому файлу, поэтому инвалидируем и журнал, и список документов.
 */
export function useInboxScan() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => client.adminInboxScan(),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: adminKeys.inboxRuns })
      void queryClient.invalidateQueries({ queryKey: adminKeys.inbox })
      void queryClient.invalidateQueries({ queryKey: adminKeys.documents })
    },
  })
}

/** Очистка каталога rejected: причины остаются в журнале прогонов. */
export function useClearRejected() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => client.adminClearRejected(),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: adminKeys.inboxRuns })
      void queryClient.invalidateQueries({ queryKey: adminKeys.inbox })
    },
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

// ------------------------------------------------------------------ сброс
/** План сброса: что будет удалено при выбранном scope. */
export function useResetPreview(scope: ResetScope, includeModels: boolean) {
  return useQuery({
    queryKey: [...adminKeys.reset, 'preview', scope, includeModels],
    queryFn: () => client.adminResetPreview(scope, includeModels),
  })
}

/**
 * Сброс состояния. После успеха сбрасываем ВСЕ ключи приложения:
 * удалены сессии, документы и сообщения, поэтому старые данные на экране
 * больше невалидны (принцип: после сброса нужен чистый клиент).
 */
export function useResetState() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (fields: {
      scope: ResetScope
      confirm: string
      include_models?: boolean
    }) => client.adminReset(fields),
    onSuccess: () => {
      queryClient.clear()
    },
  })
}

// ------------------------------------------------------- резервные копии
/** Список копий и план следующей. */
export function useBackups() {
  return useQuery({
    queryKey: adminKeys.backups,
    queryFn: () => client.adminBackups(),
    // план зависит от размера данных — после сброса он меняется
    refetchOnWindowFocus: false,
  })
}

/** Снять копию. После успеха перечитываем список. */
export function useCreateBackup() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (keep?: number) => client.adminCreateBackup(keep),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: adminKeys.backups })
    },
  })
}

/** Удалить копию. */
export function useDeleteBackup() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (name: string) => client.adminDeleteBackup(name),
    onSuccess: async (_data, name) => {
      await queryClient.invalidateQueries({ queryKey: adminKeys.backups })
      notifications.show({
        title: 'Копия удалена',
        message: name,
        color: 'gray',
      })
    },
  })
}
