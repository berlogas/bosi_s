/**
 * Хук для страницы «Сессии» админки: сессии, группировка/фильтр по
 * пользователям, сортировка, пагинация.
 * URL-параметры имеют префикс `sessions_`.
 */

import { useCallback, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'

import {
  useAdminUsers,
  useSessionsTable,
} from '../../queries'
import type { SessionOut } from '../../../../api/types'

const PARAM_PREFIX = 'sessions_'

function getParam(searchParams: URLSearchParams, key: string): string | null {
  return searchParams.get(`${PARAM_PREFIX}${key}`)
}

function setParam(searchParams: URLSearchParams, key: string, value: string | null) {
  const fullKey = `${PARAM_PREFIX}${key}`
  if (value) searchParams.set(fullKey, value)
  else searchParams.delete(fullKey)
}

export function useSessionsPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const usersQuery = useAdminUsers()
  const sessionsQuery = useSessionsTable()

  // --- URL state ---
  const pageIndex = Math.max(0, Number(getParam(searchParams, 'page')) - 1 || 0)
  const pageSize = Number(getParam(searchParams, 'size')) || 25
  const sorting = useMemo(() => {
    const s = getParam(searchParams, 'sort')
    return s ? JSON.parse(s) : [{ id: 'last_activity_at', desc: true }]
  }, [searchParams])
  const filters = useMemo(() => {
    const f = getParam(searchParams, 'filters')
    return f ? JSON.parse(f) : []
  }, [searchParams])

  // --- Фильтр по пользователю ---
  const [userId, setUserIdState] = useState<string>(
    getParam(searchParams, 'user') ?? 'all'
  )

  const setUserId = useCallback(
    (v: string) => {
      setUserIdState(v)
      const params = new URLSearchParams(searchParams)
      setParam(params, 'user', v)
      setParam(params, 'page', '1')
      setSearchParams(params, { replace: true })
    },
    [searchParams, setSearchParams]
  )

  // --- Синхронизация URL для таблицы ---
  const setPagination = useCallback(
    (next: { pageIndex: number; pageSize: number; pageCount: number }) => {
      const params = new URLSearchParams(searchParams)
      setParam(params, 'page', String(next.pageIndex + 1))
      setParam(params, 'size', String(next.pageSize))
      setSearchParams(params, { replace: true })
    },
    [searchParams, setSearchParams]
  )

  const setSorting = useCallback(
    (next: { id: string; desc: boolean }[]) => {
      const params = new URLSearchParams(searchParams)
      setParam(params, 'page', '1')
      setParam(params, 'sort', JSON.stringify(next))
      setSearchParams(params, { replace: true })
    },
    [searchParams, setSearchParams]
  )

  const setFilters = useCallback(
    (next: { id: string; value: unknown }[]) => {
      const params = new URLSearchParams(searchParams)
      setParam(params, 'page', '1')
      setParam(params, 'filters', JSON.stringify(next))
      setSearchParams(params, { replace: true })
    },
    [searchParams, setSearchParams]
  )

  // --- Имена пользователей ---
  const names = useMemo(() => {
    const map = new Map<string, string>()
    for (const user of usersQuery.data ?? []) map.set(user.id, user.username)
    return map
  }, [usersQuery.data])

  // --- Данные ---
  const all = sessionsQuery.data ?? []
  const items = all.filter((session) => {
    if (userId !== 'all' && (session.user_id ?? '') !== userId) return false
    return true
  })

  const isLoading = sessionsQuery.isLoading || usersQuery.isLoading
  const isError = sessionsQuery.isError || usersQuery.isError
  const error = sessionsQuery.error ?? usersQuery.error

  // --- Группировка по пользователям ---
  const grouped = useMemo(() => {
    const byUser = new Map<string, SessionOut[]>()
    for (const session of items) {
      const bucket = byUser.get(session.user_id ?? '') ?? []
      bucket.push(session)
      byUser.set(session.user_id ?? '', bucket)
    }
    return [...byUser.entries()]
      .map(([uid, rows]) => ({
        userId: uid,
        label: names.get(uid) ?? uid.slice(0, 8),
        rows: rows.sort(
          (a, b) =>
            (b.last_activity_at ?? '').localeCompare(a.last_activity_at ?? '')
        ),
      }))
      .sort((a, b) => a.label.localeCompare(b.label))
  }, [items, names])

  // --- Пагинация ---
  const pageCount = Math.max(1, Math.ceil(items.length / pageSize))
  const safePageIndex = Math.min(pageIndex, pageCount - 1)

  return {
    data: items,
    all,
    grouped,
    isLoading,
    isError,
    error,
    userId,
    setUserId,
    names,
    pagination: { pageIndex: safePageIndex, pageSize, pageCount },
    sorting,
    filters,
    setPagination,
    setSorting,
    setFilters,
  }
}