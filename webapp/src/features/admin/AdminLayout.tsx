/**
 * Layout для админки: навигация по вкладкам + рендер контента вкладок.
 * Заменяет Tabs внутри монолитного AdminPage.
 *
 * Важно: AdminLayout уже рендерится внутри AppLayout (внешний AppShell),
 * поэтому здесь НЕ должно быть второго AppShell — иначе контент смещается
 * вправо из-за двойных отступов и несуществующего navbar.
 */

import { useLocation, useNavigate } from 'react-router-dom'
import {
  Group,
  Box,
  Stack,
  Text,
  useMantineColorScheme,
  Alert,
} from '@mantine/core'
import { useAuth } from '../auth/authStore'
import {
  IconUsers,
  IconDatabase,
  IconListCheck,
  IconLayoutDashboard,
  IconFileAnalytics,
  IconAdjustments,
} from '@tabler/icons-react'
import UsersPage from './tabs/UsersPage'
import DocumentsPage from './tabs/DocumentsPage'
import TasksPage from './tabs/TasksPage'
import SessionsPage from './tabs/SessionsPage'
import AuditPage from './tabs/AuditPage'
import MaintenancePage from './tabs/MaintenancePage'

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
          не sticky, чтобы не накладываться на общую шапку AppLayout при скролле */}
      <Box px="md" py="sm">
        <Group justify="space-between" align="center" wrap="nowrap" style={{ minWidth: 0 }}>
          <Group gap="xs" style={{ minWidth: 0, flex: 1 }}>
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
                  style={{ whiteSpace: 'nowrap', display: 'flex', alignItems: 'center', gap: 'xs' }}
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

      {/* Контент вкладки — без AppShell, чтобы не было двойных отступов */}
      <Stack p="md">
        <ActiveComponent />
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
        padding: '4px 8px',
        borderRadius: 6,
        fontSize: 16,
      }}
    >
      {icon}
    </button>
  )
}
