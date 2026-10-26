/**
 * Command palette (Ctrl/Cmd+K) на @mantine/spotlight.
 *
 * План Волны 2, п. 3: разделы, недавние сессии, действия. Spotlight даёт
 * из коробки навигацию стрелками, Enter, Esc, aria-роли и подсказку
 * «ничего не найдено» — самодельный Modal их не давал.
 *
 * Открытие: Ctrl/Cmd+K глобально или кнопка в шапке (`spotlight.open()`).
 */

import {
  Spotlight,
  createSpotlight,
  type SpotlightActionData,
} from '@mantine/spotlight'
import {
  IconDashboard,
  IconBook,
  IconSearch,
  IconSettings,
  IconBrain,
  IconUpload,
} from '@tabler/icons-react'
import { useMemo } from 'react'
import { useNavigate } from 'react-router-dom'

import { useAuth } from '../auth/authStore'
import { useSessions } from '../dashboard/queries'

// store общий для палитры и триггера в шапке.
const [store, spotlight] = createSpotlight()

/** Программное открытие из шапки и других мест. */
export function openCommandPalette(): void {
  spotlight.open()
}

export function CommandPalette() {
  const navigate = useNavigate()
  const user = useAuth((state) => state.user)
  const sessions = useSessions()

  // Недавние сессии (первые 5) — не дропдаун, а поиск: распределены по
  // группам, чтобы «Действия» не терялись за списком сессий.
  const recentSessions: SpotlightActionData[] = useMemo(
    () =>
      (sessions.data ?? []).slice(0, 5).map((session) => ({
        id: `session-${session.id}`,
        group: 'Недавние сессии',
        title: session.title || 'Без названия',
        description: 'Открыть сессию',
        leftSection: <IconBrain size={18} stroke={1.5} />,
        keywords: ['сессия', 'чат'],
        onClick: () => navigate(`/s/${session.id}/chat`),
      })),
    [sessions.data, navigate],
  )

  const sections: SpotlightActionData[] = useMemo(() => {
    const items: SpotlightActionData[] = [
      {
        id: 'dashboard',
        group: 'Разделы',
        title: 'Информационная панель',
        description: 'Сессии и задачи',
        leftSection: <IconDashboard size={18} stroke={1.5} />,
        onClick: () => navigate('/'),
      },
      {
        id: 'knowledge',
        group: 'Разделы',
        title: 'База знаний',
        description: 'Общий корпус документов',
        leftSection: <IconBook size={18} stroke={1.5} />,
        keywords: ['база', 'документы', 'корпус'],
        onClick: () => navigate('/knowledge'),
      },
    ]
    if (user?.role === 'admin') {
      items.push({
        id: 'admin',
        group: 'Разделы',
        title: 'Администрирование',
        description: 'Пользователи, база, обслуживание',
        leftSection: <IconSettings size={18} stroke={1.5} />,
        keywords: ['админ', 'пользователи'],
        onClick: () => navigate('/admin'),
      })
    }
    return items
  }, [navigate, user?.role])

  const actions: SpotlightActionData[] = useMemo(() => {
    // Админ грузит документ через admin/base, остальным — чтение базы:
    // наполняет только админ (см. KnowledgePage).
    const uploadTo = user?.role === 'admin' ? '/admin/base' : '/knowledge'
    return [
      {
        id: 'new-question',
        group: 'Действия',
        title: 'Новый вопрос',
        description: 'Композер быстрого вопроса на панели',
        leftSection: <IconSearch size={18} stroke={1.5} />,
        keywords: ['вопрос', 'спросить', 'чат'],
        onClick: () => navigate('/'),
      },
      {
        id: 'upload-document',
        group: 'Действия',
        title: 'Загрузить документ',
        description:
          user?.role === 'admin' ? 'Глобальная база — загрузка' : 'Список базы знаний',
        leftSection: <IconUpload size={18} stroke={1.5} />,
        keywords: ['загрузить', 'файл', 'документ'],
        onClick: () => navigate(uploadTo),
      },
    ]
  }, [navigate, user?.role])

  return (
    <Spotlight
      store={store}
      shortcut={['mod + K', 'ctrl + K']}
      searchProps={{
        placeholder: 'Поиск: раздел, сессия, действие…',
        leftSection: <IconSearch size={18} stroke={1.5} />,
      }}
      limit={12}
      clearQueryOnClose
      nothingFound="Ничего не найдено"
      actions={[...sections, ...actions, ...recentSessions]}
    />
  )
}
