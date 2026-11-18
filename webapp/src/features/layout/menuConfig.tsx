/**
 * Единая конфигурация левого меню (AppShellNavbar).
 * Используется в AppLayout.tsx для рендера навигации.
 */

import type { NavLinkProps } from '@mantine/core'
import {
  IconHome,
  IconDatabase,
  IconClock,
  IconUsers,
  IconListCheck,
  IconLayoutDashboard,
  IconFileAnalytics,
  IconAdjustments,
} from '@tabler/icons-react'
import type { User } from '../auth/authStore'

// Только нужные пропсы от NavLink, без children (у нас свой children для вложенных пунктов)
export interface MenuItem {
  to: string
  label: string
  icon?: React.ReactNode
  enabled?: boolean | ((user: User | null) => boolean)
  roles?: string[]
  children?: MenuItem[]  // для вложенных пунктов
  // Остальные NavLink-пропсы при необходимости:
  disabled?: NavLinkProps['disabled']
  variant?: NavLinkProps['variant']
}

export interface MenuSection {
  id: string
  header?: string
  items: MenuItem[]
  visible?: (user: User | null) => boolean
  collapsible?: boolean
  defaultOpen?: boolean
}

/** Получить путь к текущей сессии из sessionStorage */
export function getCurrentSessionPath(user: User | null): string | null {
  if (!user) return null
  try {
    const raw = sessionStorage.getItem('boasi.lastSessionPath')
    if (!raw) return null
    const parsed = JSON.parse(raw)
    return parsed.userId === user.id ? parsed.path : null
  } catch {
    return null
  }
}

/**
 * Основная конфигурация меню.
 *
 * `sessionPath` — путь текущей сессии; его должен передавать `useCurrentSessionPath`,
 * иначе пункт «Текущая сессия» не обновится, когда сессия открылась или сменилась.
 * Если путь не передан — берём из хранилища (как раньше).
 */
export function getMenuSections(user: User | null, sessionPath?: string | null): MenuSection[] {
  const path = sessionPath !== undefined ? sessionPath : getCurrentSessionPath(user)

  return [
    {
      id: 'main',
      header: 'Навигация',
      items: [
        { to: '/', label: 'Информационная панель', icon: <IconHome size={16} />, enabled: true },
        { to: '/knowledge', label: 'База знаний', icon: <IconDatabase size={16} />, enabled: true },
        {
          to: path || '',
          label: 'Текущая сессия',
          icon: <IconClock size={16} />,
          enabled: !!path,
        },
      ],
    },
    {
      id: 'admin',
      header: 'Администрирование',
      visible: (u) => u?.role === 'admin',
      collapsible: true,
      defaultOpen: true,
      items: [
        { to: '/admin/users', label: 'Пользователи', icon: <IconUsers size={16} />, roles: ['admin'] },
        { to: '/admin/documents', label: 'Глобальная база', icon: <IconDatabase size={16} />, roles: ['admin'] },
        { to: '/admin/tasks', label: 'Задачи', icon: <IconListCheck size={16} />, roles: ['admin'] },
        { to: '/admin/sessions', label: 'Сессии', icon: <IconLayoutDashboard size={16} />, roles: ['admin'] },
        { to: '/admin/audit', label: 'Аудит', icon: <IconFileAnalytics size={16} />, roles: ['admin'] },
        { to: '/admin/maintenance', label: 'Обслуживание', icon: <IconAdjustments size={16} />, roles: ['admin'] },
      ],
    },
  ]
}

/** Старые адреса, которые ещё работают (AdminLayout их понимает). */
const PATH_ALIASES: Record<string, string> = {
  '/admin/base': '/admin/documents',
}

/** Проверить, активен ли пункт (или его родительская секция) */
export function isItemActive(pathname: string, to: string): boolean {
  if (!to) return false
  const path = PATH_ALIASES[pathname] ?? pathname
  if (to === '/') return path === '/'
  return path === to || path.startsWith(`${to}/`)
}

/** Проверить, активна ли секция (хотя бы один дочерний пункт активен) */
export function isSectionActive(pathname: string, items: MenuItem[]): boolean {
  return items.some((item) => {
    if (item.children) return isSectionActive(pathname, item.children)
    return isItemActive(pathname, item.to)
  })
}