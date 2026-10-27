/**
 * Command Palette (Cmd/Ctrl+K) — быстрый переход по разделам, сессиям и действиям.
 * Аналог палитры в v0.app: глобальный поиск по всему приложению.
 */

import { useEffect, useState } from 'react'
import { Spotlight, SpotlightRoot, SpotlightSearch, SpotlightActionsGroup, SpotlightActionsList, SpotlightAction, SpotlightEmpty } from '@mantine/spotlight'
import { useNavigate } from 'react-router-dom'
import {
  Box,
  Group,
  Text,
} from '@mantine/core'
import {
  IconSearch,
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
  label: string
  icon: React.ReactNode
  hint?: string
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
  const [opened, setOpened] = useState(false)
  const navigate = useNavigate()
  const { user } = useAuth()

  // Регистрируем функцию открытия для внешнего вызова
  useEffect(() => {
    openFn = () => setOpened(true)

    const handleKey = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key === 'k') {
        event.preventDefault()
        setOpened(true)
      }
    }

    document.addEventListener('keydown', handleKey)
    return () => {
      document.removeEventListener('keydown', handleKey)
      openFn = null
    }
  }, [])

  const items: CommandItem[] = [
    {
      label: 'Пользователи',
      icon: <IconUsers size={16} />,
      hint: 'Администраторы и исследователи',
      onSelect: () => navigate('/admin/users'),
    },
    {
      label: 'Глобальная база',
      icon: <IconDatabase size={16} />,
      hint: 'Документы базы знаний',
      onSelect: () => navigate('/admin/documents'),
    },
    {
      label: 'Задачи',
      icon: <IconListCheck size={16} />,
      hint: 'Фоновые задачи и индексация',
      onSelect: () => navigate('/admin/tasks'),
    },
    {
      label: 'Сессии',
      icon: <IconLayoutDashboard size={16} />,
      hint: 'Активные и архивные сессии',
      onSelect: () => navigate('/admin/sessions'),
    },
    {
      label: 'Аудит',
      icon: <IconFileAnalytics size={16} />,
      hint: 'Журнал действий администраторов',
      onSelect: () => navigate('/admin/audit'),
    },
    {
      label: 'Обслуживание',
      icon: <IconAdjustments size={16} />,
      hint: 'Бэкапы и сброс состояния',
      onSelect: () => navigate('/admin/maintenance'),
    },
    ...(user?.role === 'admin'
      ? [
          {
            label: 'Создать пользователя',
            icon: <IconPlus size={16} />,
            hint: 'Новая учётная запись',
            onSelect: () => navigate('/admin/users'),
          },
        ]
      : []),
  ]

  return (
    <Spotlight
      opened={opened}
      onClose={() => setOpened(false)}
      closeOnBlur={false}
      withinPortal
      withOverlay
      zIndex={1000}
    >
      <SpotlightRoot>
        <Group gap="xs" align="center" style={{ width: '100%' }}>
          <IconSearch size={16} color="dimmed" />
          <SpotlightSearch
            placeholder="Поиск по разделам, сессиям, действиям…"
            icon={<Box />}
            withinPortal
          />
        </Group>
        <SpotlightActionsGroup>
          <SpotlightActionsList>
            {items.map((item) => (
              <SpotlightAction
                key={item.label}
                icon={item.icon}
                onSelect={() => {
                  setOpened(false)
                  item.onSelect()
                }}
              >
                <Box>
                  <Text weight={500}>{item.label}</Text>
                  {item.hint && <Text size="xs" c="dimmed">{item.hint}</Text>}
                </Box>
              </SpotlightAction>
            ))}
            {items.length === 0 && (
              <SpotlightEmpty>
                <Text c="dimmed">Ничего не найдено</Text>
              </SpotlightEmpty>
            )}
          </SpotlightActionsList>
        </SpotlightActionsGroup>
      </SpotlightRoot>
    </Spotlight>
  )
}
