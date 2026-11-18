/**
 * Хук для страницы «Задачи» админки: задачи, фильтры по статусу и
 * пользователю, отмена задачи, очистка завершённых.
 * URL-параметры имеют префикс `tasks_`.
 */

import { useCallback, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'

import {
  useAdminTasks,
  useAdminUsers,
  useAdminCancelTask,
  useClearFinishedTasks,
} from '../../queries'
import { isActiveTask } from '../../../dashboard/queries'

export const TASK_FILTERS = [
  { value: 'all', label: 'Все' },
  { value: 'active', label: 'Активные' },
  { value: 'done', label: 'Завершённые' },
  { value: 'error', label: 'С ошибкой' },
  { value: 'cancelled', label: 'Отменённые' },
] as const

const PARAM_PREFIX = 'tasks_'

function getParam(searchParams: URLSearchParams, key: string): string | null {
  return searchParams.get(`${PARAM_PREFIX}${key}`)
}

function setParam(searchParams: URLSearchParams, key: string, value: string | null) {
  const fullKey = `${PARAM_PREFIX}${key}`
  if (value) searchParams.set(fullKey, value)
  else searchParams.delete(fullKey)
}

export function useTasksPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const tasksQuery = useAdminTasks()
  const usersQuery = useAdminUsers()
  const cancel = useAdminCancelTask()
  const clearFinished = useClearFinishedTasks()

  // --- Локальные фильтры (статус + пользователь) ---
  const [status, setStatusState] = useState<string>(
    getParam(searchParams, 'status') ?? 'all',
  )
  const [userId, setUserIdState] = useState<string>(
    getParam(searchParams, 'user') ?? 'all',
  )

  const setStatus = useCallback(
    (v: string) => {
      setStatusState(v)
      setSearchParams(
        (prev) => {
          const params = new URLSearchParams(prev)
          setParam(params, 'status', v)
          setParam(params, 'page', '1')
          return params
        },
        { replace: true },
      )
    },
    [setSearchParams],
  )

  const setUserId = useCallback(
    (v: string) => {
      setUserIdState(v)
      setSearchParams(
        (prev) => {
          const params = new URLSearchParams(prev)
          setParam(params, 'user', v)
          setParam(params, 'page', '1')
          return params
        },
        { replace: true },
      )
    },
    [setSearchParams],
  )

  // --- URL state для таблицы ---
  const pageIndex = Math.max(0, Number(getParam(searchParams, 'page')) - 1 || 0)
  const pageSize = Number(getParam(searchParams, 'size')) || 25
  const sorting = useMemo(() => {
    const s = getParam(searchParams, 'sort')
    return s ? JSON.parse(s) : [{ id: 'created_at', desc: true }]
  }, [searchParams])
  const filters = useMemo(() => {
    const f = getParam(searchParams, 'filters')
    return f ? JSON.parse(f) : []
  }, [searchParams])

  const setPagination = useCallback(
    (next: { pageIndex: number; pageSize: number; pageCount: number }) => {
      setSearchParams(
        (prev) => {
          const params = new URLSearchParams(prev)
          setParam(params, 'page', String(next.pageIndex + 1))
          setParam(params, 'size', String(next.pageSize))
          return params
        },
        { replace: true },
      )
    },
    [setSearchParams],
  )

  const setSorting = useCallback(
    (next: { id: string; desc: boolean }[]) => {
      setSearchParams(
        (prev) => {
          const params = new URLSearchParams(prev)
          setParam(params, 'page', '1')
          setParam(params, 'sort', JSON.stringify(next))
          return params
        },
        { replace: true },
      )
    },
    [setSearchParams],
  )

  const setFilters = useCallback(
    (next: { id: string; value: unknown }[]) => {
      setSearchParams(
        (prev) => {
          const params = new URLSearchParams(prev)
          setParam(params, 'page', '1')
          setParam(params, 'filters', JSON.stringify(next))
          return params
        },
        { replace: true },
      )
    },
    [setSearchParams],
  )

  // --- Имена пользователей ---
  const names = useMemo(() => {
    const map = new Map<string, string>()
    for (const user of usersQuery.data ?? []) map.set(user.id, user.username)
    return map
  }, [usersQuery.data])

  // --- Данные ---
  const all = tasksQuery.data ?? []
  const items = all.filter((task) => {
    if (status === 'active' && !isActiveTask(task.status)) return false
    if (status !== 'all' && status !== 'active' && task.status !== status) {
      return false
    }
    if (userId !== 'all' && (task.user_id ?? '') !== userId) return false
    return true
  })
  const finishedCount = all.filter((task) => !isActiveTask(task.status)).length

  const isLoading = tasksQuery.isLoading || usersQuery.isLoading
  const isError = tasksQuery.isError || usersQuery.isError
  const error = tasksQuery.error ?? usersQuery.error

  // --- Пагинация с защитой от out-of-bounds ---
  const pageCount = Math.max(1, Math.ceil(items.length / pageSize))
  const safePageIndex = Math.min(pageIndex, pageCount - 1)

  // --- Мутации ---
  const handleCancel = useCallback(
    (taskId: string) => {
      cancel.mutate(taskId)
    },
    [cancel],
  )

  const handleClearFinished = useCallback(() => {
    clearFinished.mutate(undefined)
  }, [clearFinished])

  return {
    data: items,
    all,
    isLoading,
    isError,
    error,
    status,
    userId,
    setStatus,
    setUserId,
    TASK_FILTERS,
    pagination: { pageIndex: safePageIndex, pageSize, pageCount },
    sorting,
    filters,
    setPagination,
    setSorting,
    setFilters,
    handleCancel,
    handleClearFinished,
    finishedCount,
    names,
    cancel,
    clearFinished,
  }
}
