/**
 * Страница «Аудит» админки.
 * SimpleTable + DatePicker фильтры + экспорт CSV.
 */

import React from 'react'
import { DatePickerInput } from '@mantine/dates'
import {
  Stack,
  Title,
  Text,
  Group,
  Button,
  Alert,
  Box,
  Select,
} from '@mantine/core'
import { useAuditPage } from './hooks/useAuditPage'
import { SimpleTable } from '../components'
import { dayWhen } from '../../../lib/format'

const AUDIT_PERIODS = [
  { value: 'all', label: 'Всё время', days: 0 },
  { value: '7', label: '7 дней', days: 7 },
  { value: '30', label: '30 дней', days: 30 },
  { value: '90', label: '90 дней', days: 90 },
] as const

function errorText(cause: unknown, fallback: string): string {
  return cause instanceof Error ? cause.message : fallback
}

export default function AuditPage() {
  const {
    data,
    isLoading,
    isError,
    error,
    total,
    oldestAt,
    dateFrom,
    dateTo,
    setDateFrom,
    setDateTo,
    pagination,
    sorting,
    filters,
    setPagination,
    setSorting,
    setFilters,
    exportUrl,
  } = useAuditPage()

  // Все useMemo до early return
  const columns = React.useMemo(() => [
    { id: 'created_at', accessorKey: 'created_at', header: 'Время' },
    {
      id: 'actor_username',
      accessorKey: 'actor_username',
      header: 'Кто',
      cell: (row: { actor_username: string | null }) => row.actor_username ?? '—',
    },
    {
      id: 'action',
      accessorKey: 'action',
      header: 'Действие',
      cell: (row: { action: string }) => row.action,
    },
    {
      id: 'target_type',
      accessorKey: 'target_type',
      header: 'Цель',
      cell: (row: { target_type: string | null }) => row.target_type ?? '—',
    },
    {
      id: 'ok',
      accessorKey: 'ok',
      header: 'OK',
      cell: (row: { ok: boolean }) => (row.ok ? '✓' : '✗'),
    },
    {
      id: 'ip',
      accessorKey: 'ip',
      header: 'IP',
      cell: (row: { ip: string | null }) => row.ip ?? '—',
    },
  ], [])

  if (isLoading) return <Text c="dimmed">Загрузка...</Text>
  if (isError) return <Alert color="red">{errorText(error, 'Ошибка загрузки')}</Alert>

  return (
    <Stack gap="sm">
      <Title order={3}>Аудит</Title>

      <Group align="flex-end" gap="sm" wrap="wrap">
        <Select
          label="Период"
          aria-label="Фильтр: период журнала"
          data={AUDIT_PERIODS.map(({ value, label }) => ({ value, label }))}
          value={dateFrom ? 'custom' : (oldestAt ? 'all' : 'all')}
          onChange={(value) => {
            if (!value) return
            if (value === 'all') {
              setDateFrom(undefined)
              setDateTo(undefined)
            } else {
              const period = AUDIT_PERIODS.find((p) => p.value === value)
              if (period && period.days > 0) {
                const date = new Date()
                date.setDate(date.getDate() - period.days)
                date.setHours(0, 0, 0, 0)
                setDateFrom(date.toISOString())
                setDateTo(undefined)
              }
            }
          }}
          allowDeselect={false}
          w={150}
        />
        <DatePickerInput
          label="С"
          placeholder="с"
          value={dateFrom ? new Date(dateFrom) : undefined}
          onChange={(date) => setDateFrom(date ? date.toISOString() : undefined)}
          w={130}
          size="xs"
        />
        <DatePickerInput
          label="По"
          placeholder="по"
          value={dateTo ? new Date(dateTo) : undefined}
          onChange={(date) => setDateTo(date ? date.toISOString() : undefined)}
          w={130}
          size="xs"
        />
        <Button
          size="xs"
          variant="outline"
          component="a"
          href={exportUrl}
          download
          aria-label="Выгрузить журнал в CSV"
        >
          Выгрузить CSV
        </Button>
        <Text size="xs" c="dimmed" role="status">
          {total === null
            ? 'считаем журнал…'
            : `всего записей: ${total}${
                oldestAt ? `, самые старые от ${dayWhen(oldestAt)}` : ''
              }`}
        </Text>
      </Group>

      {data.length === 0 && !isLoading && (
        <Text c="dimmed" role="status">Записей аудита нет.</Text>
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
          emptyMessage="Записей аудита нет."
        />
      )}
    </Stack>
  )
}
