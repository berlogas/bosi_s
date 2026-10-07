/**
 * Админка — паритет Streamlit-версии admin.py (Фаза 4).
 *
 * Пять вкладок как в st.tabs: Пользователи, Глобальная база, Задачи,
 * Сессии, Аудит. Вход только для роли admin (в Streamlit — guard в
 * render()). Тексты кнопок/сообщений 1-в-1 с admin.py.
 */

import {
  Accordion,
  Alert,
  Button,
  FileInput,
  Group,
  Loader,
  Pagination,
  Paper,
  Select,
  Stack,
  Table,
  Tabs,
  Text,
  Textarea,
  TextInput,
  Title,
} from '@mantine/core'
import { useMemo, useState } from 'react'

import type { AuditLogEntry, User } from '../../api/types'
import { TaskPanel } from '../../components/TaskPanel'
import { shortWhen } from '../../lib/format'
import { useAuth } from '../auth/authStore'
import {
  useAdminAddPath,
  useAdminCancelTask,
  useAdminDeleteDocument,
  useAdminDocuments,
  useAdminReindex,
  useAdminTasks,
  useAdminUpload,
  useAdminUsers,
  useAudit,
  useBulkIndex,
  useCreateUser,
  useSessionsTable,
  useUpdateUser,
} from './queries'

const ROLES = ['researcher', 'admin']

/** Текст ошибки мутации/запроса — общий паттерн проекта. */
function errorText(cause: unknown, fallback: string): string {
  return cause instanceof Error ? cause.message : fallback
}
const AUDIT_PAGE_SIZE = 50

// ------------------------------------------------------------------ пользователи

function CreateUser() {
  const create = useCreateUser()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [fullName, setFullName] = useState('')
  const [role, setRole] = useState('researcher')
  const [done, setDone] = useState(false)

  return (
    <Accordion>
      <Accordion.Item value="create">
        <Accordion.Control>Создать пользователя</Accordion.Control>
        <Accordion.Panel>
          <form
            onSubmit={(event) => {
              event.preventDefault()
              setDone(false)
              create.mutate(
                {
                  username: username.trim(),
                  password,
                  role,
                  full_name: fullName.trim() || undefined,
                },
                {
                  onSuccess: () => {
                    setDone(true)
                    setUsername('')
                    setPassword('')
                    setFullName('')
                  },
                },
              )
            }}
          >
            <Stack gap="sm">
              {create.isError && (
                <Alert color="red" role="alert">
                  {errorText(create.error, 'Ошибка запроса')}
                </Alert>
              )}
              {done && (
                <Alert color="green" role="status">
                  Пользователь создан.
                </Alert>
              )}
              <Group align="flex-end" wrap="nowrap" gap="xs">
                <TextInput
                  label="Логин"
                  value={username}
                  onChange={(event) => setUsername(event.currentTarget.value)}
                  style={{ flex: 1 }}
                  required
                />
                <TextInput
                  label="Пароль"
                  type="password"
                  value={password}
                  onChange={(event) => setPassword(event.currentTarget.value)}
                  style={{ flex: 1 }}
                  required
                />
                <TextInput
                  label="ФИО"
                  value={fullName}
                  onChange={(event) => setFullName(event.currentTarget.value)}
                  style={{ flex: 1 }}
                />
                <Select
                  label="Роль"
                  data={ROLES}
                  value={role}
                  onChange={(value) => value && setRole(value)}
                  allowDeselect={false}
                  w={150}
                />
                <Button
                  type="submit"
                  loading={create.isPending}
                  disabled={!username || password.length < 8}
                >
                  Создать
                </Button>
              </Group>
            </Stack>
          </form>
        </Accordion.Panel>
      </Accordion.Item>
    </Accordion>
  )
}

