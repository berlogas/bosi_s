/**
 * Layout для админки: навигация по вкладкам + рендер контента вкладок.
 * Заменяет Tabs внутри монолитного AdminPage.
 *
 * Важно: AdminLayout уже рендерится внутри AppLayout (внешний AppShell),
 * поэтому здесь НЕ должно быть второго AppShell — иначе контент смещается
 * вправо из-за двойных отступов и несуществующего navbar.
 */

import { useLocation, useNavigate } from 'react-router-dom'
import { Suspense, lazy } from 'react'
import {
  Group,
  Box,
  Stack,
  Text,
  useMantineColorScheme,
  Alert,
} from '@mantine/core'
import { SkeletonList } from '../../components/SkeletonList'
import { useAuth } from '../auth/authStore'
import {
  IconUsers,
  IconDatabase,
  IconListCheck,
  IconLayoutDashboard,
  IconFileAnalytics,
  IconAdjustments,
} from '@tabler/icons-react'

const UsersPage = lazy(() => import('./tabs/UsersPage').then((m) => ({ default: m.UsersPage })))
const DocumentsPage = lazy(() => import('./tabs/DocumentsPage').then((m) => ({ default: m.DocumentsPage })))
const TasksPage = lazy(() => import('./tabs/TasksPage').then((m) => ({ default: m.TasksPage })))
const SessionsPage = lazy(() => import('./tabs/SessionsPage').then((m) => ({ default: m.SessionsPage })))
const AuditPage = lazy(() => import('./tabs/AuditPage').then((m) => ({ default: m.AuditPage })))
const MaintenancePage = lazy(() => import('./tabs/MaintenancePage').then((m) => ({ default: m.MaintenancePage })))

const TABS = [
  { path: 'users', label: 'Пользователи', icon: IconUsers, component: UsersPage },
  { path: 'documents', label: 'Глобальная база', icon: IconDatabase, component: DocumentsPage },
  { path: 'tasks', label: 'Задачи', icon: IconListCheck, component: TasksPage },
  { path: 'sessions', label: 'Сессии', icon: IconLayoutDashboard, component: SessionsPage },
  { path: 'audit', label: 'Аудит', icon: IconFileAnalytics, component: AuditPage },
  { path: 'maintenance', label: 'Обслуживание', icon: IconAdjustments, component: MaintenancePage },
] as const

export function AdminLayout() {
  const { user } = useAuth()
  const navigate = useNavigate()

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

  // Активная вкладка — по текущему URL.
  // «base» — старое имя вкладки «Глобальная база», оставлено для обратной совместимости.
  const location = useLocation()
  const currentTab = location.pathname.split('/').filter(Boolean)[1] || 'users'
  const tabPath = currentTab === 'base' ? 'documents' : currentTab
  const knownTabPaths = TABS.map((t) => t.path)
  const activeTab = knownTabPaths.includes(tabPath as any) ? tabPath : 'users'

  const tabComponentMap: Record<string, React.ComponentType> = {
    users: UsersPage,
    documents: DocumentsPage,
    tasks: TasksPage,
    sessions: SessionsPage,
    audit: AuditPage,
    maintenance: MaintenancePage,
  }
  const ActiveComponent = tabComponentMap[activeTab as any] || UsersPage

  const handleTabClick = (path: string) => () => {
    navigate(`/admin/${path}`)
  }

  return (
    <Stack>
      {/* Навигация по вкладкам (заменяет st.tabs / Mantine Tabs) —
          фиксирована вверху экрана, чтобы меню всегда оставалось в поле зрения */}
      <Box
        px="md"
        py="sm"
        style={{
          position: 'fixed',
          top: 0,
          left: 260, // ширина сайдбара AppShellNavbar
          right: 0,
          zIndex: 100,
          backgroundColor: 'var(--mantine-color-body)',
          borderBottom: '1px solid var(--mantine-color-default-border)',
          borderRadius: `0 0 var(--mantine-radius-md) var(--mantine-radius-md)`,
        }}
      >
        <Group justify="space-between" align="center" wrap="nowrap" style={{ minWidth: 0 }}>
          <Group gap="sm" style={{ minWidth: 0, flex: 1 }}>
            {TABS.map((tab) => {
              const isActive = tab.path === activeTab
              return (
                <div
                  key={tab.path}
                  onClick={handleTabClick(tab.path)}
                  role="link"
                  tabIndex={0}
                  className={`
                    px-3 py-2 rounded-md text-sm font-medium transition-colors cursor-pointer
                    ${isActive
                      ? 'bg-primary-filled text-primary-color'
                      : 'text-gray-600 hover:bg-gray-100 dark:hover:bg-dark-600'}
                  `}
                  style={{ whiteSpace: 'nowrap', display: 'flex', alignItems: 'center', gap: 'sm' }}
                >
                  <span role="tab" aria-selected={isActive}>
                    <tab.icon size={16} />
                    <Text size="sm" fw={500}>{tab.label}</Text>
                  </span>
                </div>
              )
            })}
          </Group>
          <ColorSchemeToggle />
        </Group>
      </Box>

      {/* Контент вкладки — без AppShell, чтобы не было двойных отступов.
          padding-top компенсирует фиксированное меню. */}
      <Stack p="md" style={{ paddingTop: 'var(--mantine-spacing-xl)' }}>
        <Suspense fallback={<SkeletonList count={3} />}>
          <ActiveComponent />
        </Suspense>
      </Stack>
    </Stack>
  )
}

function ColorSchemeToggle() {
  const colorScheme = useMantineColorScheme()
  const toggle = () => colorScheme.toggleColorScheme()
  const icon = colorScheme.colorScheme === 'dark' ? '☀️' : '🌙'

  return (
    <button
      onClick={toggle}
      aria-label={`Переключить текущую тему (${colorScheme.colorScheme})`}
      style={{
        border: 'none',
        background: 'transparent',
        cursor: 'pointer',
        padding: 'var(--mantine-spacing-xs) var(--mantine-spacing-sm)',
        borderRadius: 'var(--mantine-radius-sm)',
        fontSize: 'var(--mantine-font-size-md)',
      }}
    >
      {icon}
    </button>
  )
}
export default AdminLayout
