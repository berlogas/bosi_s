/**
 * Command Palette (Cmd/Ctrl+K) — быстрый переход по разделам, сессиям и действиям.
 * Аналог палитры в v0.app: глобальный поиск по всему приложению.
 */

import { useEffect } from 'react'
import { Spotlight, spotlight } from '@mantine/spotlight'
import { useNavigate } from 'react-router-dom'
import { Text } from '@mantine/core'
import {
  IconUsers,
  IconDatabase,
  IconListCheck,
  IconLayoutDashboard,
  IconFileAnalytics,
  IconAdjustments,
  IconPlus,
} from '@tabler/icons-react'
import { useAuth } from '../features/auth/authStore'

interface CommandItem {
  id: string
  label: string
  icon: React.ReactNode
  description?: string
  onSelect: () => void
}

/**
 * Глобальный экземпляр для открытия палитры из любого места приложения.
 */
let openFn: (() => void) | null = null

export function openCommandPalette() {
  openFn?.()
}

export function CommandPalette() {
  const navigate = useNavigate()
  const { user } = useAuth()

  // Регистрируем функцию открытия для внешнего вызова
  useEffect(() => {
    openFn = () => spotlight.open()

    const handleKey = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key === 'k') {
        event.preventDefault()
        spotlight.toggle()
      }
    }

    document.addEventListener('keydown', handleKey)
    return () => {
      document.removeEventListener('keydown', handleKey)
      openFn = null
    }
  }, [])

  const actions: Array<{
    id: string
    title: string
    description?: string
    icon: React.ReactNode
    onSelect: () => void
  }> = [
    {
      id: 'users',
      title: 'Пользователи',
      description: 'Администраторы и исследователи',
      icon: <IconUsers size={16} />,
      onSelect: () => navigate('/admin/users'),
    },
    {
      id: 'documents',
      title: 'Глобальная база',
      description: 'Документы базы знаний',
      icon: <IconDatabase size={16} />,
      onSelect: () => navigate('/admin/documents'),
    },
    {
      id: 'tasks',
      title: 'Задачи',
      description: 'Фоновые задачи и индексация',
      icon: <IconListCheck size={16} />,
      onSelect: () => navigate('/admin/tasks'),
    },
    {
      id: 'sessions',
      title: 'Сессии',
      description: 'Активные и архивные сессии',
      icon: <IconLayoutDashboard size={16} />,
      onSelect: () => navigate('/admin/sessions'),
    },
    {
      id: 'audit',
      title: 'Аудит',
      description: 'Журнал действий администраторов',
      icon: <IconFileAnalytics size={16} />,
      onSelect: () => navigate('/admin/audit'),
    },
    {
      id: 'maintenance',
      title: 'Обслуживание',
      description: 'Бэкапы и сброс состояния',
      icon: <IconAdjustments size={16} />,
      onSelect: () => navigate('/admin/maintenance'),
    },
    ...(user?.role === 'admin'
      ? [
          {
            id: 'create-user',
            title: 'Создать пользователя',
            description: 'Новая учётная запись',
            icon: <IconPlus size={16} />,
            onSelect: () => navigate('/admin/users'),
          },
        ]
      : []),
  ]

  return (
    <Spotlight
      withOverlay
      zIndex={1000}
      actions={actions.map((action) => ({
        id: action.id,
        title: action.title,
        description: action.description,
        icon: action.icon,
        onSelect: action.onSelect,
      }))}
      nothingFound={<Text c="dimmed">Ничего не найдено</Text>}
    />
  )
}