function UserRow({ user }: { user: User }) {
  const update = useUpdateUser()
  const [role, setRole] = useState<string>(
    ROLES.includes(user.role) ? user.role : 'researcher',
  )
  const [password, setPassword] = useState('')
  const [saved, setSaved] = useState(false)
  const canSave = (role !== user.role || password) && !update.isPending

  return (
    <tr>
      <td>
        <Text size="sm">
          <b>{user.username}</b> · {user.full_name ?? ''}
        </Text>
      </td>
      <td>
        <Select
          label="Роль"
          aria-label={`Роль: ${user.username}`}
          data={ROLES}
          value={role}
          onChange={(value) => value && setRole(value)}
          allowDeselect={false}
          disabled={update.isPending}
          w={160}
        />
      </td>
      <td>
        <TextInput
          label="Новый пароль"
          aria-label={`Новый пароль: ${user.username}`}
          type="password"
          value={password}
          onChange={(event) => setPassword(event.currentTarget.value)}
          disabled={update.isPending}
        />
      </td>
      <td>
        <Group gap="xs" wrap="nowrap">
          <Button
            size="xs"
            disabled={!canSave}
            loading={update.isPending && update.variables?.userId === user.id}
            onClick={() => {
              setSaved(false)
              const fields: { role: string; password?: string } = { role }
              if (password) fields.password = password
              update.mutate(
                { userId: user.id, fields },
                {
                  onSuccess: () => {
                    setSaved(true)
                    setPassword('')
                  },
                },
              )
            }}
          >
            Сохранить
          </Button>
          {saved && (
            <Text size="sm" c="green" role="status">
              Сохранено.
            </Text>
          )}
          {update.isError && update.variables?.userId === user.id && (
            <Text size="sm" c="red" role="alert">
              {errorText(update.error, 'Ошибка запроса')}
            </Text>
          )}
        </Group>
      </td>
    </tr>
  )
}

function UsersTab() {
  const users = useAdminUsers()

  if (users.isPending) return <Loader size="sm" />
  if (users.isError) {
    return (
      <Alert color="red" role="alert">
        {errorText(users.error, 'Ошибка запроса')}
      </Alert>
    )
  }

  return (
    <Stack gap="sm">
      <CreateUser />
      {users.data.length === 0 && <Text c="dimmed">Пользователей нет.</Text>}
      {users.data.length > 0 && (
        <Table>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Пользователь</Table.Th>
              <Table.Th>Роль</Table.Th>
              <Table.Th>Пароль</Table.Th>
              <Table.Th />
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {users.data.map((user) => (
              <UserRow key={user.id} user={user} />
            ))}
          </Table.Tbody>
        </Table>
      )}
    </Stack>
  )
}

// -------------------------------------------------------------- глобальная база

