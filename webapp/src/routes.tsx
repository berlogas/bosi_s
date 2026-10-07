/**
 * Маршруты приложения.
 *
 * Фаза 0: вход и дашборд. Фаза 1: сессии. Фаза 2: вкладки сессии как
 * маршруты (`/s/:id/chat`, …) — план, п. E.
 */

import { Center, Loader } from '@mantine/core'
import { Navigate, Route, Routes, useLocation } from 'react-router-dom'

import { LoginPage } from './features/auth/LoginPage'
import { useAuth } from './features/auth/authStore'
import { DashboardPage } from './features/dashboard/DashboardPage'
import { AppLayout } from './features/layout/AppLayout'
import { SessionPage } from './features/sessions/SessionPage'
import {
  ChatRoute,
  DocumentsRoute,
  NotesRoute,
  ProjectsRoute,
} from './features/sessions/tabs'

function RequireAuth({ children }: { children: React.ReactElement }) {
  const status = useAuth((state) => state.status)
  const location = useLocation()

  if (status === 'boot') {
    return (
      <Center mih="100vh">
        <Loader />
      </Center>
    )
  }
  if (status === 'anonymous') {
    return <Navigate to="/login" state={{ from: location }} replace />
  }
  return children
}

export function AppRoutes() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route
        element={
          <RequireAuth>
            <AppLayout />
          </RequireAuth>
        }
      >
        <Route path="/" element={<DashboardPage />} />
        <Route path="/s/:sessionId" element={<SessionPage />}>
          {/* без вкладки — на чат (у Streamlit это был active_tab) */}
          <Route index element={<Navigate to="chat" replace />} />
          <Route path="chat" element={<ChatRoute />} />
          <Route path="notes" element={<NotesRoute />} />
          <Route path="documents" element={<DocumentsRoute />} />
          <Route path="projects" element={<ProjectsRoute />} />
        </Route>
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}
