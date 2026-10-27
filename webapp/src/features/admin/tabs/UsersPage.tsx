/**
 * Страница «Пользователи» админки.
 * Таблица с сортировкой, пагинацией, фильтрами, созданием/удалением.
 */

import React, { useState } from 'react'
import { Stack, Title, Text, Group, TextInput, Select, Button, Alert, Badge, Modal } from '@mantine/core'
import { useForm } from '@mantine/form'
import { z } from 'zod'
import { notifications } from '@mantine/notifications'
import { useUsersPage } from './hooks/useUsersPage'
import { SimpleTable, DangerZone } from '../components'
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

function CreateUserForm({ handleCreate }: { handleCreate: (fields: { username: string; password: string; role: string; full_name?: string }) => void }) {
  const [createOpen, setCreateOpen] = useState(false)

  const form = useForm<CreateUserFormValues>({
    initialValues: { username: '', password: '', fullName: '', role: 'researcher' },
    validate: (values) => {
      const parsed = createUserSchema.safeParse(values)
      if (!parsed.success) {
        const errors: Partial<CreateUserFormValues> = {}
        for (const [key, err] of Object.entries(parsed.error.flatten().fieldErrors)) {
          errors[key as keyof CreateUserFormValues] = err[0] as string
        }
        return errors
      }
      return {}
    },
  }) as any

  const handleSubmit = (values: CreateUserFormValues) => {
    handleCreate({
      username: values.username.trim(),
      password: values.password,
      role: values.role,
      full_name: values.fullName?.trim() || undefined,
    })
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
            onClose={() => setCreateOpen(false)}
          />
        </Modal>
      )}
    </Stack>
  )
}

function ModalForm({ form, handleSubmit, onClose }: { form: ReturnType<typeof useForm<CreateUserFormValues>>; handleSubmit: (values: CreateUserFormValues) => void; onClose: () => void }) {
  return (
    <form onSubmit={form.onSubmit(handleSubmit)}>
      <Stack gap="sm">
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
          <Button type="submit" disabled={!form.isValid}>Создать</Button>
        </Group>
      </Stack>
    </form>
  )
}

// --- UserRow с редактированием и удалением (вынесен наружу) ---
function UserRow({ user, handleUpdate, handleDelete, currentUserId }: { user: any; handleUpdate: (id: string, fields: any) => void; handleDelete: (id: string) => void; currentUserId: string }) {
  const [editUsername, setEditUsername] = React.useState(user.username)
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
    const fields: any = { role: editRole }
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

  return (
    <Group gap="xs" wrap="nowrap">
      <TextInput
        size="xs"
        value={editUsername}
        onChange={(e) => { setEditUsername(e.target.value); handleChange() }}
        w={160}
        aria-label={`Логин: ${user.username}`}
      />
      <TextInput
        size="xs"
        value={editFullName}
        onChange={(e) => { setEditFullName(e.target.value); handleChange() }}
        w={200}
        aria-label={`ФИО: ${user.username}`}
      />
      <Select
        size="xs"
        data={roleOptions(['researcher', 'admin'])}
        value={editRole}
        onChange={(v) => { v && setEditRole(v); handleChange() }}
        allowDeselect={false}
        w={150}
        aria-label={`Роль: ${user.username}`}
      />
      <TextInput
        size="xs"
        type="password"
        placeholder="Новый пароль"
        value={editPassword}
        onChange={(e) => { setEditPassword(e.target.value); handleChange() }}
        aria-label={`Новый пароль: ${user.username}`}
      />
      <span style={{ textAlign: 'center', display: 'inline-block', width: 20 }}>
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
      <Button size="xs" variant="default" disabled={!dirty || !!usernameError} onClick={handleSave}>Сохранить</Button>
      {usernameError && <Text size="xs" c="red">{usernameError}</Text>}
      <DangerZone
        confirmText={user.username}
        label="Удалить"
        onConfirm={() => handleDelete(user.id)}
        warning={
          'Удаление необратимо. Вместе с учётной записью каскадно удалятся её сессии, '
          + 'сообщения, документы и проекты. Восстановление возможно только из резервной копии. '
          + 'Если достаточно закрыть доступ — снимите галочку активности вместо удаления.'
        }
        disabled={user.id === currentUserId}
      />
    </Group>
  )
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
  } = useUsersPage()

  // Все хуки и useMemo ДО early return
  // @ts-ignore
  const customColumns = React.useMemo(() => [
    { id: 'username', accessorKey: 'username', header: 'Логин', cell: (row: any) => row.username },
    { id: 'full_name', accessorKey: 'full_name', header: 'ФИО', cell: (row: any) => row.full_name || '—' },
    { id: 'role', accessorKey: 'role', header: 'Роль', cell: (row: any) => <Badge size="xs">{String(row.role ?? '—')}</Badge> },
    { id: 'is_active', accessorKey: 'is_active', header: 'Активен', cell: (row: any) => row.is_active ? '✓' : '✗' },
    { id: 'actions', header: '', cell: (row: any) => <UserRow user={row} handleUpdate={handleUpdate} handleDelete={handleDelete} currentUserId={currentUserId} /> },
  ], [handleUpdate, handleDelete])

  if (isLoading) return <Text c="dimmed">Загрузка...</Text>
  if (isError) return <Alert color="red">{errorText(error, 'Ошибка загрузки')}</Alert>

  return (
    <Stack gap="md">
      <Title order={3}>Пользователи</Title>
      <CreateUserForm handleCreate={handleCreate} />
      {data.length === 0 && !isLoading ? (
        <EmptyState
          title="Пользователей нет"
          description="Создайте первую учётную запись исследователя или администратора."
          action={<Button onClick={() => {}}>Создать пользователя</Button>}
          icon={<IconUsers size={32} />}
        />
      ) : (
        <SimpleTable
          columns={customColumns as any}
          data={data}
          pagination={pagination}
          onPaginationChange={setPagination}
          sorting={sorting}
          onSortingChange={setSorting}
          filters={filters}
          onFiltersChange={() => {}}
          rowActions={({ original: _ }) => null}
          isLoading={isLoading}
          emptyMessage="Пользователей нет."
        />
      )}
    </Stack>
  )
}