function GlobalBaseTab() {
  const addPath = useAdminAddPath()
  const upload = useAdminUpload()
  const reindex = useAdminReindex()
  const remove = useAdminDeleteDocument()
  const documents = useAdminDocuments()
  const bulk = useBulkIndex()

  const [path, setPath] = useState('')
  const [files, setFiles] = useState<File[] | null>(null)
  const [bulkText, setBulkText] = useState('')
  const [message, setMessage] = useState<string | null>(null)
  const [bulkMessage, setBulkMessage] = useState<string | null>(null)
  const [reindexDone, setReindexDone] = useState(false)

  return (
    <Stack gap="sm">
      {message && (
        <Alert color="green" role="status">
          {message}
        </Alert>
      )}

      <Group align="flex-end" gap="sm" wrap="nowrap">
        <TextInput
          label="Путь к файлу"
          value={path}
          onChange={(event) => setPath(event.currentTarget.value)}
          style={{ flex: 1 }}
        />
        <Button
          loading={addPath.isPending}
          disabled={!path.trim()}
          onClick={() => {
            setMessage(null)
            addPath.mutate(path.trim(), {
              onSuccess: () => {
                setMessage('Добавлено.')
                setPath('')
              },
            })
          }}
        >
          Добавить
        </Button>
      </Group>
      {addPath.isError && (
        <Alert color="red" role="alert">
          {errorText(addPath.error, 'Ошибка запроса')}
        </Alert>
      )}

      <Group align="flex-end" gap="sm" wrap="nowrap">
        <FileInput
          label="Или файлы"
          multiple
          value={files ?? undefined}
          onChange={setFiles}
          style={{ flex: 1 }}
        />
        <Button
          disabled={!files || files.length === 0}
          loading={upload.isPending}
          onClick={() => {
            setMessage(null)
            upload.mutate(
              { files: files ?? [], tags: '' },
              {
                onSuccess: (result) => {
                  setMessage(`Добавлено ${(result.added ?? []).length}`)
                  setFiles(null)
                },
              },
            )
          }}
        >
          Загрузить
        </Button>
      </Group>
      {upload.isError && (
        <Alert color="red" role="alert">
          {errorText(upload.error, 'Ошибка запроса')}
        </Alert>
      )}

      <Title order={5}>Массовая индексация</Title>
      <Text size="sm" c="dimmed">
        Фоновый режим: можно свернуть и отменить
      </Text>
      <Textarea
        label="Пути через запятую или по одному в строке"
        value={bulkText}
        onChange={(event) => setBulkText(event.currentTarget.value)}
        autosize
        minRows={3}
      />
      <Group>
        <Button
          loading={bulk.isPending}
          onClick={() => {
            const paths = bulkText
              .replace(/,/g, '\n')
              .split('\n')
              .map((line) => line.trim())
              .filter(Boolean)
            if (paths.length === 0) {
              setBulkMessage('Укажите хотя бы один путь.')
              return
            }
            setBulkMessage(null)
            bulk.mutate(paths, {
              onSuccess: (task) =>
                setBulkMessage(`Задача поставлена: ${task.total} файлов`),
            })
          }}
        >
          Запустить индексацию
        </Button>
        <Button
          color="orange"
          loading={reindex.isPending}
          onClick={() => {
            setReindexDone(false)
            reindex.mutate(undefined, { onSuccess: () => setReindexDone(true) })
          }}
        >
          Переиндексировать всё
        </Button>
      </Group>
      {bulkMessage && (
        <Alert
          color={bulk.isError || bulkMessage.startsWith('Укажите') ? 'red' : 'green'}
          role={bulk.isError || bulkMessage.startsWith('Укажите') ? 'alert' : 'status'}
        >
          {bulk.isError ? errorText(bulk.error, 'Ошибка запроса') : bulkMessage}
        </Alert>
      )}
      {reindex.isError && (
        <Alert color="red" role="alert">
          {errorText(reindex.error, 'Ошибка запроса')}
        </Alert>
      )}
      {reindexDone && (
        <Alert color="green" role="status">
          Готово.
        </Alert>
      )}

      <Title order={5}>Документы глобальной базы</Title>
      {documents.isPending && <Loader size="sm" />}
      {documents.isError && (
        <Alert color="red" role="alert">
          {errorText(documents.error, 'Ошибка запроса')}
        </Alert>
      )}
      {documents.data && documents.data.length === 0 && (
        <Text c="dimmed">Документов пока нет.</Text>
      )}
      {documents.data?.map((document) => (
        <Group key={document.id} justify="space-between" wrap="nowrap">
          <Text size="sm" style={{ flex: 1 }}>
            {document.title} — {Math.round((document.size_bytes ?? 0) / 1024)} КБ,{' '}
            {document.chunk_count ?? 0} чанков
          </Text>
          <Button
            size="xs"
            color="red"
            variant="outline"
            loading={remove.isPending && remove.variables === document.id}
            onClick={() => remove.mutate(document.id as string)}
          >
            Удалить
          </Button>
        </Group>
      ))}
      {remove.isError && (
        <Alert color="red" role="alert">
          {errorText(remove.error, 'Ошибка запроса')}
        </Alert>
      )}
    </Stack>
  )
}

// ---------------------------------------------------------------------- задачи

function TasksTab() {
  const tasks = useAdminTasks()
  const cancel = useAdminCancelTask()

  if (tasks.isPending) return <Loader size="sm" />
  if (tasks.isError) {
    return (
      <Alert color="red" role="alert">
        {errorText(tasks.error, 'Не удалось загрузить задачи')}
      </Alert>
    )
  }
  const items = tasks.data ?? []
  if (items.length === 0) {
    return (
      <Text c="dimmed" role="status">
        Задач нет.
      </Text>
    )
  }

  return (
    <Stack gap="xs">
      {items.map((task) => (
        <Paper key={task.id} withBorder p="sm">
          <TaskPanel
            task={task}
            onCancel={(item) => cancel.mutate(item.id)}
            cancelPending={cancel.isPending}
          />
        </Paper>
      ))}
    </Stack>
  )
}

// --------------------------------------------------------------------- сессии

function SessionsTab() {
  const sessions = useSessionsTable()

  if (sessions.isPending) return <Loader size="sm" />
  if (sessions.isError) {
    return (
      <Alert color="red" role="alert">
        {errorText(sessions.error, 'Ошибка запроса')}
      </Alert>
    )
  }

  return (
    <Table>
      <Table.Thead>
        <Table.Tr>
          <Table.Th>id</Table.Th>
          <Table.Th>пользователь</Table.Th>
          <Table.Th>название</Table.Th>
          <Table.Th>статус</Table.Th>
          <Table.Th>действие</Table.Th>
          <Table.Th>активность</Table.Th>
        </Table.Tr>
      </Table.Thead>
      <Table.Tbody>
        {sessions.data.map((session) => (
          <Table.Tr key={session.id}>
            <Table.Td>{(session.id ?? '').slice(0, 8)}</Table.Td>
            <Table.Td>{(session.user_id ?? '').slice(0, 8)}</Table.Td>
            <Table.Td>{session.title ?? ''}</Table.Td>
            <Table.Td>{session.status ?? ''}</Table.Td>
            <Table.Td>{session.last_action_label ?? ''}</Table.Td>
            <Table.Td>{shortWhen(session.last_activity_at)}</Table.Td>
          </Table.Tr>
        ))}
      </Table.Tbody>
    </Table>
  )
}

