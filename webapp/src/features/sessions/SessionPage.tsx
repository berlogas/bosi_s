/**
 * Страница сессии — каркас Фазы 1 (паритет `_header` из workspace.py).
 *
 * Вкладки (Документы/Проекты/Чат/Заметки) — Фаза 2–3; здесь шапка:
 * статус, срок хранения, лимиты, «Пауза»/«Архив» с подтверждением и
 * режим «только чтение» для архивных сессий.
 */

import {
  Alert,
  Button,
  Group,
  Loader,
  Modal,
  Progress,
  Stack,
  Text,
  Title,
} from '@mantine/core'
import { useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'

import { client } from '../../api/client'
import { useArchiveSession, useSessionDetail } from '../dashboard/queries'
import { ttlLabel } from '../../lib/format'

function Limits({
  documents,
  documentsLimit,
  storageBytes,
  storageLimitBytes,
}: {
  documents: number
  documentsLimit: number
  storageBytes: number
  storageLimitBytes: number
}) {
  const usedMb = storageBytes / (1024 * 1024)
  const limitMb = storageLimitBytes / (1024 * 1024)
  return (
    <Stack gap={4}>
      <Text size="xs" c="dimmed">
        Документы: {documents}/{documentsLimit} · Хранилище: {usedMb.toFixed(1)}/
        {limitMb.toFixed(0)} МБ
      </Text>
      {documents >= documentsLimit && (
        <Text size="xs" c="orange">
          Достигнут лимит документов — удалите лишние.
        </Text>
      )}
      <Progress
        value={(documents / Math.max(1, documentsLimit)) * 100}
        size="xs"
        aria-label="Лимит документов"
      />
    </Stack>
  )
}

export function SessionPage() {
  const { sessionId } = useParams<{ sessionId: string }>()
  const navigate = useNavigate()
  const detail = useSessionDetail(sessionId ?? null)
  const archive = useArchiveSession()
  const [confirmOpened, setConfirmOpened] = useState(false)
  const [actionError, setActionError] = useState<string | null>(null)

  if (detail.isPending) {
    return <Loader size="sm" />
  }

  if (detail.isError || !detail.data) {
    return (
      <Alert color="red" role="alert">
        {detail.error instanceof Error ? detail.error.message : 'Сессия не найдена'}
        <Group mt="sm">
          <Button size="xs" variant="light" onClick={() => navigate('/')}>
            ← Дашборд
          </Button>
        </Group>
      </Alert>
    )
  }

  const session = detail.data
  const readOnly = session.status === 'archived'

  async function handlePause() {
    setActionError(null)
    try {
      await client.pauseSession(session.id)
      await detail.refetch()
    } catch (cause) {
      setActionError(
        cause instanceof Error ? cause.message : 'Не удалось поставить на паузу',
      )
    }
  }

  function handleArchiveConfirm() {
    setActionError(null)
    archive.mutate(session.id, {
      onSuccess: () => {
        setConfirmOpened(false)
        void detail.refetch()
      },
      onError: (cause) =>
        setActionError(
          cause instanceof Error ? cause.message : 'Не удалось архивировать',
        ),
    })
  }

  return (
    <Stack gap="md">
      <Group justify="space-between" align="flex-start">
        <Stack gap={4}>
          <Title order={3}>{session.title}</Title>
          <Text size="sm" c="dimmed">
            Статус: {session.status} · Срок хранения: {ttlLabel(session.days_left)}
          </Text>
          <Limits
            documents={session.summary.documents}
            documentsLimit={session.summary.documents_limit}
            storageBytes={session.summary.storage_bytes}
            storageLimitBytes={session.summary.storage_limit_bytes}
          />
        </Stack>

        <Group gap="xs">
          <Button
            size="xs"
            variant="light"
            disabled={readOnly}
            onClick={() => void handlePause()}
          >
            Пауза
          </Button>
          <Button
            size="xs"
            variant="light"
            color="red"
            disabled={readOnly}
            onClick={() => setConfirmOpened(true)}
          >
            Архив
          </Button>
          <Button size="xs" variant="default" onClick={() => navigate('/')}>
            ← Дашборд
          </Button>
        </Group>
      </Group>

      {actionError && (
        <Alert color="red" role="alert">
          {actionError}
        </Alert>
      )}

      {readOnly && (
        <Alert color="yellow">Сессия в архиве — доступно только чтение.</Alert>
      )}

      <Alert color="blue" title="Разделы сессии">
        Вкладки «Документы · Проекты · Чат · Заметки» появятся в Фазе 2–3 миграции.
      </Alert>

      <Modal
        opened={confirmOpened}
        onClose={() => setConfirmOpened(false)}
        title="Подтвердите: сессия уйдёт в архив"
        centered
      >
        <Stack>
          <Text size="sm">
            Архивировать сессию? Она станет только для чтения: вернуть её из интерфейса
            будет нельзя.
          </Text>
          <Group justify="flex-end">
            <Button variant="default" onClick={() => setConfirmOpened(false)}>
              Отмена
            </Button>
            <Button
              color="red"
              loading={archive.isPending}
              onClick={handleArchiveConfirm}
            >
              Да, в архив
            </Button>
          </Group>
        </Stack>
      </Modal>
    </Stack>
  )
}
