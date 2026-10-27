/**
 * Страница «Сессии» админки.
 * SimpleTable с группировкой/фильтром по пользователям.
 */

import React from 'react'
import {
  Stack,
  Title,
  Text,
  Group,
  Select,
  Alert,
} from '@mantine/core'

import { useSessionsPage } from './hooks/useSessionsPage'
import { SimpleTable } from '../components'
import { shortWhen, fullWhen } from '../../../lib/format'

function errorText(cause: unknown, fallback: string): string {
  return cause instanceof Error ? cause.message : fallback
}

export default function SessionsPage() {
  const {
    data,
    grouped,
    isLoading,
    isError,
    error,
    userId,
    setUserId,
    names,
    pagination,
    sorting,
    filters,
    setPagination,
    setSorting,
    setFilters,
  } = useSessionsPage()

  // Все useMemo до early return
  const userOptions = React.useMemo(() => {
    const opts: { value: string; label: string }[] = [
      { value: 'all', label: 'Все пользователи' },
    ]
    for (const [uid, label] of names.entries()) {
      opts.push({ value: uid, label })
    }
    return opts
  }, [names])

  const columns = React.useMemo(() => [
    { id: 'id', accessorKey: 'id', header: 'ID' },
    {
      id: 'title',
      accessorKey: 'title',
      header: 'Название',
      cell: (row: { title: string }) => row.title || '—',
    },
    {
      id: 'status',
      accessorKey: 'status',
      header: 'Статус',
      cell: (row: { status: string }) => row.status || '—',
    },
    {
      id: 'user_id',
      accessorKey: 'user_id',
      header: 'Пользователь',
      cell: (row: { user_id: string | null }) =>
        names.get(row.user_id ?? '') ?? row.user_id ?? '—',
    },
    {
      id: 'last_activity_at',
      accessorKey: 'last_activity_at',
      header: 'Активность',
      cell: (row: { last_activity_at: string | null }) => {
        const v = row.last_activity_at ?? ''
        return v ? <span title={fullWhen(v)}>{shortWhen(v)}</span> : '—'
      },
    },
  ], [names])

  if (isLoading) return <Text c="dimmed">Загрузка...</Text>
  if (isError) return <Alert color="red">{errorText(error, 'Ошибка загрузки')}</Alert>

  return (
    <Stack gap="sm">
      <Title order={3}>Сессии</Title>

      <Group align="flex-end" gap="sm" wrap="wrap">
        <Select
          label="Пользователь"
          aria-label="Фильтр: пользователь сессии"
          data={userOptions}
          value={userId}
          onChange={(value) => value && setUserId(value)}
          allowDeselect={false}
          w={220}
        />
        <Text size="xs" c="dimmed">
          {`Показано ${data.length} сессий из ${grouped.reduce(
            (acc, g) => acc + g.rows.length,
            0
          )} всего`}
        </Text>
      </Group>

      {data.length === 0 && !isLoading && (
        <Text c="dimmed" role="status">Сессий нет.</Text>
      )}

      {data.length > 0 && (
        <SimpleTable
          columns={columns as never}
          data={data as never}
          pagination={pagination}
          onPaginationChange={setPagination}
          sorting={sorting}
          onSortingChange={setSorting}
          filters={filters}
          onFiltersChange={setFilters}
          rowActions={() => null}
          isLoading={isLoading}
          emptyMessage="Сессий нет."
        />
      )}
    </Stack>
  )
}