// ------------------------------------------------------------------------ аудит

function AuditTab() {
  const audit = useAudit()
  const [sortDesc, setSortDesc] = useState(true)
  const [page, setPage] = useState(1)

  const rows = useMemo(() => {
    const items = audit.data ? [...audit.data] : []
    items.sort((a, b) =>
      sortDesc
        ? (b.created_at ?? '').localeCompare(a.created_at ?? '')
        : (a.created_at ?? '').localeCompare(b.created_at ?? ''),
    )
    return items
  }, [audit.data, sortDesc])

  const pages = Math.max(1, Math.ceil(rows.length / AUDIT_PAGE_SIZE))
  const visible = rows.slice((page - 1) * AUDIT_PAGE_SIZE, page * AUDIT_PAGE_SIZE)

  if (audit.isPending) return <Loader size="sm" />
  if (audit.isError) {
    return (
      <Alert color="red" role="alert">
        {errorText(audit.error, 'Ошибка запроса')}
      </Alert>
    )
  }

  return (
    <Stack gap="sm">
      <Button
        size="xs"
        variant="outline"
        onClick={() => {
          setSortDesc((value) => !value)
          setPage(1)
        }}
      >
        Время: {sortDesc ? 'сначала новые ↓' : 'сначала старые ↑'}
      </Button>
      <Table>
        <Table.Thead>
          <Table.Tr>
            <Table.Th>время</Table.Th>
            <Table.Th>кто</Table.Th>
            <Table.Th>действие</Table.Th>
            <Table.Th>цель</Table.Th>
            <Table.Th>ok</Table.Th>
            <Table.Th>ip</Table.Th>
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {visible.map((entry: AuditLogEntry) => (
            <Table.Tr key={entry.id}>
              <Table.Td>{(entry.created_at ?? '').slice(0, 19)}</Table.Td>
              <Table.Td>{entry.actor_username ?? '—'}</Table.Td>
              <Table.Td>{entry.action}</Table.Td>
              <Table.Td>{entry.target_type ?? ''}</Table.Td>
              <Table.Td>{entry.ok ? '✓' : '✗'}</Table.Td>
              <Table.Td>{entry.ip ?? ''}</Table.Td>
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
      {pages > 1 && (
        <Pagination value={page} onChange={setPage} total={pages} size="sm" />
      )}
    </Stack>
  )
}

// ------------------------------------------------------------------------ page

export function AdminPage() {
  const role = useAuth((state) => state.user?.role)

  if (role !== 'admin') {
    return (
      <Alert color="red" role="alert">
        Раздел доступен только администратору.
      </Alert>
    )
  }

  return (
    <Stack gap="md">
      <Title order={3}>Администрирование</Title>
      <Tabs defaultValue="users">
        <Tabs.List>
          <Tabs.Tab value="users">Пользователи</Tabs.Tab>
          <Tabs.Tab value="base">Глобальная база</Tabs.Tab>
          <Tabs.Tab value="tasks">Задачи</Tabs.Tab>
          <Tabs.Tab value="sessions">Сессии</Tabs.Tab>
          <Tabs.Tab value="audit">Аудит</Tabs.Tab>
        </Tabs.List>

        <Tabs.Panel value="users" pt="sm">
          <UsersTab />
        </Tabs.Panel>
        <Tabs.Panel value="base" pt="sm">
          <GlobalBaseTab />
        </Tabs.Panel>
        <Tabs.Panel value="tasks" pt="sm">
          <TasksTab />
        </Tabs.Panel>
        <Tabs.Panel value="sessions" pt="sm">
          <SessionsTab />
        </Tabs.Panel>
        <Tabs.Panel value="audit" pt="sm">
          <AuditTab />
        </Tabs.Panel>
      </Tabs>
    </Stack>
  )
}
