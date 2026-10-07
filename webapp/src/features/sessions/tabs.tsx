/**
 * Страницы-вкладки сессии: чат, заметки и заглушки Фазы 3.
 *
 * Маршруты `/s/:id/{chat,notes,documents,projects}`; общий контекст
 * (detail сессии, readOnly) отдаётся через Outlet от SessionPage.
 */

import { Alert, Stack } from '@mantine/core'
import { useOutletContext, useParams } from 'react-router-dom'

import { ChatTab } from '../chat/ChatTab'
import type { SessionDetail } from '../../api/types'
import { NotesTab } from './NotesTab'
import { useSessionDetail } from '../dashboard/queries'

export interface SessionOutletContext {
  session: SessionDetail
  readOnly: boolean
}

export function ChatRoute() {
  const { readOnly } = useOutletContext<SessionOutletContext>()
  const { sessionId } = useParams<{ sessionId: string }>()
  if (!sessionId) return null
  return <ChatTab sessionId={sessionId} readOnly={readOnly} />
}

export function NotesRoute() {
  const { session, readOnly } = useOutletContext<SessionOutletContext>()
  const { sessionId } = useParams<{ sessionId: string }>()
  const detail = useSessionDetail(sessionId ?? null)
  if (!sessionId) return null
  // приходим за свежим detail (нужен resume_note после сохранения извне)
  const current = detail.data ?? session
  return (
    <NotesTab
      session={current}
      readOnly={readOnly}
      snapshotTab="notes"
      onSaved={() => void detail.refetch()}
    />
  )
}

/** Документы и проекты — Фаза 3 (паритет project_editor/documents_tab). */
export function PlaceholderRoute({ title }: { title: string }) {
  return (
    <Stack>
      <Alert color="blue">{title} появятся в Фазе 3 миграции.</Alert>
    </Stack>
  )
}
