/**
 * Маршруты приложения.
 *
 * Фаза 0: вход и дашборд. Дальше — /s/:id/... (чат, документы, проекты)
 * и /admin (раздел 6 плана миграции).
 */

import { Center, Loader } from '@mantine/core'
import { Navigate, Route, Routes, useLocation } from 'react-router-dom'

import { LoginPage } from './features/auth/LoginPage'
import { useAuth } from './features/auth/authStore'
import { DashboardPage } from './features/dashboard/DashboardPage'
import { AppLayout } from './features/layout/AppLayout'

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
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}
