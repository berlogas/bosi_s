/**
 * Карточка сессии на дашборде — паритет `ui.session_card` (Streamlit).
 *
 * Превью последнего действия, срок жизни, «Продолжить» и архив в ДВА шага:
 * первый клик открывает модалку «Подтвердите», второй уносит сессию в
 * архив. Архивация необратима (reactivate_session для archived не пускает),
 * поэтому одного клика мало — так же, как в Streamlit-версии.
 */

import { Button, Card, Group, Modal, Stack, Text } from '@mantine/core'
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'

import type { SessionOut } from '../../api/types'
import { shortWhen, STATUS_ICONS } from '../../lib/format'
import { useArchiveSession } from './queries'

/** Сколько дней осталось — как days_left() на бэкенде: ceil до суток. */
function daysLeft(session: SessionOut): number {
  const delta = new Date(session.expires_at).getTime() - Date.now()
  return Math.max(0, Math.ceil(delta / 86_400_000))
}

function ttlLabel(days: number): string {
  if (days <= 0) return 'срок истёк'
  if (days === 1) return 'остался 1 день'
  if (days < 5) return `осталось ${days} дня`
  return `осталось ${days} дней`
}

export function SessionCard({ session }: { session: SessionOut }) {
  const navigate = useNavigate()
  const [confirmOpened, setConfirmOpened] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const archive = useArchiveSession()

  const archived = session.status === 'archived'
  const title = session.title || 'Без названия'
  const icon = STATUS_ICONS[session.status] ?? ''
  const label = session.last_action_label || 'без действий'

  function handleArchive() {
    archive.mutate(session.id, {
      onSuccess: () => setConfirmOpened(false),
      onError: (cause) =>
        setError(cause instanceof Error ? cause.message : 'Не удалось архивировать'),
    })
  }

  return (
    <Card withBorder padding="sm" data-testid="session-card">
      <Group align="flex-start" wrap="nowrap">
        <Stack gap={4} style={{ flex: 1 }}>
          <Text fw={600}>{title}</Text>
          <Text size="xs" c="dimmed">
            {icon} {session.status} · {label} · {shortWhen(session.last_action_at)}
          </Text>
          {session.resume_note && (
            <Text size="xs" c="dimmed">
              Заметка: {session.resume_note}
            </Text>
          )}
          {!archived && (
            <Text size="xs" c="dimmed">
              Срок хранения: {ttlLabel(daysLeft(session))}
            </Text>
          )}
        </Stack>

        <Button
          size="xs"
          variant="light"
          disabled={archived}
          onClick={() => navigate(`/s/${session.id}`)}
        >
          Продолжить
        </Button>

        <Button
          size="xs"
          variant="light"
          color="red"
          disabled={session.status !== 'active'}
          onClick={() => setConfirmOpened(true)}
        >
          Архив
        </Button>
      </Group>

      <Modal
        opened={confirmOpened}
        onClose={() => setConfirmOpened(false)}
        title="Подтвердите: сессия уйдёт в архив"
        centered
      >
        <Stack>
          <Text size="sm">
            Сессия станет только для чтения: вернуть её из интерфейса будет нельзя.
          </Text>
          {error && (
            <Text size="sm" c="red">
              {error}
            </Text>
          )}
          <Group justify="flex-end">
            <Button variant="default" onClick={() => setConfirmOpened(false)}>
              Отмена
            </Button>
            <Button color="red" loading={archive.isPending} onClick={handleArchive}>
              Да, в архив
            </Button>
          </Group>
        </Stack>
      </Modal>
    </Card>
  )
}
