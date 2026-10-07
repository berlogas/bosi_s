/**
 * Дашборд — паритет frontend/boasi_ui/pages/dashboard.py (Фаза 1).
 *
 * Порядок блоков как в Streamlit: быстрый чат → активные задачи (поллинг
 * 2 с) → создание сессии → мои сессии (active) → «На паузе» → «Архив».
 */

import {
  Alert,
  Button,
  Card,
  Group,
  Loader,
  SimpleGrid,
  Stack,
  Text,
  TextInput,
  Title,
} from '@mantine/core'
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { TaskPanel } from '../../components/TaskPanel'
import { useAuth } from '../auth/authStore'
import { QuickChat } from './QuickChat'
import { SessionCard } from './SessionCard'
import { useActiveTasks, useCreateSession, useSessions } from './queries'

function NewSession() {
  const navigate = useNavigate()
  const [title, setTitle] = useState('')
  const create = useCreateSession()

  function handleSubmit(event: React.FormEvent) {
    event.preventDefault()
    if (!title.trim()) return
    create.mutate(title.trim(), {
      onSuccess: (session) => {
        setTitle('')
        navigate(`/s/${session.id}`)
      },
    })
  }

  return (
    <Card withBorder>
      <form onSubmit={handleSubmit}>
        <Stack gap="sm">
          <Title order={5}>Новая сессия</Title>
          {create.isError && (
            <Alert color="red" role="alert">
              {create.error instanceof Error
                ? create.error.message
                : 'Не удалось создать сессию'}
            </Alert>
          )}
          <Group align="flex-end" wrap="nowrap" gap="xs">
            <TextInput
              label="Название"
              placeholder="Например: Баренцево море, 2026"
              value={title}
              onChange={(event) => setTitle(event.currentTarget.value)}
              style={{ flex: 1 }}
            />
            <Button type="submit" disabled={!title.trim()} loading={create.isPending}>
              Создать
            </Button>
          </Group>
        </Stack>
      </form>
    </Card>
  )
}

function ActiveTasks() {
  const { data: tasks, isPending, isError, error } = useActiveTasks()

  if (isPending) return null
  if (isError) {
    return (
      <Alert color="red">
        Не удалось получить активные задачи:{' '}
        {error instanceof Error ? error.message : 'неизвестная ошибка'}
      </Alert>
    )
  }
  if (!tasks || tasks.length === 0) return null

  return (
    <Card withBorder>
      <Stack gap="xs">
        <Title order={5}>Активные задачи</Title>
        {tasks.map((task) => (
          <TaskPanel key={task.id} task={task} />
        ))}
      </Stack>
    </Card>
  )
}

export function DashboardPage() {
  const user = useAuth((state) => state.user)
  const sessions = useSessions()

  if (sessions.isError) {
    return (
      <Alert color="red" role="alert">
        {sessions.error instanceof Error
          ? sessions.error.message
          : 'Не удалось загрузить сессии'}
      </Alert>
    )
  }

  const all = sessions.data ?? []
  const active = all.filter((session) => session.status === 'active')
  const paused = all.filter((session) => session.status === 'paused')
  const archived = all.filter((session) => session.status === 'archived')

  return (
    <Stack gap="md">
      <Group justify="space-between">
        <Title order={3}>Дашборд</Title>
        {user && (
          <Text size="sm" c="dimmed">
            Здравствуйте, {user.username}!
          </Text>
        )}
      </Group>

      <QuickChat />

      <ActiveTasks />

      <NewSession />

      <Title order={5}>Мои сессии ({active.length})</Title>
      {sessions.isPending ? (
        <Loader size="sm" />
      ) : active.length === 0 ? (
        <Alert color="blue">Активных сессий нет — создайте первую.</Alert>
      ) : (
        <SimpleGrid cols={{ base: 1, sm: 2, lg: 3 }} spacing="sm">
          {active.map((session) => (
            <SessionCard key={session.id} session={session} />
          ))}
        </SimpleGrid>
      )}

      {paused.length > 0 && (
        <Card withBorder>
          <Stack gap="sm">
            <Title order={5}>На паузе ({paused.length})</Title>
            <SimpleGrid cols={{ base: 1, sm: 2 }} spacing="sm">
              {paused.map((session) => (
                <SessionCard key={session.id} session={session} />
              ))}
            </SimpleGrid>
          </Stack>
        </Card>
      )}

      {archived.length > 0 && (
        <Card withBorder>
          <Stack gap="sm">
            <Title order={5}>Архив ({archived.length}) — только чтение</Title>
            <SimpleGrid cols={{ base: 1, sm: 2 }} spacing="sm">
              {archived.map((session) => (
                <SessionCard key={session.id} session={session} />
              ))}
            </SimpleGrid>
          </Stack>
        </Card>
      )}
    </Stack>
  )
}
