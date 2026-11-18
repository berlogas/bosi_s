/**
 * Страница «Пользователи» админки.
 * Таблица с сортировкой, пагинацией, фильтрами, созданием/удалением.
 */

import React, { useState } from 'react'
import { Stack, Title, Text, Group, TextInput, Select, Button, Alert, Modal } from '@mantine/core'
import { useForm } from '@mantine/form'
import type { FormErrors, UseFormReturnType } from '@mantine/form'
import { z } from 'zod'
import { notifications } from '@mantine/notifications'
import { useUsersPage } from './hooks/useUsersPage'
import { SimpleTable, DangerZone } from '../components'
import type { SimpleColumn } from '../components/SimpleTable'
import { EmptyState } from '../../../components/EmptyState'
import { roleOptions } from '../../../lib/roles'
import { useAuth } from '../../auth/authStore'
import { IconUsers } from '@tabler/icons-react'

function errorText(cause: unknown, fallback: string): string {
  return cause instanceof Error ? cause.message : fallback
}

// --- CreateUser form с @mantine/form + zod (Волна 6, п.5: формы) ---
type CreateUserFormValues = {
  username: string
  password: string
  fullName?: string
  role: string
}

const createUserSchema = z.object({
  username: z.string().min(2, 'Логин должен быть минимум 2 символа'),
  password: z.string().min(8, 'Пароль должен быть минимум 8 символов'),
  fullName: z.string().optional(),
  role: z.string().min(1, 'Выберите роль'),
})

interface CreateUserState {
  isPending: boolean
  error: unknown
}

/** Форма создания пользователя с zod-валидацией. */
type CreateUserForm = UseFormReturnType<
  CreateUserFormValues,
  CreateUserFormValues,
  (values: CreateUserFormValues) => FormErrors
>

function CreateUserForm({ handleCreate, createState }: {
  handleCreate: (fields: { username: string; password: string; role: string; full_name?: string }) => Promise<unknown>
  createState: CreateUserState
}) {
  const [createOpen, setCreateOpen] = useState(false)

  const form = useForm<CreateUserFormValues, CreateUserFormValues, FormErrors>({
    initialValues: { username: '', password: '', fullName: '', role: 'researcher' },
    validate: (values): FormErrors => {
      const parsed = createUserSchema.safeParse(values)
      if (!parsed.success) {
        const errors: FormErrors = {}
        for (const [key, err] of Object.entries(parsed.error.flatten().fieldErrors)) {
          errors[key] = err[0] as string
        }
        return errors
      }
      return {}
    },
  })

  const handleSubmit = async (values: CreateUserFormValues) => {
    try {
      await handleCreate({
        username: values.username.trim(),
        password: values.password,
        role: values.role,
        full_name: values.fullName?.trim() || undefined,
      })
    } catch {
      // Ошибка — рядом с полями (createState.error); окно остаётся открытым,
      // чтобы админ поправил данные и повторил.
      return
    }
    notifications.show({ title: 'Пользователь создан.', message: '', color: 'green' })
    setCreateOpen(false)
    form.reset()
  }

  const handleOpen = () => {
    setCreateOpen(true)
  }

  return (
    <Stack gap="sm">
      <Button
        onClick={handleOpen}
        variant="outline"
      >
        Создать пользователя
      </Button>
      {createOpen && (
        <Modal opened={createOpen} onClose={() => setCreateOpen(false)} title="Создать пользователя" size="sm">
          <ModalForm
            form={form}
            handleSubmit={handleSubmit}
            createState={createState}
          />
        </Modal>
      )}
    </Stack>
  )
}

function ModalForm({ form, handleSubmit, createState }: {
  form: CreateUserForm
  handleSubmit: (values: CreateUserFormValues) => void | Promise<void>
  createState: CreateUserState
}) {
  return (
    <form onSubmit={form.onSubmit(handleSubmit)}>
      <Stack gap="sm">
        {createState.error && (
          <Alert color="red" role="alert">
            {errorText(createState.error, 'Не удалось создать пользователя')}
          </Alert>
        )}
        <Group align="flex-end" wrap="nowrap" gap="xs">
          <TextInput
            label="Логин"
            aria-label="Логин"
            {...form.getInputProps('username')}
            required
            autoComplete="off"
          />
          <TextInput
            label="Пароль"
            type="password"
            aria-label="Пароль"
            {...form.getInputProps('password')}
            required
            autoComplete="new-password"
          />
          <TextInput
            label="ФИО"
            aria-label="ФИО"
            {...form.getInputProps('fullName')}
          />
          <Select
            label="Роль"
            aria-label="Роль"
            data={roleOptions(['researcher', 'admin'])}
            {...form.getInputProps('role')}
            allowDeselect={false}
            w={150}
          />
          {/* form.isValid в Mantine v9 — функция: без скобок кнопка
              никогда не блокировалась. */}
          <Button type="submit" disabled={!form.isValid() || createState.isPending}>Создать</Button>
        </Group>
      </Stack>
    </form>
  )
}

