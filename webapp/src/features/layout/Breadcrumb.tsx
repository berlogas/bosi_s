/**
 * Хлебные крошки — только на странице сессии (план Волны 2, п. 5).
 *
 * Раньше это была статичная строка «Панель / Сессия / Чат» без ссылок:
 * путь «Панель → Сессия» реально существует, и переход по нему должен
 * работать. На остальных страницах иерархии нет — крошки не рендерим,
 * чтобы не дублировать PageHeader.
 *
 * Теперь поддерживает вложенный контекст: проект / раздел (для вкладки Проекты).
 */

import { Breadcrumbs, Group, Anchor, Text } from '@mantine/core'
import { Link } from 'react-router-dom'
import { useBreadcrumbContext } from './BreadcrumbContext'

import type { TabId } from '../sessions/tabPaths'

const TAB_LABELS: Record<TabId, string> = {
  documents: 'Документы',
  projects: 'Проекты',
  chat: 'Чат',
  notes: 'Заметки',
}

export function SessionBreadcrumb({
  sessionId,
  sessionTitle,
  activeTab,
}: {
  sessionId: string
  /** Заголовок сессии; пустой — «Без названия». */
  sessionTitle: string
  /** Текущая вкладка — крайний (некликабельный) элемент. */
  activeTab: TabId
}) {
  const { activeProjectTitle, activeSectionName } = useBreadcrumbContext()
  const isProjectsTab = activeTab === 'projects'

  return (
    <Group mb="xs">
      <Breadcrumbs separator="/" separatorMargin="xs" aria-label="Хлебные крошки">
        <Anchor component={Link} to="/" size="sm">
          Информационная панель
        </Anchor>
        <Anchor component={Link} to={`/s/${sessionId}/chat`} size="sm">
          {sessionTitle || 'Сессия'}
        </Anchor>
        <Anchor component={Link} to={`/s/${sessionId}/${activeTab}`} size="sm">
          {TAB_LABELS[activeTab]}
        </Anchor>
        {isProjectsTab && activeProjectTitle && (
          <Text size="sm" c="dimmed">
            {activeProjectTitle}
          </Text>
        )}
        {isProjectsTab && activeSectionName && (
          <Text size="sm" c="dimmed">
            {activeSectionName}
          </Text>
        )}
        {!isProjectsTab && (
          <Text size="sm" c="dimmed">
            {TAB_LABELS[activeTab]}
          </Text>
        )}
      </Breadcrumbs>
    </Group>
  )
}
