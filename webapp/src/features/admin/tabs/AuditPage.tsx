/**
 * Страница «Аудит» админки.
 * SimpleTable + ручной ввод дат (дд.мм.гг) + экспорт CSV.
 */

import React from 'react'
import {
  Stack,
  Title,
  Text,
  Group,
  Button,
  Alert,
  Select,
  TextInput,
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

/** Парсит дату из строки «дд.мм.гг» в ISO «YYYY-MM-DD». Возвращает undefined при невалидном вводе. */
function parseRuDate(value: string): string | undefined {
  const m = value.trim().match(/^(\d{2})\.(\d{2})\.(\d{2})$/)
  if (!m) return undefined
  const [, day, month, year] = m
  const y = 2000 + Number(year)
  const mo = Number(month)
  const d = Number(day)
  const date = new Date(y, mo - 1, d)
  if (date.getFullYear() !== y || date.getMonth() !== mo - 1 || date.getDate() !== d) {
    return undefined
  }
  return `${String(y).padStart(4, '0')}-${String(mo).padStart(2, '0')}-${String(d).padStart(2, '0')}`
}

/** Форматирует ISO дату «YYYY-MM-DD» в «дд.мм.гг». */
function formatRuDate(iso: string | undefined): string {
  if (!iso) return ''
  const d = new Date(iso + 'T00:00:00')
  const day = String(d.getDate()).padStart(2, '0')
  const month = String(d.getMonth() + 1).padStart(2, '0')
  const year = String(d.getFullYear()).slice(-2)
  return `${day}.${month}.${year}`
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
        <TextInput
          label="С"
          placeholder="дд.мм.гг"
          value={formatRuDate(dateFrom)}
          onChange={(event) => {
            const v = event.currentTarget.value.trim()
            if (!v) {
              setDateFrom(undefined)
              return
            }
            const iso = parseRuDate(v)
            setDateFrom(iso)
          }}
          w={110}
          size="xs"
        />
        <TextInput
          label="По"
          placeholder="дд.мм.гг"
          value={formatRuDate(dateTo)}
          onChange={(event) => {
            const v = event.currentTarget.value.trim()
            if (!v) {
              setDateTo(undefined)
              return
            }
            const iso = parseRuDate(v)
            setDateTo(iso)
          }}
          w={110}
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
