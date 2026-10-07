/**
 * Страницы-вкладки сессии: чат, заметки, документы и проекты.
 *
 * Маршруты `/s/:id/{chat,notes,documents,projects}`; общий контекст
 * (detail сессии, readOnly) отдаётся через Outlet от SessionPage.
 */

import { useOutletContext, useParams } from 'react-router-dom'

import { ChatTab } from '../chat/ChatTab'
import type { SessionDetail } from '../../api/types'
import { DocumentsTab } from '../documents/DocumentsTab'
import { NotesTab } from './NotesTab'
import { ProjectsTab } from '../projects/ProjectsTab'

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
  if (!sessionId) return null
  // detail из контекста уже содержит resume_note (SessionPage его читает)
  return <NotesTab session={session} readOnly={readOnly} snapshotTab="notes" />
}

export function DocumentsRoute() {
  const { readOnly } = useOutletContext<SessionOutletContext>()
  const { sessionId } = useParams<{ sessionId: string }>()
  if (!sessionId) return null
  return <DocumentsTab sessionId={sessionId} readOnly={readOnly} />
}

export function ProjectsRoute() {
  const { readOnly } = useOutletContext<SessionOutletContext>()
  const { sessionId } = useParams<{ sessionId: string }>()
  if (!sessionId) return null
  return <ProjectsTab sessionId={sessionId} readOnly={readOnly} />
}
