/**
 * Подтверждение необратимого удаления.
 *
 * Один клик по «🗑» раньше сразу уносил пару сообщений или документ: без
 * soft-delete восстановить их нельзя, поэтому спрашиваем явно. Пока диалог
 * открыт, запрос не уходит; «Отмена» ничего не меняет.
 */

import { Button, Group, Modal, Stack, Text } from '@mantine/core'
import type { ReactNode } from 'react'

export function ConfirmDeleteModal({
  opened,
  title,
  subject,
  error,
  loading,
  onCancel,
  onConfirm,
}: {
  opened: boolean
  title: string
  /** Что именно удаляем — вопрос, название документа. */
  subject: ReactNode
  error?: string | null
  loading?: boolean
  onCancel: () => void
  onConfirm: () => void
}) {
  return (
    <Modal opened={opened} onClose={onCancel} title={title} centered>
      <Stack>
        <Text size="sm">{subject}</Text>
        <Text size="sm" c="dimmed">
          Действие необратимо: восстановить из интерфейса будет нельзя.
        </Text>
        {error && (
          <Text size="sm" c="red" role="alert">
            {error}
          </Text>
        )}
        <Group justify="flex-end">
          <Button variant="default" onClick={onCancel} disabled={loading}>
            Отмена
          </Button>
          <Button color="red" loading={loading} onClick={onConfirm}>
            Удалить
          </Button>
        </Group>
      </Stack>
    </Modal>
  )
}
