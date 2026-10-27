/**
 * Страница «Задачи» админки.
 * SimpleTable с действиями (отмена задачи).
 */

import React from 'react'
import {
  Stack,
  Title,
  Text,
  Group,
  Select,
  Button,
  Alert,
} from '@mantine/core'

import { useTasksPage } from './hooks/useTasksPage'
import { SimpleTable } from '../components'
import { shortWhen } from '../../../lib/format'

function errorText(cause: unknown, fallback: string): string {
  return cause instanceof Error ? cause.message : fallback
}

export default function TasksPage() {
  const {
    data,
    all,
    isLoading,
    isError,
    error,
    status,
    userId,
    setStatus,
    setUserId,
    pagination,
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
  } = useTasksPage()

  // Все хуки и useMemo должны быть до любых early return
  const columns = React.useMemo(() => [
    { id: 'id', accessorKey: 'id', header: 'ID' },
    {
      id: 'title',
      accessorKey: 'title',
      header: 'Название',
      cell: (row: { title: string }) => row.title,
    },
    {
      id: 'status',
      accessorKey: 'status',
      header: 'Статус',
      cell: (row: { status: string }) => row.status,
    },
    {
      id: 'user_id',
      accessorKey: 'user_id',
      header: 'Автор',
      cell: (row: { user_id: string | null }) =>
        names.get(row.user_id ?? '') ?? row.user_id ?? '—',
    },
    {
      id: 'created_at',
      accessorKey: 'created_at',
      header: 'Создано',
      cell: (row: { created_at: string | null }) =>
        shortWhen(row.created_at ?? ''),
    },
    {
      id: 'actions',
      header: 'Действия',
      cell: (row: { id: string; status: string }) => {
        const active = row.status === 'queued' || row.status === 'running'
        return (
          <Group gap="xs" wrap="nowrap">
            <Button
              size="xs"
              variant="subtle"
              color="error"
              disabled={!active || cancel.isPending}
              loading={cancel.isPending}
              onClick={() => handleCancel(row.id)}
            >
              Отменить
            </Button>
          </Group>
        )
      },
    },
  ], [names, handleCancel, cancel.isPending])

  const userOptions = React.useMemo(() => {
    const seen = new Set<string>()
    const opts: { value: string; label: string }[] = [
      { value: 'all', label: 'Все' },
    ]
    for (const task of all) {
      const uid = task.user_id
      if (!uid || seen.has(uid)) continue
      seen.add(uid)
      opts.push({ value: uid, label: names.get(uid) ?? uid.slice(0, 8) })
    }
    return opts
  }, [all, names])

  if (isLoading) return <Text c="dimmed">Загрузка...</Text>
  if (isError) return <Alert color="red">{errorText(error, 'Ошибка загрузки')}</Alert>

  return (
    <Stack gap="sm">
      <Title order={3}>Задачи</Title>

      {/* Фильтры и действие очистки */}
      <Group align="flex-end" gap="sm" wrap="wrap">
        <Select
          label="Статус"
          aria-label="Фильтр: статус задачи"
          data={[
            { value: 'all', label: 'Все' },
            { value: 'active', label: 'Активные' },
            { value: 'done', label: 'Завершённые' },
            { value: 'error', label: 'С ошибкой' },
            { value: 'cancelled', label: 'Отменённые' },
          ]}
          value={status}
          onChange={(value) => value && setStatus(value)}
          allowDeselect={false}
          w={180}
        />
        <Select
          label="Пользователь"
          aria-label="Фильтр: пользователь задачи"
          data={userOptions}
          value={userId}
          onChange={(value) => value && setUserId(value)}
          allowDeselect={false}
          w={200}
        />
        <Text size="xs" c="dimmed">
          {`Показано ${data.length} из ${all.length}`}
        </Text>
        <Button
          color="warning"
          variant="light"
          size="xs"
          style={{ marginLeft: 'auto' }}
          disabled={finishedCount === 0 || clearFinished.isPending}
          loading={clearFinished.isPending}
          onClick={handleClearFinished}
        >
          Очистить завершённые
        </Button>
      </Group>

      {clearFinished.isSuccess && (
        <Text size="sm" c="success" role="status">
          Завершённые задачи убраны.
        </Text>
      )}
      {clearFinished.isError && (
        <Alert color="error" role="alert">
          {errorText(clearFinished.error, 'Не удалось очистить задачи')}
        </Alert>
      )}

      {data.length === 0 && !isLoading && (
        <Text c="dimmed" role="status">Задач нет.</Text>
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
          emptyMessage="Задач нет."
        />
      )}
    </Stack>
  )
}