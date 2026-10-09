/**
 * «Заметки» — паритет `notes_tab` (workspace.py).
 *
 * Заметка (resume_note) и снапшот UI сохраняются через PUT
 * /sessions/{id}/state; в клиенте снапшот несёт активную вкладку —
 * этого достаточно, чтобы после F5 открыться там же.
 *
 * Сам снапшот пользователю не показывается: раньше здесь выводился сырой
 * JSON `state_snapshot`, то есть отладочная выгрузка вида
 * `{"tab": "chat", "saved_at": ...}` на главном рабочем экране. Механизм
 * работает как раньше — «Продолжить» вернёт на ту вкладку, где вы были.
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

  return (
    <Stack gap="sm">
      <Title order={5}>Заметки</Title>

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

      {session.last_action_label && (
        <Text size="xs" c="dimmed">
          Последнее действие: {session.last_action_label}
        </Text>
      )}
    </Stack>
  )
}
