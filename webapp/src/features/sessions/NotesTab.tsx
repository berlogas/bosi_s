/**
 * «Заметки и точка возврата» — паритет `notes_tab` (workspace.py).
 *
 * Заметка (resume_note) и снапшот UI сохраняются через PUT
 * /sessions/{id}/state; в клиенте снапшот несёт активную вкладку —
 * этого достаточно, чтобы после F5 открыться там же (черновики
 * документов придут в Фазе 3).
 */

import { Alert, Button, Group, Stack, Text, Textarea, Title } from '@mantine/core'
import { useEffect, useState } from 'react'

import type { SessionDetail } from '../../api/types'
import { useSaveState } from '../chat/queries'

export function NotesTab({
  session,
  readOnly,
  snapshotTab,
  onSaved,
}: {
  session: SessionDetail
  readOnly: boolean
  /** Значение «tab» для автосохранения снапшота. */
  snapshotTab: string
  /** Сообщить родителю, что заметка сохранена (обновить detail). */
  onSaved?: () => void
}) {
  const [note, setNote] = useState(session.resume_note ?? '')
  const [saved, setSaved] = useState(false)
  const save = useSaveState(session.id)

  // при обновлении detail извне (например, после F5) подтянуть заметку
  useEffect(() => {
    setNote(session.resume_note ?? '')
  }, [session.resume_note])

  function handleSave() {
    setSaved(false)
    save.mutate(
      {
        resume_note: note || null,
        snapshot: { tab: snapshotTab },
        action_label: 'Заметка сохранена',
        force: true,
      },
      {
        onSuccess: () => {
          setSaved(true)
          onSaved?.()
        },
      },
    )
  }

  const snapshot = { ...(session.state_snapshot ?? {}) }
  delete snapshot.saved_at
  const hasSnapshot = Object.keys(snapshot).length > 0

  return (
    <Stack gap="sm">
      <Title order={5}>Заметки и точка возврата</Title>

      <Textarea
        label="Заметка о работе"
        placeholder="Что делали, на чём остановились…"
        value={note}
        onChange={(event) => setNote(event.currentTarget.value)}
        minRows={4}
        autosize
        maxRows={12}
        disabled={readOnly}
      />

      <Group>
        <Button
          size="sm"
          disabled={readOnly}
          loading={save.isPending}
          onClick={handleSave}
        >
          Сохранить заметку
        </Button>
        {saved && save.isSuccess && (
          <Text size="sm" c="green">
            Заметка сохранена.
          </Text>
        )}
      </Group>

      {save.isError && (
        <Alert color="red" role="alert">
          {save.error instanceof Error ? save.error.message : 'Не удалось сохранить'}
        </Alert>
      )}

      <Title order={6}>Состояние (точка возврата)</Title>
      {hasSnapshot ? (
        <pre
          style={{
            margin: 0,
            padding: '8px 12px',
            background: 'var(--mantine-color-gray-0)',
            borderRadius: 6,
            fontSize: 'var(--mantine-font-size-sm)',
          }}
        >
          {JSON.stringify(snapshot, null, 2)}
        </pre>
      ) : (
        <Text size="sm" c="dimmed">
          Состояние пока не сохранялось.
        </Text>
      )}

      {session.last_action_label && (
        <Text size="xs" c="dimmed">
          Последнее действие: {session.last_action_label}
        </Text>
      )}
    </Stack>
  )
}
