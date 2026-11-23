/**
 * Маршруты приложения.
 *
 * Фаза 0: вход и дашборд. Фаза 1: сессии. Фаза 2: вкладки сессии как
 * маршруты (`/s/:id/chat`, …) — план, п. E.
 */

import { Center, Loader } from '@mantine/core'
import { Navigate, Route, Routes, useLocation } from 'react-router-dom'
import { lazy, Suspense } from 'react'

import { LoginPage } from './features/auth/LoginPage'
import { useAuth } from './features/auth/authStore'
import { DashboardPage } from './features/dashboard/DashboardPage'
import { RouteErrorBoundary } from './components/RouteErrorBoundary'
import { AppLayout } from './features/layout/AppLayout'
import { SessionPage } from './features/sessions/SessionPage'

// Код сплиттинг для тяжёлых страниц (Волна 6, п.3):
// каждая страница загружается отдельным чанком только при первом посещении
const AdminLayout = lazy(() =>
  import('./features/admin/AdminLayout').then((m) => ({ default: m.AdminLayout })),
)
const KnowledgePage = lazy(() =>
  import('./features/knowledge/KnowledgePage').then((m) => ({
    default: m.KnowledgePage,
  })),
)
const ChatRoute = lazy(() =>
  import('./features/sessions/tabs').then((m) => ({ default: m.ChatRoute })),
)
const DocumentsRoute = lazy(() =>
  import('./features/sessions/tabs').then((m) => ({ default: m.DocumentsRoute })),
)
const NotesRoute = lazy(() =>
  import('./features/sessions/tabs').then((m) => ({ default: m.NotesRoute })),
)
const ProjectsRoute = lazy(() =>
  import('./features/sessions/tabs').then((m) => ({ default: m.ProjectsRoute })),
)

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
            <RouteErrorBoundary>
              <AppLayout />
            </RouteErrorBoundary>
          </RequireAuth>
        }
      >
        <Route path="/" element={<DashboardPage />} />
        {/* Глобальная база знаний на чтение: доступна и исследователю,
            который не может её наполнять (наполняет администратор) */}
        <Route
          path="/knowledge"
          element={
            <Suspense fallback={<Loader />}>
              <KnowledgePage />
            </Suspense>
          }
        />
        {/* Админка: страницы по вкладкам. Оба варианта адреса (/admin и /admin/:tab)
            рендерят AdminLayout, который сам определяет активную вкладку по URL. */}
        <Route
          path="/admin"
          element={
            <Suspense fallback={<Loader />}>
              <AdminLayout />
            </Suspense>
          }
        />
        <Route
          path="/admin/:tab"
          element={
            <Suspense fallback={<Loader />}>
              <AdminLayout />
            </Suspense>
          }
        />
        <Route path="/s/:sessionId" element={<SessionPage />}>
          {/* без вкладки — на чат (у Streamlit это был active_tab) */}
          <Route index element={<Navigate to="chat" replace />} />
          <Route
            path="chat"
            element={
              <Suspense fallback={<Loader />}>
                <ChatRoute />
              </Suspense>
            }
          />
          <Route
            path="notes"
            element={
              <Suspense fallback={<Loader />}>
                <NotesRoute />
              </Suspense>
            }
          />
          <Route
            path="documents"
            element={
              <Suspense fallback={<Loader />}>
                <DocumentsRoute />
              </Suspense>
            }
          />
          <Route
            path="projects"
            element={
              <Suspense fallback={<Loader />}>
                <ProjectsRoute />
              </Suspense>
            }
          />
        </Route>
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}
