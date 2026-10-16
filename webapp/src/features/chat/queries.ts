/**
 * Запросы чата сессии (Фаза 2).
 *
 * История, отправка вопроса (фоновый/синхронный), удаление пары,
 * очистка переписки, поллинг задачи и «точка возврата» (save_state).
 */

import type { QueryClient } from '@tanstack/react-query'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { client } from '../../api/client'
import type { SearchMode } from '../../api/types'
import { isActiveTask, queryKeys } from '../dashboard/queries'

export const chatKeys = {
  messages: (sessionId: string) => ['messages', sessionId] as const,
  task: (taskId: string) => ['task', taskId] as const,
}

export function useMessages(sessionId: string | null, limit: number) {
  return useQuery({
    queryKey: [...chatKeys.messages(sessionId ?? ''), limit],
    queryFn: async () => {
      // список приходит старшими первыми: чтобы видеть хвост переписки,
      // сдвигаем окно в конец (offset = total - limit)
      const head = await client.messages(sessionId as string, { limit: 1 })
      const total = head.total ?? 0
      const offset = Math.max(0, total - limit)
      const page = await client.messages(sessionId as string, { limit, offset })
      return { messages: page.messages ?? [], total, offset }
    },
    enabled: sessionId !== null,
    // история пополняется задачами/ответами — не держим старой дольше минуты
    staleTime: 15_000,
  })
}

/** Единый источник истины о фоновой задаче чата: поллинг 2 с, пока активна. */
export function useTask(taskId: string | null) {
  return useQuery({
    queryKey: chatKeys.task(taskId ?? ''),
    queryFn: () => client.task(taskId as string),
    enabled: taskId !== null && taskId !== '',
    refetchInterval: (query) => {
      const task = query.state.data
      if (!task) return 2000
      return isActiveTask(task.status) ? 2000 : false
    },
    refetchIntervalInBackground: false,
  })
}

/** Отправить вопрос в фоне — возвращает task_id. */
export function useChatAsync(sessionId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ question, mode }: { question: string; mode: SearchMode }) =>
      client.chatQueryAsync(sessionId, question, mode),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.activeTasks })
    },
  })
}

/** Синхронный вопрос: ответ приходит сразу (и уже сохранён в истории). */
export function useChatSync(sessionId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ question, mode }: { question: string; mode: SearchMode }) =>
      client.chatQuery(sessionId, question, mode),
    onSuccess: () => {
      // не из кэша — обмен уже в истории: подтянуть пузыри
      void queryClient.invalidateQueries({
        queryKey: chatKeys.messages(sessionId),
      })
    },
  })
}

/** Удаление пары «вопрос + ответ» (сервер удаляет оба). */
export function useDeleteMessage(sessionId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (messageId: string) => client.deleteMessage(messageId),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: chatKeys.messages(sessionId),
      })
      void queryClient.invalidateQueries({
        queryKey: queryKeys.sessionDetail(sessionId),
      })
    },
  })
}

/** Очистить всю переписку сессии (в два шага — подтверждение в UI). */
export function useClearMessages(sessionId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => client.clearMessages(sessionId),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: chatKeys.messages(sessionId),
      })
      void queryClient.invalidateQueries({
        queryKey: queryKeys.sessionDetail(sessionId),
      })
    },
  })
}

/**
 * Ответ `PUT /state` (SessionOut) вливаем в кэш detail — но только если
 * detail уже загружен.
 *
 * SessionOut не содержит `summary`, `days_left`, `writable`, поэтому запись
 * в пустой кэш подменяла бы detail объектом без них: `SessionPage` падал бы на
 * `session.summary.documents`, React размонтировал дерево, и страница оставалась
 * пустой до F5 (F5 перезапрашивает detail целиком и всё работает). Гонка
 * PUT-раньше-GET и делала баг «иногда».
 */
export function applySaveState(
  queryClient: QueryClient,
  sessionId: string,
  session: Record<string, unknown>,
): void {
  const cached = queryClient.getQueryData(queryKeys.sessionDetail(sessionId))
  if (!cached || typeof cached !== 'object') {
    void queryClient.invalidateQueries({ queryKey: queryKeys.sessionDetail(sessionId) })
    return
  }
  queryClient.setQueryData<Record<string, unknown>>(
    queryKeys.sessionDetail(sessionId),
    (old) => ({ ...(old as Record<string, unknown>), ...session }),
  )
}

/** «Точка возврата»: смена вкладки / заметка (PUT /state, force). */
export function useSaveState(sessionId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (payload: Parameters<typeof client.saveState>[1]) =>
      client.saveState(sessionId, payload),
    onSuccess: (session) => applySaveState(queryClient, sessionId, session),
  })
}
