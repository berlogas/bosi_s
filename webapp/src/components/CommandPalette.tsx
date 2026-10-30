/**
 * Command Palette (Cmd/Ctrl+K) — быстрый переход по разделам, сессиям и действиям.
 */

import { useEffect, useState } from 'react'
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
  IconHome,
  IconClock,
} from '@tabler/icons-react'
import { useAuth } from '../features/auth/authStore'
import { client } from '../api/client'
import { useQuery } from '@tanstack/react-query'

interface CommandAction {
  id: string
  title: string
  description?: string
  icon: React.ReactNode
  onClick: () => void
  keywords?: string | string[]  // для поиска в Spotlight
}

interface CommandGroup {
  group: string
  actions: CommandAction[]
}

type SpotlightAction = CommandAction | CommandGroup

let openFn: (() => void) | null = null

export function openCommandPalette() {
  openFn?.()
}

function makeAction(
  id: string,
  title: string,
  description: string,
  icon: React.ReactNode,
  path: string,
  navigate: (path: string) => void,
  keywords?: string | string[]
): CommandAction {
  return {
    id,
    title,
    description,
    icon,
    keywords,
    onClick: () => {
      spotlight.close()
      setTimeout(() => navigate(path), 0)
    },
  }
}

function makeGroup(groupTitle: string, actions: CommandAction[]): CommandGroup {
  return { group: groupTitle, actions }
}

export function CommandPalette() {
  const navigate = useNavigate()
  const { user } = useAuth()
  const [recentSessions, setRecentSessions] = useState<any[]>([])

  // Загружаем недавние сессии пользователя (только активные, последние 10)
  const { data: sessionsData } = useQuery({
    queryKey: ['command-palette-sessions'],
    queryFn: () => client.sessions(),
    enabled: !!user,
    staleTime: 30_000,
  })

  useEffect(() => {
    if (Array.isArray(sessionsData)) {
      // Фильтруем только активные сессии и сортируем по последней активности
      const activeSessions = sessionsData
        .filter((s) => s.status === 'active')
        .sort((a, b) => new Date(b.last_activity_at).getTime() - new Date(a.last_activity_at).getTime())
        .slice(0, 10)
      setRecentSessions(activeSessions)
    }
  }, [sessionsData])

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

  // Навигация
  const navigationActions = makeGroup('Навигация', [
    makeAction(
      'dashboard',
      'Информационная панель',
      'Дашборд и создание сессий',
      <IconHome size={16} />,
      '/',
      navigate
    ),
    makeAction(
      'knowledge',
      'База знаний',
      'Глобальный корпус документов',
      <IconDatabase size={16} />,
      '/knowledge',
      navigate
    ),
  ])

  // Недавние сессии
  const sessionActions = recentSessions.length > 0
    ? makeGroup('Недавние сессии', recentSessions.map((s) =>
        makeAction(
          `session-${s.id}`,
          `${s.title || 'Без названия'}  ·  ${new Date(s.last_activity_at).toLocaleString()}`,
          `${s.title || 'Без названия'}  ·  Статус: ${s.status}`,
          <IconClock size={16} />,
          `/s/${s.id}/chat`,
          navigate,
          [s.title, s.id]
        )
      ))
    : null

  // Администрирование
  const adminActions = user?.role === 'admin'
    ? makeGroup('Администрирование', [
        makeAction(
          'users',
          'Пользователи',
          'Администраторы и исследователи',
          <IconUsers size={16} />,
          '/admin/users',
          navigate
        ),
        makeAction(
          'documents',
          'Глобальная база',
          'Документы базы знаний',
          <IconDatabase size={16} />,
          '/admin/documents',
          navigate
        ),
        makeAction(
          'tasks',
          'Задачи',
          'Фоновые задачи и индексация',
          <IconListCheck size={16} />,
          '/admin/tasks',
          navigate
        ),
        makeAction(
          'sessions',
          'Сессии',
          'Активные и архивные сессии',
          <IconLayoutDashboard size={16} />,
          '/admin/sessions',
          navigate
        ),
        makeAction(
          'audit',
          'Аудит',
          'Журнал действий администраторов',
          <IconFileAnalytics size={16} />,
          '/admin/audit',
          navigate
        ),
        makeAction(
          'maintenance',
          'Обслуживание',
          'Бэкапы и сброс состояния',
          <IconAdjustments size={16} />,
          '/admin/maintenance',
          navigate
        ),
        makeAction(
          'create-user',
          'Создать пользователя',
          'Новая учётная запись',
          <IconPlus size={16} />,
          '/admin/users',
          navigate
        ),
      ])
    : null

  const allActions: SpotlightAction[] = [
    navigationActions,
    sessionActions,
    adminActions,
  ].filter(Boolean) as SpotlightAction[]

  return (
    <Spotlight
      withOverlay
      zIndex={1000}
      actions={allActions}
      nothingFound={<Text c="dimmed">Ничего не найдено</Text>}
      closeOnActionTrigger={true}
    />
  )
}