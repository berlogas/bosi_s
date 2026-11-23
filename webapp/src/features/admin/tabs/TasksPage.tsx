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
  Paper,
  Progress,
} from '@mantine/core'
import { useNavigate } from 'react-router-dom'

import { useTasksPage } from './hooks/useTasksPage'
import { SimpleTable } from '../components'
import { shortWhen } from '../../../lib/format'
import type { Task } from '../../../api/types'

function errorText(cause: unknown, fallback: string): string {
  return cause instanceof Error ? cause.message : fallback
}

/** Документы в результате задачи: у загрузок и индексаций это `result.added`. */
function taskDocuments(task: Task): { id: string; title: string }[] {
  const result = task.result
  if (!result || typeof result !== 'object') return []
  const added = (result as { added?: unknown }).added
  if (!Array.isArray(added)) return []
  return added.flatMap((item) => {
    if (!item || typeof item !== 'object') return []
    const doc = item as { id?: unknown; title?: unknown }
    return [{ id: String(doc.id ?? ''), title: String(doc.title ?? doc.id ?? '') }]
  })
}

/**
 * Панель незавершённых задач: прогресс, текущий этап и ошибка.
 *
 * В таблице задач прогресса нет — там одна строка на задачу, а админ
 * смотрит, что задача делается и чем кончилась.
 */
function TaskProgressPanel({ task }: { task: Task }) {
  const progress = task.progress ?? 0
  return (
    <Paper withBorder p="xs">
      <Group justify="space-between" gap="xs" wrap="nowrap">
        <Text size="sm" fw={500}>
          {task.title}
        </Text>
        <Text size="sm" c="dimmed">{`${progress}%`}</Text>
      </Group>
      {task.step && (
        <Text size="xs" c="dimmed">
          {task.step}
        </Text>
      )}
      <Progress value={progress} size="sm" mt={4} />
      {task.error && (
        <Alert color="red" role="alert" mt="xs">
          {task.error}
        </Alert>
      )}
    </Paper>
  )
}

/** Ссылки «куда смотреть результат»: сессия, проекты и документы задачи. */
function TaskLinks({ task }: { task: Task }) {
  const navigate = useNavigate()
  const documents = taskDocuments(task)
  if (!task.session_id && documents.length === 0) return null
  return (
    <Group gap="xs" wrap="nowrap">
      {task.session_id && (
        <Button
          size="compact-xs"
          variant="subtle"
          onClick={() => navigate(`/s/${task.session_id}`)}
          aria-label={`Открыть сессию задачи ${task.title}`}
        >
          Открыть сессию
        </Button>
      )}
      {task.project_id && task.session_id && (
        <Button
          size="compact-xs"
          variant="subtle"
          onClick={() => navigate(`/s/${task.session_id}/projects`)}
          aria-label={`Открыть проекты задачи ${task.title}`}
        >
          Открыть проекты
        </Button>
      )}
      {documents.length > 0 && task.session_id && (
        <Button
          size="compact-xs"
          variant="subtle"
          onClick={() => navigate(`/s/${task.session_id}/documents`)}
          aria-label={`Документы задачи ${task.title}`}
        >
          {`Документы (${documents.length})`}
        </Button>
      )}
    </Group>
  )
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
  // Незавершённые задачи: показываем прогресс и ошибку отдельной панелью.
  // Панель уважает фильтры — иначе отфильтрованная задача осталась бы на экране.
  const liveTasks = React.useMemo(
    () =>
      (data as Task[]).filter(
        (task) =>
          task.status === 'queued' ||
          task.status === 'running' ||
          task.status === 'error',
      ),
    [data],
  )

  const columns = React.useMemo(
    () => [
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
        cell: (row: { created_at: string | null }) => shortWhen(row.created_at ?? ''),
      },
      {
        id: 'actions',
        header: 'Действия',
        cell: (row: {
          id: string
          status: string
          title: string
          session_id?: string | null
          project_id?: string | null
          result?: unknown
        }) => {
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
              <TaskLinks task={row as Task} />
            </Group>
          )
        },
      },
    ],
    [names, handleCancel, cancel.isPending],
  )

  const userOptions = React.useMemo(() => {
    const seen = new Set<string>()
    const opts: { value: string; label: string }[] = [{ value: 'all', label: 'Все' }]
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
        <Text c="dimmed" role="status">
          Задач нет.
        </Text>
      )}

      {/* Панель незавершённых задач: прогресс и ошибка — их в таблице нет. */}
      {liveTasks.length > 0 && (
        <Stack gap="xs">
          {liveTasks.map((task) => (
            <TaskProgressPanel key={task.id} task={task} />
          ))}
        </Stack>
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
          emptyMessage="Задач нет."
        />
      )}
    </Stack>
  )
}
