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
  Checkbox,
  Divider,
  FileInput,
  Group,
  Loader,
  Modal,
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

import type { AuditLogEntry, SessionOut, User } from '../../api/types'
import type { ResetScope } from '../../api/client'
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
  useBackups,
  useBulkIndex,
  useCreateBackup,
  useCreateUser,
  useDeleteBackup,
  useDeleteUser,
  useResetPreview,
  useResetState,
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

/**
 * Кнопка удаления. Показываем её только там, где действие имеет смысл:
 * удалить себя нельзя (backend отдаёт 409), поэтому для текущего
 * администратора кнопка задизейблена с подсказкой.
 *
 * Подтверждение — отдельная модалка с перечислением того, что исчезнет
 * каскадом: удаление необратимо, отмены нет.
 */
function DeleteUserButton({ user }: { user: User }) {
  const remove = useDeleteUser()
  const currentUserId = useAuth((state) => state.user?.id)
  const [opened, setOpened] = useState(false)
  const isSelf = currentUserId === user.id

  return (
    <>
      <Button
        size="xs"
        color="red"
        variant="light"
        disabled={isSelf}
        title={isSelf ? 'Нельзя удалить самого себя' : undefined}
        aria-label={`Удалить: ${user.username}`}
        onClick={() => setOpened(true)}
      >
        Удалить
      </Button>
      <Modal
        opened={opened}
        onClose={() => setOpened(false)}
        title="Подтвердите удаление"
        centered
      >
        <Stack gap="sm">
          <Text size="sm">
            Удалить пользователя <b>{user.username}</b>?
          </Text>
          <Alert color="red" role="alert">
            Действие необратимо. Вместе с учётной записью каскадно удалятся его
            сессии, сообщения, документы и проекты. Восстановление возможно
            только из резервной копии. Если достаточно закрыть доступ —
            используйте снятие галочки активности.
          </Alert>
          {remove.isError && (
            <Alert color="red" role="alert">
              {errorText(remove.error, 'Ошибка запроса')}
            </Alert>
          )}
          <Group justify="flex-end">
            <Button
              variant="default"
              onClick={() => setOpened(false)}
              disabled={remove.isPending}
            >
              Отмена
            </Button>
            <Button
              color="red"
              loading={remove.isPending}
              onClick={() =>
                remove.mutate(user.id, { onSuccess: () => setOpened(false) })
              }
            >
              Удалить безвозвратно
            </Button>
          </Group>
        </Stack>
      </Modal>
    </>
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
            variant="default"
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
          <DeleteUserButton user={user} />
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
        <>
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
        <Text size="xs" c="dimmed">
          «Удалить» стирает учётную запись вместе с её сессиями и документами, и
          отменить это нельзя. Если достаточно закрыть доступ — снимите галочку
          активности вместо удаления.
        </Text>
        </>
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

type AdminSessionRow = SessionOut

function SessionsTab() {
  const users = useAdminUsers()
  const sessions = useSessionsTable()

  // «сессии сгруппированы по пользователям» — пользователь решает, чью
  // сессию смотреть; сам список остаётся прежним (все сессии админу видны)
  const grouped = useMemo(() => {
    const byUser = new Map<string, AdminSessionRow[]>()
    for (const session of sessions.data ?? []) {
      const bucket = byUser.get(session.user_id ?? '') ?? []
      bucket.push(session)
      byUser.set(session.user_id ?? '', bucket)
    }
    const names = new Map((users.data ?? []).map((u) => [u.id, u.username]))
    return [...byUser.entries()]
      .map(([userId, rows]) => ({
        userId,
        label: names.get(userId) ?? userId.slice(0, 8),
        rows: rows.sort((a, b) =>
          (b.last_activity_at ?? '').localeCompare(a.last_activity_at ?? ''),
        ),
      }))
      .sort((a, b) => a.label.localeCompare(b.label))
  }, [sessions.data, users.data])

  if (sessions.isPending || users.isPending) return <Loader size="sm" />
  if (sessions.isError) {
    return (
      <Alert color="red" role="alert">
        {errorText(sessions.error, 'Ошибка запроса')}
      </Alert>
    )
  }
  if (grouped.length === 0) {
    return <Text c="dimmed">Сессий нет.</Text>
  }

  return (
    <Accordion defaultValue={`user:${grouped[0]?.userId}`}>
      {grouped.map((group) => (
        <Accordion.Item key={group.userId} value={`user:${group.userId}`} role="region" aria-label={group.label}>
          <Accordion.Control aria-label={`${group.label}, ${group.rows.length} ${pluralizeSession(group.rows.length)}`}>
            <Group justify="space-between" wrap="nowrap">
              <Text fw={600}>{group.label}</Text>
              <Text c="dimmed" size="sm">
                {group.rows.length}{' '}
                {pluralizeSession(group.rows.length)}
              </Text>
            </Group>
          </Accordion.Control>
          <Accordion.Panel>
            <Table>
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>id</Table.Th>
                  <Table.Th>название</Table.Th>
                  <Table.Th>статус</Table.Th>
                  <Table.Th>действие</Table.Th>
                  <Table.Th>активность</Table.Th>
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {group.rows.map((session) => (
                  <Table.Tr key={session.id}>
                    <Table.Td>{(session.id ?? '').slice(0, 8)}</Table.Td>
                    <Table.Td>{session.title ?? ''}</Table.Td>
                    <Table.Td>{session.status ?? ''}</Table.Td>
                    <Table.Td>{session.last_action_label ?? ''}</Table.Td>
                    <Table.Td>{shortWhen(session.last_activity_at)}</Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          </Accordion.Panel>
        </Accordion.Item>
      ))}
    </Accordion>
  )
}

function pluralizeSession(count: number): string {
  const n = count % 10
  const n100 = count % 100
  if (n === 1 && n100 !== 11) return 'сессия'
  if (n >= 2 && n <= 4 && (n100 < 12 || n100 > 14)) return 'сессии'
  return 'сессий'
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

// ----------------------------------------------------------------------- сброс
const RESET_SCOPES = [
  {
    value: 'data',
    label: 'Данные (сессии, документы, проекты, переписка)',
    hint: 'Пользователи и аудит остаются. Документы нужно загрузить заново.',
  },
  {
    value: 'users',
    label: 'Данные и входы (+ refresh-токены)',
    hint: 'Все пользователи останутся, но им придётся войти заново.',
  },
  {
    value: 'all',
    label: 'Всё (полностью пустая платформа)',
    hint: 'Удаляются и учётные записи. После этого нужен make create-admin.',
  },
] as const

/** Человеческий размер: план сброса приходит в байтах. */
function humanBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} Б`
  const units = ['КБ', 'МБ', 'ГБ']
  let value = bytes / 1024
  let unit = 0
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024
    unit += 1
  }
  return `${value.toFixed(1)} ${units[unit]}`
}

function ResetSection() {
  const [scope, setScope] = useState<ResetScope>('data')
  const [includeModels, setIncludeModels] = useState(false)
  const [phrase, setPhrase] = useState('')
  const [opened, setOpened] = useState(false)
  const plan = useResetPreview(scope, includeModels)
  const reset = useResetState()

  const current = RESET_SCOPES.find((item) => item.value === scope)
  const expected = plan.data?.confirmation ?? ''
  const canReset = Boolean(expected) && phrase.trim() === expected && !reset.isPending

  function openDialog() {
    setPhrase('')
    reset.reset()
    setOpened(true)
  }

  return (
    <Stack gap="sm">
      <Alert color="yellow" title="Сброс необратим">
        Удалённые сессии, документы и переписка восстановить нельзя — только из
        бэкапа (<code>make backup</code>). Сначала посмотрите план.
      </Alert>

      <Select
        label="Что сбросить"
        data={RESET_SCOPES.map((item) => ({ value: item.value, label: item.label }))}
        value={scope}
        onChange={(value) => value && setScope(value as ResetScope)}
        allowDeselect={false}
        w={520}
      />
      {current && (
        <Text size="sm" c="dimmed">
          {current.hint}
        </Text>
      )}

      <Checkbox
        label="Также удалить кэш моделей (HF/Torch)"
        description='Обычно НЕ нужно: без него после сброса платформа не сможет считать эмбеддинги в оффлайне, пока модель не будет скачана заново.'
        checked={includeModels}
        onChange={(event) => setIncludeModels(event.currentTarget.checked)}
      />

      {plan.isPending && <Loader size="sm" />}
      {plan.isError && (
        <Alert color="red" role="alert">
          {errorText(plan.error, 'Ошибка запроса')}
        </Alert>
      )}
      {plan.data && !plan.data.allowed && (
        <Alert color="red" role="alert">
          Сброс запрещён: {plan.data.blocked_reason}
        </Alert>
      )}

      {plan.data && plan.data.allowed && (
        <Paper withBorder p="sm">
          <Stack gap="xs">
            <Text fw={600}>Будет удалено</Text>
            <Table>
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>Таблица</Table.Th>
                  <Table.Th>Строк</Table.Th>
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {Object.entries(plan.data.tables).map(([name, rows]) => (
                  <Table.Tr key={name}>
                    <Table.Td>{name}</Table.Td>
                    <Table.Td>{rows}</Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
            {plan.data.paths.map((item) => (
              <Text key={item.path} size="sm">
                <code>{item.path}</code> — {item.files} файлов,{' '}
                {humanBytes(item.bytes)}
              </Text>
            ))}
            <Text size="sm" fw={600}>
              Итого: {plan.data.rows} строк, {plan.data.files} файлов,{' '}
              {humanBytes(plan.data.total_bytes)}
            </Text>
            {plan.data.kept_paths.length > 0 && (
              <Text size="sm" c="dimmed">
                Не трогаем: {plan.data.kept_paths.join(', ')} (кэш моделей — нужен
                для эмбеддингов).
              </Text>
            )}
          </Stack>
        </Paper>
      )}

      <Group>
        <Button color="red" onClick={openDialog} disabled={!plan.data?.allowed}>
          Сбросить…
        </Button>
      </Group>

      <Modal
        opened={opened}
        onClose={() => setOpened(false)}
        title="Подтвердите сброс"
        centered
      >
        <Stack gap="sm">
          <Text size="sm">
            Будет выполнен сброс <b>{scope}</b>. Действие необратимо.
          </Text>
          <Text size="sm">
            Для подтверждения введите: <b>{expected}</b>
          </Text>
          <TextInput
            label="Фраза подтверждения"
            value={phrase}
            onChange={(event) => setPhrase(event.currentTarget.value)}
            data-testid="reset-confirm-input"
          />
          {reset.isError && (
            <Alert color="red" role="alert">
              {errorText(reset.error, 'Ошибка запроса')}
            </Alert>
          )}
          <Group justify="flex-end">
            <Button variant="default" onClick={() => setOpened(false)}>
              Отмена
            </Button>
            <Button
              color="red"
              disabled={!canReset}
              loading={reset.isPending}
              onClick={() => {
                if (!expected) return
                reset.mutate(
                  { scope, confirm: expected, include_models: includeModels },
                  { onSuccess: () => setOpened(false) },
                )
              }}
            >
              Выполнить сброс
            </Button>
          </Group>
        </Stack>
      </Modal>
    </Stack>
  )
}

// ------------------------------------------------------- резервные копии
function BackupsSection() {
  const backups = useBackups()
  const create = useCreateBackup()
  const remove = useDeleteBackup()

  const [opened, setOpened] = useState(false)

  const plan = backups.data?.plan
  const items = backups.data?.backups ?? []

  return (
    <Stack gap="sm">
      <Alert color="blue" title="Копия снимается на сервере">
        Архив содержит базу данных (согласованный снимок), файлы сессий и
        документов и манифест с ревизией схемы. Копии складываются в каталог{' '}
        <code>{plan?.backup_dir ?? '—'}</code> — он намеренно вынесен за пределы
        данных, иначе копия попадала бы сама в себя.
      </Alert>

      {plan?.db_exists === false && (
        <Alert color="red" role="alert">
          База данных не найдена — копия получится без данных. Проверьте, что
          платформа видит свой каталог данных.
        </Alert>
      )}

      {plan && (
        <Paper withBorder p="sm">
          <Text size="sm">
            Данные: <code>{plan.data_dir}</code> · файлов: {plan.files} ·{' '}
            {plan.source_human}
          </Text>
          <Text size="sm">
            Копия займёт около {plan.estimated_human}
            {plan.free_human ? `, свободно на диске ${plan.free_human}` : ''}
          </Text>
          <Text size="sm" c="dimmed">
            Хранится копий: {plan.keep === 0 ? 'без ограничения' : `последние ${plan.keep}`}{' '}
            (сейчас {plan.existing}); при создании новой более старые удаляются
            автоматически.
          </Text>
        </Paper>
      )}

      <Group>
        <Button
          onClick={() => {
            create.reset()
            setOpened(true)
          }}
          disabled={backups.isPending || plan?.db_exists === false}
        >
          Создать копию…
        </Button>
        <Button
          variant="default"
          onClick={() => void backups.refetch()}
          loading={backups.isFetching}
        >
          Обновить
        </Button>
      </Group>

      {backups.isPending && <Loader size="sm" />}
      {backups.isError && (
        <Alert color="red" role="alert">
          {errorText(backups.error, 'Ошибка запроса')}
        </Alert>
      )}

      {items.length > 0 && (
        <Table>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Копия</Table.Th>
              <Table.Th>Размер</Table.Th>
              <Table.Th>Создана</Table.Th>
              <Table.Th />
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {items.map((item) => (
              <Table.Tr key={item.name}>
                <Table.Td>
                  <Text size="sm">{item.name}</Text>
                  <Text size="xs" c="dimmed">
                    {item.has_sha256 ? 'с контрольной суммой' : 'без суммы'}
                    {item.has_manifest ? ' · с манифестом' : ''}
                  </Text>
                </Table.Td>
                <Table.Td>{item.human_size}</Table.Td>
                <Table.Td>{(item.created_at ?? '').replace('T', ' ').slice(0, 19)}</Table.Td>
                <Table.Td>
                  <Button
                    size="xs"
                    color="red"
                    variant="outline"
                    loading={
                      remove.isPending && remove.variables === item.name
                    }
                    onClick={() => remove.mutate(item.name)}
                  >
                    Удалить
                  </Button>
                </Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      )}
      {items.length === 0 && backups.isSuccess && (
        <Text size="sm" c="dimmed" role="status">
          Копий пока нет.
        </Text>
      )}

      {remove.isError && (
        <Alert color="red" role="alert">
          {errorText(remove.error, 'Не удалось удалить копию')}
        </Alert>
      )}

      <Alert color="yellow" title="Восстановление — только скриптом">
        Восстановление требует остановки платформы, поэтому из браузера его
        делать нельзя. После копии выполните в корне проекта:
        <code> ./scripts/restore.sh путь/к/архиву.tar.gz</code>
      </Alert>

      <Modal
        opened={opened}
        onClose={() => setOpened(false)}
        title="Создать резервную копию"
        centered
      >
        <Stack gap="sm">
          <Text size="sm">
            Архив займёт около {plan?.estimated_human ?? '?'} и ложится в{' '}
            <code>{plan?.backup_dir ?? '—'}</code>.
          </Text>
          {plan?.warning && (
            <Text size="sm" c="dimmed">
              {plan.warning}
            </Text>
          )}
          {create.isError && (
            <Alert color="red" role="alert">
              {errorText(create.error, 'Не удалось создать копию')}
            </Alert>
          )}
          <Group justify="flex-end">
            <Button variant="default" onClick={() => setOpened(false)}>
              Отмена
            </Button>
            <Button
              loading={create.isPending}
              onClick={() => {
                create.mutate(undefined, { onSuccess: () => setOpened(false) })
              }}
            >
              Создать
            </Button>
          </Group>
        </Stack>
      </Modal>
    </Stack>
  )
}

// -------------------------------------------------------------- обслуживание
function MaintenanceTab() {
  return (
    <Stack gap="lg">
      <BackupsSection />
      <Divider label="Сброс состояния" labelPosition="center" />
      <ResetSection />
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
          <Tabs.Tab value="service">Обслуживание</Tabs.Tab>
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
        <Tabs.Panel value="service" pt="sm">
          <MaintenanceTab />
        </Tabs.Panel>
      </Tabs>
    </Stack>
  )
}
