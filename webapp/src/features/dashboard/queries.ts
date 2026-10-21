/**
 * Запросы Фазы 1: сессии и активные задачи.
 *
 * Задачи обновляются через SSE (EventSource) вместо поллинга — сервер
 * пушит изменения в реальном времени, без лишних запросов каждые 2 секунды.
 */

import { notifications } from '@mantine/notifications'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { client } from '../../api/client'
import type { Task } from '../../api/types'

export const queryKeys = {
  sessions: ['sessions'] as const,
  sessionDetail: (id: string) => ['session', id] as const,
  activeTasks: ['tasks', 'active'] as const,
  quickHistory: ['chat', 'quick-history'] as const,
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

/**
 * Активные задачи пользователя.
 *
 * Сам SSE-поток открывает `TaskEventsProvider` (один на приложение); здесь
 * остаётся запрос-снимок и короткий опрос как страховка от пропущенных
 * событий.
 */
export function useActiveTasks() {
  return useQuery({
    queryKey: queryKeys.activeTasks,
    queryFn: async () => {
      const body = await client.tasks()
      return body.tasks.filter((task: Task) => isActiveTask(task.status))
    },
    // SSE пушит изменения сразу, но как страховка от пропущенного события —
    // короткий опрос, пока есть живые задачи (готовые гасят refetchInterval)
    refetchInterval: (query) => {
      const tasks = query.state.data
      if (!tasks) return 2000
      return tasks.some((task) => isActiveTask(task.status)) ? 2000 : false
    },
    refetchIntervalInBackground: false,
  })
}

/**
 * История быстрых вопросов.
 *
 * Раньше переписка жила в состоянии компонента и умирала вместе с вкладкой:
 * ответ, посчитанный на backend, приходилось ждать заново. Теперь она в БД
 * (`/api/chat/quick-history`), и дашборд поднимает её при открытии.
 */
export function useQuickHistory(limit = 20) {
  return useQuery({
    queryKey: [...queryKeys.quickHistory, limit],
    queryFn: () => client.quickHistory(limit),
    // история меняется только после завершённого вопроса, а он сам инвалидирует
    // ключ — фонового перечитывания не нужно
    staleTime: 30_000,
  })
}

/** Очистить историю быстрых вопросов — инвалидация покрывает все лимиты. */
export function useClearQuickHistory() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => client.clearQuickHistory(),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.quickHistory })
    },
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

/**
 * Возврат к работе: `paused` → `active`, реконструкция `Docs` на сервере.
 *
 * Ответ несёт точку возврата (вкладку) и число восстановленных документов —
 * вызывающий сам решает, куда перейти. Ошибка не меняет статус: сбрасывать
 * кэш до успеха нельзя, иначе карточка покажет `active` без реактивации.
 */
export function useResumeSession() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (sessionId: string) => client.resumeSession(sessionId),
    onSuccess: (data, sessionId) => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.sessions })
      void queryClient.invalidateQueries({
        queryKey: queryKeys.sessionDetail(sessionId),
      })
      notifications.show({
        title: 'Сессия возобновлена',
        message:
          data.restored_documents > 0
            ? `Восстановлено документов: ${data.restored_documents}`
            : 'Можно продолжать работу',
        color: 'green',
      })
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