/** Строка таблицы пользователей: правка полей и удаление. */
interface UserRowData {
  id: string
  username: string
  full_name?: string | null
  role: string
  is_active: boolean
}

interface UserFields {
  role?: string
  username?: string
  full_name?: string
  password?: string
  is_active?: boolean
}

// --- UserRow с редактированием и удалением (вынесен наружу) ---
function UserRow({ user, handleUpdate, handleDelete, currentUserId }: {
  user: UserRowData
  handleUpdate: (id: string, fields: UserFields) => void
  handleDelete: (id: string) => Promise<unknown>
  currentUserId: string
}) {
  const [editUsername, setEditUsername] = React.useState(user.username)
  // Ошибка удаления (409 «нельзя удалить себя») показывается в окне
  // подтверждения — раньше она просто терялась.
  const [deleteError, setDeleteError] = React.useState<string | null>(null)
  const [editFullName, setEditFullName] = React.useState(user.full_name || '')
  const [editRole, setEditRole] = React.useState(user.role)
  const [editPassword, setEditPassword] = React.useState('')
  const [editIsActive, setEditIsActive] = React.useState(user.is_active)
  const [dirty, setDirty] = React.useState(false)
  const [usernameError, setUsernameError] = React.useState<string | null>(null)

  const validateUsername = (value: string) => {
    if (!value || value.trim().length < 2) {
      setUsernameError('Логин должен быть минимум 2 символа')
      return false
    }
    setUsernameError(null)
    return true
  }

  const handleSave = () => {
    if (!validateUsername(editUsername)) return
    const fields: UserFields = { role: editRole }
    if (editUsername !== user.username) fields.username = editUsername
    if (editFullName !== user.full_name) fields.full_name = editFullName
    if (editPassword) fields.password = editPassword
    if (editIsActive !== user.is_active) fields.is_active = editIsActive
    handleUpdate(user.id, fields)
    notifications.show({ title: `Сохранено: ${user.username}`, message: '', color: 'blue' })
    setDirty(false)
    setEditPassword('')
  }

  const handleChange = () => {
    setDirty(true)
    validateUsername(editUsername)
  }

  return [
    <td
      key="login"
      style={{
        whiteSpace: 'nowrap',
        textAlign: 'right',
        padding: '2px 4px',
        width: 160,
      }}
    >
      <TextInput
        size="xs"
        value={editUsername}
        onChange={(e) => { setEditUsername(e.target.value); handleChange() }}
        style={{ width: 150 }}
        aria-label={`Логин: ${user.username}`}
      />
    </td>,
    <td
      key="fullname"
      style={{
        whiteSpace: 'nowrap',
        textAlign: 'right',
        padding: '2px 4px',
        width: 200,
      }}
    >
      <TextInput
        size="xs"
        value={editFullName}
        onChange={(e) => { setEditFullName(e.target.value); handleChange() }}
        style={{ width: 190 }}
        aria-label={`ФИО: ${user.username}`}
      />
    </td>,
    <td
      key="role"
      style={{
        whiteSpace: 'nowrap',
        textAlign: 'right',
        padding: '2px 4px',
        width: 150,
      }}
    >
      <Select
        size="xs"
        data={roleOptions(['researcher', 'admin'])}
        value={editRole}
        onChange={(v) => {
          if (v) setEditRole(v)
          handleChange()
        }}
        allowDeselect={false}
        style={{ width: 140 }}
        aria-label={`Роль: ${user.username}`}
      />
    </td>,
    <td
      key="password"
      style={{
        whiteSpace: 'nowrap',
        textAlign: 'right',
        padding: '2px 4px',
        width: 150,
      }}
    >
      <TextInput
        size="xs"
        type="password"
        placeholder="Новый пароль"
        value={editPassword}
        onChange={(e) => { setEditPassword(e.target.value); handleChange() }}
        style={{ width: 140 }}
        aria-label={`Новый пароль: ${user.username}`}
      />
    </td>,
    <td
      key="active"
      style={{
        whiteSpace: 'nowrap',
        textAlign: 'right',
        padding: '2px 4px',
        width: 40,
      }}
    >
      <span style={{ textAlign: 'center', display: 'inline-block' }}>
        <input
          type="checkbox"
          checked={editIsActive}
          onChange={(e) => {
            setEditIsActive(e.target.checked)
            handleChange()
            handleUpdate(user.id, { role: editRole, is_active: e.target.checked })
          }}
          aria-label={`Активен: ${user.username}`}
        />
      </span>
    </td>,
    <td
      key="actions"
      style={{
        whiteSpace: 'nowrap',
        textAlign: 'right',
        padding: '2px 4px',
        width: 220,
      }}
    >
      <Group gap="xs" wrap="nowrap">
        <Button size="xs" variant="default" disabled={!dirty || !!usernameError} onClick={handleSave}>Сохранить</Button>
        {usernameError && <Text size="xs" c="red">{usernameError}</Text>}
        <DangerZone
          confirmText={user.username}
          label="Удалить"
          error={deleteError}
          onConfirm={async () => {
            setDeleteError(null)
            try {
              await handleDelete(user.id)
            } catch (cause) {
              setDeleteError(errorText(cause, 'Не удалось удалить пользователя'))
              throw cause
            }
          }}
          warning={
            'Удаление необратимо. Вместе с учётной записью каскадно удалятся её сессии, '
            + 'сообщения, документы и проекты. Восстановление возможно только из резервной копии. '
            + 'Если достаточно закрыть доступ — снимите галочку активности вместо удаления.'
          }
          disabled={user.id === currentUserId}
        />
      </Group>
    </td>,
  ]
}

