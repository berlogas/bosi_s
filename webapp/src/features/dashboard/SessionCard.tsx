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
import {
  fullWhen,
  shortWhen,
  sessionStatusLabel,
  STATUS_ICONS,
  ttlLabel,
} from '../../lib/format'
import { sessionTabPath, tabFromState } from '../sessions/tabPaths'
import { useArchiveSession, useResumeSession } from './queries'

/** Сколько дней осталось — как days_left() на бэкенде: ceil до суток. */
function daysLeft(session: SessionOut): number {
  const delta = new Date(session.expires_at).getTime() - Date.now()
  return Math.max(0, Math.ceil(delta / 86_400_000))
}

/**
 * Подпись владельца в карточке не выводится: администратору карточки
 * разложены по группам владельцев (см. `SessionGroups`), а исследователю
 * слово «владелец» и так лишнее — это его собственная сессия.
 */
export function SessionCard({ session }: { session: SessionOut }) {
  const navigate = useNavigate()
  const [confirmOpened, setConfirmOpened] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const archive = useArchiveSession()
  const resume = useResumeSession()

  const archived = session.status === 'archived'
  const paused = session.status === 'paused'
  const title = session.title || 'Без названия'
  const icon = STATUS_ICONS[session.status] ?? ''
  const label = session.last_action_label || 'без действий'

  function handleOpen() {
    if (paused) {
      setError(null)
      resume.mutate(session.id, {
        onSuccess: (data) =>
          navigate(sessionTabPath(session.id, tabFromState(data.state))),
        onError: (cause) =>
          setError(
            cause instanceof Error ? cause.message : 'Не удалось возобновить сессию',
          ),
      })
      return
    }
    navigate(`/s/${session.id}`)
  }

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
            {icon} {sessionStatusLabel(session.status)} · {label} ·{' '}
            <span title={fullWhen(session.last_action_at)}>
              {shortWhen(session.last_action_at)}
            </span>
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
          loading={resume.isPending && resume.variables === session.id}
          onClick={handleOpen}
        >
          {paused ? 'Возобновить' : 'Продолжить'}
        </Button>

        <Button
          size="xs"
          variant="light"
          color="red"
          // paused архивируется так же, как active: API это разрешает, а
          // «убрать с глаз» не должно требовать сначала возобновлять сессию
          disabled={archived}
          onClick={() => setConfirmOpened(true)}
        >
          Архив
        </Button>
      </Group>

      {error && !confirmOpened && (
        <Text size="xs" c="red" role="alert">
          {error}
        </Text>
      )}

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
