/**
 * Страница «Пользователи» админки.
 * Таблица с сортировкой, пагинацией, фильтрами, созданием/удалением.
 */

import React, { useState, useRef } from 'react'
import { Stack, Title, Text, Group, TextInput, Select, Button, Alert, Badge, Modal } from '@mantine/core'
import { notifications } from '@mantine/notifications'
import { useUsersPage } from './hooks/useUsersPage'
import { SimpleTable } from '../components'
import { roleOptions } from '../../../lib/roles'
import { useAuth } from '../../auth/authStore'

function errorText(cause: unknown, fallback: string): string {
  return cause instanceof Error ? cause.message : fallback
}

// --- CreateUser form (вынесен наружу) ---
function CreateUserForm({ handleCreate }: { handleCreate: (fields: { username: string; password: string; role: string; full_name?: string }) => void }) {
  const [formKey, setFormKey] = useState(0)
  const [createOpen, setCreateOpen] = useState(false)

  const handleOpen = () => {
    setFormKey((k) => k + 1)
    setCreateOpen(true)
  }

  const handleSubmit = (values: { username: string; password: string; role: string; fullName: string }) => {
    handleCreate({
      username: values.username.trim(),
      password: values.password,
      role: values.role,
      full_name: values.fullName.trim() || undefined,
    })
    notifications.show({ title: 'Пользователь создан.', color: 'green' })
    setCreateOpen(false)
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
        <CreateUserFormInner
          key={formKey}
          handleCreate={handleCreate}
          onClose={() => setCreateOpen(false)}
          onSubmit={handleSubmit}
        />
      )}
    </Stack>
  )
}

function CreateUserFormInner({ handleCreate, onClose, onSubmit }: { handleCreate: (fields: { username: string; password: string; role: string; full_name?: string }) => void; onClose: () => void; onSubmit: (values: { username: string; password: string; role: string; fullName: string }) => void }) {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [fullName, setFullName] = useState('')
  const [role, setRole] = useState('researcher')

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    onSubmit({ username, password, role, fullName })
    onClose()
  }

  return (
    <form onSubmit={handleSubmit}>
      <Stack gap="sm">
        <Group align="flex-end" wrap="nowrap" gap="xs">
          <TextInput
            label="Логин"
            aria-label="Логин"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            style={{ flex: 1 }}
            required
            autoComplete="off"
          />
          <TextInput
            label="Пароль"
            type="password"
            aria-label="Пароль"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            style={{ flex: 1 }}
            required
            autoComplete="new-password"
          />
          <TextInput
            label="ФИО"
            aria-label="ФИО"
            value={fullName}
            onChange={(e) => setFullName(e.target.value)}
            style={{ flex: 1 }}
          />
          <Select
            label="Роль"
            aria-label="Роль"
            data={roleOptions(['researcher', 'admin'])}
            value={role}
            onChange={(v) => v && setRole(v)}
            allowDeselect={false}
            w={150}
          />
          <Button type="submit" disabled={!username || password.length < 8}>Создать</Button>
        </Group>
      </Stack>
    </form>
  )
}

