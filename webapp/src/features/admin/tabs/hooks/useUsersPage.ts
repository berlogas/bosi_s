/**
 * Хук для страницы пользователей: данные, сортировка, пагинация, фильтры.
 * Все URL-параметры имеют префикс `users_` чтобы не конфликтовать с другими вкладками.
 */

import { useCallback, useMemo } from 'react'
import { useSearchParams } from 'react-router-dom'

import {
  useAdminUsers,
  useCreateUser,
  useUpdateUser,
  useDeleteUser,
} from '../../queries'
import type { User } from '../../../../api/types'

const PAGE_SIZE_OPTIONS = [10, 25, 50, 100]
const PARAM_PREFIX = 'users_'

function getParam(searchParams: URLSearchParams, key: string): string | null {
  return searchParams.get(`${PARAM_PREFIX}${key}`)
}

function setParam(searchParams: URLSearchParams, key: string, value: string | null) {
  const fullKey = `${PARAM_PREFIX}${key}`
  if (value) searchParams.set(fullKey, value)
  else searchParams.delete(fullKey)
}

export function useUsersPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const usersQuery = useAdminUsers()
  const createUser = useCreateUser()
  const updateUser = useUpdateUser()

  // --- URL state с префиксом ---
  const pageIndex = Math.max(0, Number(getParam(searchParams, 'page')) - 1 || 0)
  const pageSize = Number(getParam(searchParams, 'size')) || 25
  const sorting = useMemo(() => {
    const s = getParam(searchParams, 'sort')
    return s ? JSON.parse(s) : [{ id: 'username', desc: false }]
  }, [searchParams])
  const filters = useMemo(() => {
    const f = getParam(searchParams, 'filters')
    return f ? JSON.parse(f) : []
  }, [searchParams])

  // --- Синхронизация URL ---
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

  // --- Колонки таблицы ---
  const columns = useMemo(() => [
    { id: 'username', accessorKey: 'username', header: 'Логин', cell: (row: User) => row.username },
    { id: 'full_name', accessorKey: 'full_name', header: 'ФИО', cell: (row: User) => row.full_name || '—' },
    { id: 'role', accessorKey: 'role', header: 'Роль', cell: (row: User) => row.role },
    { id: 'is_active', accessorKey: 'is_active', header: 'Активен', cell: (row: User) => row.is_active ? '✓' : '✗' },
  ], [])

  // --- Данные ---
  const data = usersQuery.data ?? []
  const isLoading = usersQuery.isLoading
  const isError = usersQuery.isError
  const error = usersQuery.error

  // --- Пагинация ---
  const pageCount = Math.max(1, Math.ceil(data.length / pageSize))

  // --- Мутации ---
  const handleCreate = useCallback(
    (fields: { username: string; password: string; role: string; full_name?: string }) => {
      createUser.mutate(fields)
    },
    [createUser]
  )

  const handleUpdate = useCallback(
    (userId: string, fields: { username?: string; full_name?: string; role?: string; password?: string; is_active?: boolean }) => {
      updateUser.mutate({ userId, fields })
    },
    [updateUser]
  )

  const deleteMutation = useDeleteUser()

  const handleDelete = useCallback(
    (userId: string) => {
      deleteMutation.mutate(userId)
    },
    [deleteMutation]
  )

  return {
    data,
    isLoading,
    isError,
    error,
    columns,
    pagination: { pageIndex, pageSize, pageCount },
    sorting,
    filters,
    setPagination,
    setSorting,
    setFilters,
    handleCreate,
    handleUpdate,
    handleDelete,
    deleteMutation,
    PAGE_SIZE_OPTIONS,
    ROLES: ['researcher', 'admin'] as const,
  }
}