export default function UsersPage() {
  const { user: currentUser } = useAuth()
  const currentUserId = currentUser?.id

  const {
    data,
    isLoading,
    isError,
    error,
    pagination,
    sorting,
    filters,
    setPagination,
    setSorting,
    handleCreate,
    handleUpdate,
    handleDelete,
    createUser,
  } = useUsersPage()

  // Направление сортировки по ФИО (только клиентское состояние)
  const [fullNameSortDir, setFullNameSortDir] = React.useState<'asc' | 'desc' | null>(
    null
  )

  const handleSortByFullName = React.useCallback(() => {
    setFullNameSortDir((dir) => (dir === 'asc' ? 'desc' : 'asc'))
  }, [])

  // Сортировка по ФИО на клиенте
  const sortedUsers = React.useMemo(() => {
    if (!fullNameSortDir) return data
    const dir = fullNameSortDir === 'desc' ? -1 : 1
    return [...data].sort((a, b) => {
      const av = (a.full_name || '') as string
      const bv = (b.full_name || '') as string
      if (av < bv) return -dir
      if (av > bv) return dir
      return 0
    })
  }, [data, fullNameSortDir])

  // Все хуки и useMemo ДО early return
  const customColumns = React.useMemo<SimpleColumn<UserRowData>[]>(() => [], [])

  const actionsHeaders = React.useMemo(() => [
    { label: 'Логин', width: 160 },
    {
      label: 'ФИО',
      width: 200,
      onSort: handleSortByFullName,
      sortDir: fullNameSortDir,
    },
    { label: 'Роль', width: 150 },
    { label: 'Пароль', width: 150 },
    { label: 'Активен', width: 40 },
    { label: 'Действия', width: 220 },
  ], [fullNameSortDir, handleSortByFullName])

  if (isLoading) return <Text c="dimmed">Загрузка...</Text>
  if (isError) return <Alert color="red">{errorText(error, 'Ошибка загрузки')}</Alert>

  return (
    <Stack gap="md">
      <Title order={3}>Пользователи</Title>
      <CreateUserForm
        handleCreate={handleCreate}
        createState={{ isPending: createUser.isPending, error: createUser.error }}
      />
      {data.length === 0 && !isLoading ? (
        <EmptyState
          title="Пользователей нет"
          description="Создайте первую учётную запись исследователя или администратора."
          action={<Button onClick={() => {}}>Создать пользователя</Button>}
          icon={<IconUsers size={32} />}
        />
      ) : (
        <SimpleTable
          columns={customColumns}
          data={sortedUsers as UserRowData[]}
          pagination={pagination}
          onPaginationChange={setPagination}
          sorting={sorting}
          onSortingChange={setSorting}
          filters={filters}
          onFiltersChange={() => {}}
          rowActions={({ original: row }) => <UserRow user={row} handleUpdate={handleUpdate} handleDelete={handleDelete} currentUserId={currentUserId} />}
          rowActionsHeaders={actionsHeaders}
          isLoading={isLoading}
          emptyMessage="Пользователей нет."
        />
      )}
    </Stack>
  )
}