// --- UserRow с редактированием и удалением (вынесен наружу) ---
function UserRow({ user, handleUpdate, handleDelete, deleteMutation, currentUserId }: { user: any; handleUpdate: (id: string, fields: any) => void; handleDelete: (id: string) => void; deleteMutation: any; currentUserId: string }) {
  const [editUsername, setEditUsername] = React.useState(user.username)
  const [editFullName, setEditFullName] = React.useState(user.full_name || '')
  const [editRole, setEditRole] = React.useState(user.role)
  const [editPassword, setEditPassword] = React.useState('')
  const [editIsActive, setEditIsActive] = React.useState(user.is_active)
  const [dirty, setDirty] = React.useState(false)
  const [deleteOpen, setDeleteOpen] = React.useState(false)

  const isSelf = user.id === currentUserId

  const handleSave = () => {
    const fields: any = { role: editRole }
    if (editUsername !== user.username) fields.username = editUsername
    if (editFullName !== user.full_name) fields.full_name = editFullName
    if (editPassword) fields.password = editPassword
    if (editIsActive !== user.is_active) fields.is_active = editIsActive
    handleUpdate(user.id, fields)
    notifications.show({ title: `Сохранено: ${user.username}`, color: 'blue' })
    setDirty(false)
    setEditPassword('')
  }

  const handleChange = () => setDirty(true)

  const isDeleting = deleteMutation.isPending
  const deleteError = deleteMutation.isError
    ? (deleteMutation.error?.detail || deleteMutation.error?.message || String(deleteMutation.error))
    : ''

  React.useEffect(() => {
    if (deleteMutation.isSuccess) {
      setDeleteOpen(false)
    }
  }, [deleteMutation.isSuccess])

  const handleConfirmDelete = () => {
    handleDelete(user.id)
    // Не закрываем модалку сразу — ждём результат мутации
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
            handleUpdate(user.id, { is_active: e.target.checked })
          }}
          aria-label={`Активен: ${user.username}`}
        />
      </span>
      <Button size="xs" variant="default" disabled={!dirty} onClick={handleSave}>Сохранить</Button>
      <Button
        size="xs"
        variant="subtle"
        color="red"
        aria-label={`Удалить: ${user.username}`}
        onClick={() => setDeleteOpen(true)}
        disabled={user.id === currentUserId}
      >
        Удалить
      </Button>
      <Modal
        opened={deleteOpen}
        onClose={() => { setDeleteOpen(false); setDeleteError(''); }}
        title="Подтвердите удаление"
        centered
      >
        <Stack gap="sm">
          <Text size="sm">
            Удалить пользователя <b>{user.username}</b>?
          </Text>
          <Alert color="error" role="alert">
            Действие необратимо. Вместе с учётной записью каскадно удалятся его сессии,
            сообщения, документы и проекты. Восстановление возможно только из резервной
            копии. Если достаточно закрыть доступ — используйте снятие галочки
            активности.
          </Alert>
          {deleteError && <Alert color="error" role="alert">{deleteError}</Alert>}
          <Group justify="flex-end">
            <Button variant="default" onClick={() => setDeleteOpen(false)}>
              Отмена
            </Button>
            <Button color="red" disabled={isDeleting} onClick={handleConfirmDelete}>
              {isDeleting ? 'Удаление...' : 'Удалить безвозвратно'}
            </Button>
          </Group>
        </Stack>
      </Modal>
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
    deleteMutation,
  } = useUsersPage()

  // Все хуки и useMemo ДО early return
  const customColumns = React.useMemo(() => [
    { id: 'username', accessorKey: 'username', header: 'Логин', cell: (row: any) => row.username },
    { id: 'full_name', accessorKey: 'full_name', header: 'ФИО', cell: (row: any) => row.full_name || '—' },
    { id: 'role', accessorKey: 'role', header: 'Роль', cell: (row: any) => <Badge size="xs">{row.role}</Badge> },
    { id: 'is_active', accessorKey: 'is_active', header: 'Активен', cell: (row: any) => row.is_active ? '✓' : '✗' },
    { id: 'actions', header: '', cell: (row: any) => <UserRow user={row} handleUpdate={handleUpdate} handleDelete={handleDelete} deleteMutation={deleteMutation} currentUserId={currentUserId} /> },
  ], [handleUpdate, handleDelete])

  if (isLoading) return <Text c="dimmed">Загрузка...</Text>
  if (isError) return <Alert color="red">{errorText(error, 'Ошибка загрузки')}</Alert>

  return (
    <Stack gap="md">
      <Title order={3}>Пользователи</Title>
      <CreateUserForm handleCreate={handleCreate} />
      <Text size="sm" c="dimmed">Найдено пользователей: {data.length}</Text>
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
    </Stack>
  )
}