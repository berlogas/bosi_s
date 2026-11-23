/**
 * Компонент для отображения дерева версий раздела.
 */

import { IconChevronRight, IconChevronDown, IconFileText } from '@tabler/icons-react'
import type { VersionTree, VersionNode } from '../../../api/types'
import { formatDistanceToNow } from 'date-fns'
import { Stack, Group, Text, Badge, UnstyledButton, Button, Box } from '@mantine/core'
import { ru } from 'date-fns/locale'

interface VersionTreeProps {
  tree: VersionTree
  onSelectVersion: (versionId: string) => void
  selectedVersionId: string | null
  canRollback?: boolean
  onRollback?: (versionId: string) => void
  canApprove?: boolean
  onApprove?: (versionId: string) => void
}

function VersionNodeItem({
  node,
  depth = 0,
  onSelectVersion,
  selectedVersionId,
  canRollback,
  onRollback,
  canApprove,
  onApprove,
}: {
  node: VersionNode
  depth?: number
  onSelectVersion: (versionId: string) => void
  selectedVersionId: string | null
  canRollback?: boolean
  onRollback?: (versionId: string) => void
  canApprove?: boolean
  onApprove?: (versionId: string) => void
}) {
  const version = node.version
  const isSelected = version.id === selectedVersionId
  const hasChildren = node.children.length > 0

  const statusColors: Record<string, string> = {
    draft: 'blue',
    review: 'yellow',
    approved: 'green',
    superseded: 'gray',
    archived: 'dark',
  }

  const statusLabels: Record<string, string> = {
    draft: 'Черновик',
    review: 'На ревью',
    approved: 'Одобрен',
    superseded: 'Заменён',
    archived: 'Архив',
  }

  return (
    <Stack gap="xs" style={{ marginLeft: depth * 24 }}>
      <Group
        align="center"
        style={{
          backgroundColor: isSelected
            ? 'var(--mantine-color-blue-light)'
            : 'transparent',
          borderRadius: 4,
          padding: '4px 8px',
          cursor: 'pointer',
          transition: 'background-color 0.15s',
        }}
        onClick={() => onSelectVersion(version.id)}
      >
        {hasChildren && (
          <UnstyledButton
            size={16}
            p={0}
            onClick={(e) => {
              e.stopPropagation()
            }}
            aria-label="Toggle"
          >
            {node.children.length > 0 ? (
              <IconChevronDown size={14} />
            ) : (
              <IconChevronRight size={14} />
            )}
          </UnstyledButton>
        )}
        <IconFileText size={14} color={isSelected ? 'blue' : 'gray'} />
        <Text size="sm" fw={isSelected ? 600 : 400} style={{ flex: 1 }}>
          {version.language.toUpperCase()}
          {version.source_language && ` (из ${version.source_language})`}
        </Text>
        <Badge variant="light" color={statusColors[version.status] || 'gray'} size="sm">
          {statusLabels[version.status] || version.status}
        </Badge>
        <Text size="xs" c="dimmed">
          {formatDistanceToNow(new Date(version.created_at), {
            addSuffix: true,
            locale: ru,
          })}
        </Text>
        <Text size="xs" c="dimmed">
          {version.word_count} слов
        </Text>
        {version.cost_usd !== null && version.cost_usd !== undefined && (
          <Text size="xs" c="dimmed">
            ${version.cost_usd.toFixed(4)}
          </Text>
        )}
      </Group>
      {hasChildren && (
        <Stack gap="xs">
          {node.children.map((child) => (
            <VersionNodeItem
              key={child.version.id}
              node={child}
              depth={depth + 1}
              onSelectVersion={onSelectVersion}
              selectedVersionId={selectedVersionId}
              canRollback={canRollback}
              onRollback={onRollback}
              canApprove={canApprove}
              onApprove={onApprove}
            />
          ))}
        </Stack>
      )}
      {isSelected && (onRollback || onApprove) && (
        <Group gap="xs" mt={4}>
          {onRollback && (
            <Button
              size="compact-xs"
              variant="default"
              disabled={!canRollback}
              onClick={(event) => {
                event.stopPropagation()
                onRollback(version.id)
              }}
            >
              Откатить к этой версии
            </Button>
          )}
          {onApprove && (
            <Button
              size="compact-xs"
              variant="light"
              color="green"
              disabled={!canApprove}
              onClick={(event) => {
                event.stopPropagation()
                onApprove(version.id)
              }}
            >
              Одобрить
            </Button>
          )}
        </Group>
      )}
    </Stack>
  )
}

export function VersionTreeView({
  tree,
  onSelectVersion,
  selectedVersionId,
  canRollback,
  onRollback,
  canApprove,
  onApprove,
}: VersionTreeProps) {
  return (
    <Box p="md" style={{ maxHeight: 500, overflow: 'auto' }}>
      <Stack gap="md">
        <Group justify="space-between" align="center">
          <Text fw={600}>История версий: {tree.section_name}</Text>
          <Text size="xs" c="dimmed">
            Всего версий: {tree.all_versions.length}
          </Text>
        </Group>
        {tree.roots.map((root) => (
          <VersionNodeItem
            key={root.version.id}
            node={root}
            onSelectVersion={onSelectVersion}
            selectedVersionId={selectedVersionId}
            canRollback={canRollback}
            onRollback={onRollback}
            canApprove={canApprove}
            onApprove={onApprove}
          />
        ))}
        {tree.roots.length === 0 && (
          <Text size="sm" c="dimmed" ta="center" py="xl">
            Нет версий для этого раздела
          </Text>
        )}
      </Stack>
    </Box>
  )
}
