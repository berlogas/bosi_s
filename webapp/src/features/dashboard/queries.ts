/**
 * Запросы Фазы 1: сессии и активные задачи.
 *
 * Поллинг задач — как в Streamlit (каждые 2 с), но только пока есть
 * живые: refetchInterval считает по данным, готовая задача гасит опрос.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { client } from '../../api/client'

export const queryKeys = {
  sessions: ['sessions'] as const,
  sessionDetail: (id: string) => ['session', id] as const,
  activeTasks: ['tasks', 'active'] as const,
  health: ['health'] as const,
}

/** Задачи в статусах, которые ещё можно отменить/дождаться. */
export function isActiveTask(status: string): boolean {
  return status !== 'done' && status !== 'error' && status !== 'cancelled'
}

export function useSessions() {
  return useQuery({
    queryKey: queryKeys.sessions,
    queryFn: () => client.sessions(),
  })
}

export function useSessionDetail(sessionId: string | null) {
  return useQuery({
    queryKey: queryKeys.sessionDetail(sessionId ?? ''),
    queryFn: () => client.sessionDetail(sessionId as string),
    enabled: sessionId !== null,
  })
}

/** Активные задачи пользователя; поллинг останавливается на готовых. */
export function useActiveTasks() {
  return useQuery({
    queryKey: queryKeys.activeTasks,
    queryFn: async () => {
      const body = await client.tasks()
      return body.tasks.filter((task) => isActiveTask(task.status))
    },
    refetchInterval: (query) => {
      const tasks = query.state.data
      if (!tasks) return 2000
      // опрос только пока есть живые — иначе дашборд не тратит запросы
      return tasks.some((task) => isActiveTask(task.status)) ? 2000 : false
    },
    refetchIntervalInBackground: false,
  })
}

export function useCreateSession() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (title: string) => client.createSession(title),
    onSuccess: (session) => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.sessions })
      // карточка при первой отрисовке запросит detail (TTL) — не из кэша
      void queryClient.invalidateQueries({
        queryKey: queryKeys.sessionDetail(session.id),
      })
    },
  })
}

export function useArchiveSession() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (sessionId: string) => client.archiveSession(sessionId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.sessions })
    },
  })
}

export function useCancelTask() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (taskId: string) => client.cancelTask(taskId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.activeTasks })
    },
  })
}
