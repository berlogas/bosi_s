/**
 * Хук для страницы «Аудит» админки: записи аудита, фильтры по датам,
 * сортировка, пагинация, экспорт CSV.
 * URL-параметры имеют префикс `audit_`.
 */

import { useCallback, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'

import { useAudit, useAuditStats } from '../../queries'

const PARAM_PREFIX = 'audit_'

function getParam(searchParams: URLSearchParams, key: string): string | null {
  return searchParams.get(`${PARAM_PREFIX}${key}`)
}

function setParam(searchParams: URLSearchParams, key: string, value: string | null) {
  const fullKey = `${PARAM_PREFIX}${key}`
  if (value) searchParams.set(fullKey, value)
  else searchParams.delete(fullKey)
}

export function useAuditPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const statsQuery = useAuditStats()

  // --- Фильтры по датам (DatePicker) ---
  const [dateFrom, setDateFrom] = useState<string | undefined>(
    getParam(searchParams, 'from') || undefined,
  )
  const [dateTo, setDateTo] = useState<string | undefined>(
    getParam(searchParams, 'to') || undefined,
  )

  const setDateFromValue = useCallback(
    (v: string | undefined) => {
      setDateFrom(v)
      setSearchParams(
        (prev) => {
          const params = new URLSearchParams(prev)
          if (v) setParam(params, 'from', v)
          else searchParams.delete(`${PARAM_PREFIX}from`)
          setParam(params, 'page', '1')
          return params
        },
        { replace: true },
      )
    },
    [searchParams, setSearchParams],
  )

  const setDateToValue = useCallback(
    (v: string | undefined) => {
      setDateTo(v)
      setSearchParams(
        (prev) => {
          const params = new URLSearchParams(prev)
          if (v) setParam(params, 'to', v)
          else searchParams.delete(`${PARAM_PREFIX}to`)
          setParam(params, 'page', '1')
          return params
        },
        { replace: true },
      )
    },
    [searchParams, setSearchParams],
  )

  // --- since для запроса (dateFrom имеет приоритет) ---
  const since = useMemo(() => {
    if (dateFrom) return dateFrom
    return undefined
  }, [dateFrom])

  const auditQuery = useAudit(since)

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

  // --- Данные ---
  const rows = useMemo(() => {
    const items = auditQuery.data ? [...auditQuery.data] : []
    items.sort((a, b) =>
      sorting[0]?.desc
        ? (b.created_at ?? '').localeCompare(a.created_at ?? '')
        : (a.created_at ?? '').localeCompare(b.created_at ?? ''),
    )
    // Фильтрация по dateTo (до данной даты включительно)
    if (dateTo) {
      const to = new Date(dateTo)
      to.setHours(23, 59, 59, 999)
      return items.filter((item) => new Date(item.created_at ?? '') <= to)
    }
    return items
  }, [auditQuery.data, sorting, dateTo])

  const isLoading = auditQuery.isLoading || statsQuery.isLoading
  const isError = auditQuery.isError || statsQuery.isError
  const error = auditQuery.error ?? statsQuery.error

  // --- Пагинация ---
  const pageCount = Math.max(1, Math.ceil(rows.length / pageSize))
  const safePageIndex = Math.min(pageIndex, pageCount - 1)

  // --- Экспорт CSV ---
  const exportUrl = useMemo(() => {
    const params = new URLSearchParams({ limit: '10000' })
    if (since) params.set('since', since)
    return `/api/admin/audit/export?${params.toString()}`
  }, [since])

  return {
    data: rows,
    isLoading,
    isError,
    error,
    total: statsQuery.data?.total ?? null,
    oldestAt: statsQuery.data?.oldest_at ?? null,
    dateFrom,
    dateTo,
    setDateFrom: setDateFromValue,
    setDateTo: setDateToValue,
    pagination: { pageIndex: safePageIndex, pageSize, pageCount },
    sorting,
    filters,
    setPagination,
    setSorting,
    setFilters,
    exportUrl,
  }
}
