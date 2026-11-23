/**
 * Страница «Сессии» админки.
 * SimpleTable с группировкой/фильтром по пользователям.
 */

import React from 'react'
import { Stack, Title, Text, Group, Select, Alert, Button, Modal } from '@mantine/core'

import { useSessionsPage } from './hooks/useSessionsPage'
import { useClearMessages } from '../../chat/queries'
import { SimpleTable } from '../components'
import { EmptyState } from '../../../components/EmptyState'
import { shortWhen, fullWhen } from '../../../lib/format'
import { IconLayoutDashboard } from '@tabler/icons-react'

function errorText(cause: unknown, fallback: string): string {
  return cause instanceof Error ? cause.message : fallback
}

/**
 * Очистка переписки из админки — как кнопка «Очистить чат» в самой сессии:
 * два шага, документы и заметки сессии не трогаются.
 */
function ClearChatCell({ sessionId }: { sessionId: string }) {
  const [ask, setAsk] = React.useState(false)
  const [error, setError] = React.useState<string | null>(null)
  const clear = useClearMessages(sessionId)

  return (
    <>
      <Button
        size="compact-xs"
        variant="subtle"
        color="error"
        onClick={() => setAsk(true)}
      >
        Очистить чат
      </Button>
      <Modal
        opened={ask}
        onClose={() => setAsk(false)}
        title="Очистить переписку?"
        centered
      >
        <Stack>
          <Text size="sm">
            Удалить всю переписку этой сессии? Отменить будет нельзя.
          </Text>
          {error && (
            <Alert color="error" role="alert">
              {error}
            </Alert>
          )}
          <Group justify="flex-end">
            <Button variant="default" onClick={() => setAsk(false)}>
              Отмена
            </Button>
            <Button
              color="error"
              loading={clear.isPending}
              onClick={() => {
                setError(null)
                clear.mutate(undefined, {
                  onSuccess: () => setAsk(false),
                  onError: (cause) =>
                    setError(errorText(cause, 'Не удалось очистить переписку')),
                })
              }}
            >
              Да, очистить
            </Button>
          </Group>
        </Stack>
      </Modal>
    </>
  )
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

  const columns = React.useMemo(
    () => [
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
      {
        id: 'actions',
        header: 'Действия',
        cell: (row: { id: string }) => <ClearChatCell sessionId={row.id} />,
      },
    ],
    [names],
  )

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
            0,
          )} всего`}
        </Text>
      </Group>

      {data.length === 0 && !isLoading && (
        <EmptyState
          title="Сессий нет"
          description="Сессии появляются в чате после первого вопроса исследователя."
          icon={<IconLayoutDashboard size={32} />}
        />
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
          isLoading={isLoading}
          emptyMessage="Сессий нет."
        />
      )}
    </Stack>
  )
}
