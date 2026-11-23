/**
 * Layout для админки: рендер контента активной вкладки.
 * Навигация по табам теперь в левом меню (AppShellNavbar через menuConfig).
 * Здесь НЕ должно быть своего AppShell и НЕ должно быть фиксированной панели табов.
 */

import { Navigate, useLocation } from 'react-router-dom'
import { Suspense, lazy } from 'react'
import { Stack, Skeleton } from '@mantine/core'
import { useAuth } from '../auth/authStore'
import { Alert } from '@mantine/core'

const UsersPage = lazy(() => import('./tabs/UsersPage'))
const DocumentsPage = lazy(() => import('./tabs/DocumentsPage'))
const TasksPage = lazy(() => import('./tabs/TasksPage'))
const SessionsPage = lazy(() => import('./tabs/SessionsPage'))
const AuditPage = lazy(() => import('./tabs/AuditPage'))
const MaintenancePage = lazy(() => import('./tabs/MaintenancePage'))

const TAB_COMPONENTS: Record<string, React.ComponentType> = {
  users: UsersPage,
  documents: DocumentsPage,
  tasks: TasksPage,
  sessions: SessionsPage,
  audit: AuditPage,
  maintenance: MaintenancePage,
}

export function AdminLayout() {
  const { user } = useAuth()
  const location = useLocation()

  // Только администратор может заходить в админку
  if (!user || user.role !== 'admin') {
    return (
      <Stack p="md">
        <Alert color="red" title="Доступ запрещён">
          Раздел доступен только администратору.
        </Alert>
      </Stack>
    )
  }

  // Активная вкладка — по текущему URL: /admin/users → users
  // «base» — старое имя вкладки «Глобальная база», оставлено для обратной совместимости.
  const currentTab = location.pathname.split('/').filter(Boolean)[1] || 'users'
  const tabPath = currentTab === 'base' ? 'documents' : currentTab
  const knownTabs = Object.keys(TAB_COMPONENTS)
  // Неизвестная вкладка: показываем «Пользователей», но и адрес приводим
  // в порядок — иначе в меню не выделен ни один пункт.
  if (!knownTabs.includes(tabPath)) {
    return <Navigate to="/admin/users" replace />
  }
  const activeTab = tabPath

  const ActiveComponent = TAB_COMPONENTS[activeTab] || UsersPage

  return (
    <Stack p="md">
      <Suspense
        fallback={
          <Stack gap="md" p="md">
            <Skeleton height={28} width={200} />
            <Skeleton height={200} />
          </Stack>
        }
      >
        <ActiveComponent />
      </Suspense>
    </Stack>
  )
}

export default AdminLayout
