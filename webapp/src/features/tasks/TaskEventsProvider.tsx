/**
 * Единственная SSE-подписка на задачи для всего приложения.
 *
 * Раньше поток открывали и `useActiveTasks` (дашборд), и `useTask` (чат):
 * на одной странице могло быть два EventSource, а завершение одной задачи
 * закрывало канал и теряло события по остальным. Теперь подписка одна,
 * живёт в layout, а хуки читают обновлённый кэш.
 *
 * Завершённые задачи убираются из `activeTasks` (иначе «Активные задачи»
 * навсегда показывает готовую строку), но их финальный статус остаётся в
 * `chatKeys.task(id)` — по нему `useTask` гасит панель и дописывает ответ.
 */

import { useEffect } from 'react'
import type { ReactNode } from 'react'
import { useQueryClient } from '@tanstack/react-query'

import { client } from '../../api/client'
import type { Task } from '../../api/types'
import { chatKeys } from '../chat/queries'
import { isActiveTask, queryKeys } from '../dashboard/queries'

export function TaskEventsProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient()

  useEffect(() => {
    const url = client.taskEventsUrl()
    if (!url) return

    const source = new EventSource(url)
    source.onmessage = (event) => {
      let task: Task
      try {
        task = JSON.parse(event.data) as Task
      } catch {
        // битое событие не должно ронять подписку
        return
      }
      if (!task?.id) return

      // Финальный статус нужен `useTask` даже после того, как задача ушла
      // из списка активных: иначе панель этапов не погаснет.
      queryClient.setQueryData(chatKeys.task(task.id), task)

      queryClient.setQueryData(queryKeys.activeTasks, (old: Task[] | undefined) => {
        // До первого GET списка ничего не создаём: иначе кэш станет
        // «свежим» и запрос не догрузит остальные активные задачи.
        if (!old) return old
        const rest = old.filter((item) => item.id !== task.id)
        return isActiveTask(task.status) ? [task, ...rest] : rest
      })
    }

    // События за время обрыва не переигрываются: после каждого (пере)открытия
    // сверяем список с сервером, иначе задача, стартовавшая во время разрыва,
    // не появится до перезагрузки страницы.
    source.onopen = () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.activeTasks })
    }

    // Никакого close() по статусу задачи: канал общий. EventSource сам
    // переподключается после сетевого обрыва; cleanup закрывает его при
    // размонтировании layout (выход из аккаунта).
    return () => source.close()
  }, [queryClient])

  return children
}
