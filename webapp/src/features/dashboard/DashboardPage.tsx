/**
 * Информационная панель (дашборд) — паритет Streamlit-версии dashboard.py (Фаза 1).
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

import type { SessionOut } from '../../api/types'

import { TaskPanel } from '../../components/TaskPanel'
import { displayName } from '../../lib/roles'
import { useAuth } from '../auth/authStore'
import { QuickChat } from './QuickChat'
import { SessionCard } from './SessionCard'
import { useActiveTasks, useCancelTask, useCreateSession, useSessions } from './queries'

interface OwnerGroup {
  ownerId: string
  label: string
  sessions: SessionOut[]
}

/** Имя владельца для заголовка группы: ФИО при наличии, иначе логин. */
export function ownerLabel(username: string, fullName?: string | null): string {
  return fullName?.trim() ? `${fullName} (${username})` : username
}

/**
 * Раскладывает сессии по владельцам. Свои сессии текущего пользователя —
 * первыми, остальные группы по алфавиту логина, внутри группы сессии уже
 * приходят отсортированными по последней активности.
 */
export function groupByOwner(
  sessions: SessionOut[],
  currentUserId?: string,
): OwnerGroup[] {
  const groups = new Map<string, OwnerGroup>()
  for (const session of sessions) {
    const key = session.owner_username || session.user_id
    let group = groups.get(key)
    if (!group) {
      group = {
        ownerId: session.user_id,
        label: ownerLabel(
          session.owner_username || session.user_id,
          session.owner_full_name,
        ),
        sessions: [],
      }
      groups.set(key, group)
    }
    group.sessions.push(session)
  }
  return [...groups.values()].sort((a, b) => {
    if (currentUserId) {
      if (a.ownerId === currentUserId) return -1
      if (b.ownerId === currentUserId) return 1
    }
    return a.label.localeCompare(b.label, 'ru')
  })
}

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
  const cancel = useCancelTask()

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
          <TaskPanel
            key={task.id}
            task={task}
            onCancel={(target) => cancel.mutate(target.id)}
            cancelPending={cancel.isPending}
          />
        ))}
      </Stack>
    </Card>
  )
}

/**
 * Группировка карточек по владельцу — для администратора.
 *
 * Исследователю группы не нужны: у него сессии только свои, и заголовок
 * с его же именем ничего не добавляет. Администратор видит общий список,
 * где вперемешку чужие сессии, поэтому сначала идут его собственные
 * (иначе «свои» карточки теряются в общем списке), остальные — по имени.
 */
function SessionGroups({
  sessions,
  isAdmin,
}: {
  sessions: SessionOut[]
  isAdmin: boolean
}) {
  const currentUser = useAuth((state) => state.user)
  const groups = groupByOwner(sessions, currentUser?.id)
  return (
    <Stack gap="md">
      {groups.map((group) => (
        <Stack key={group.ownerId} gap="xs">
          <Text size="sm" fw={600}>
            {group.label} ({group.sessions.length})
          </Text>
          <SimpleGrid cols={{ base: 1, sm: 2, lg: 3 }} spacing="sm">
            {group.sessions.map((session) => (
              <SessionCard key={session.id} session={session} />
            ))}
          </SimpleGrid>
        </Stack>
      ))}
      {groups.length === 0 && (
        <Alert color="blue">
          {isAdmin
            ? 'Сессий нет — создайте первую.'
            : 'Активных сессий нет — создайте первую.'}
        </Alert>
      )}
    </Stack>
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
  const isAdmin = user?.role === 'admin'

  return (
    <Stack gap="md">
      <Group justify="space-between">
        <Title order={3}>Информационная панель</Title>
        {user && (
          <Text size="sm" c="dimmed">
            Здравствуйте, {displayName(user)}!
          </Text>
        )}
      </Group>

      <QuickChat />

      <ActiveTasks />

      <NewSession />

      <Title order={5}>
        {isAdmin ? 'Сессии всех пользователей' : 'Мои сессии'} ({active.length})
      </Title>
      {sessions.isPending ? (
        <Loader size="sm" />
      ) : (
        <SessionGroups sessions={active} isAdmin={isAdmin} />
      )}

      {paused.length > 0 && (
        <Card withBorder>
          <Stack gap="sm">
            <Title order={5}>На паузе ({paused.length})</Title>
            <SessionGroups sessions={paused} isAdmin={isAdmin} />
          </Stack>
        </Card>
      )}

      {archived.length > 0 && (
        <Card withBorder>
          <Stack gap="sm">
            <Title order={5}>Архив ({archived.length}) — только чтение</Title>
            <SessionGroups sessions={archived} isAdmin={isAdmin} />
          </Stack>
        </Card>
      )}
    </Stack>
  )
}
