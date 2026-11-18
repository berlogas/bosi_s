import { Paper, Group, Stack, Text, Select, Button } from '@mantine/core'
import { IconGripVertical, IconClock, IconPencil, IconEye, IconCheck, IconTrash } from '@tabler/icons-react'
import { useSortable } from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import React from 'react'
import { projectStatusOptions, STATUSES } from '../../../lib/projectOptions'
import type { ProjectOut } from '../../../api/types'

interface SortableProjectItemProps {
  project: ProjectOut
  isActive: boolean
  onSelect: () => void
  onStatusChange: (value: string) => void
  onDelete: () => void
  readOnly?: boolean
}

export function SortableProjectItem({
  project,
  isActive,
  onSelect,
  onStatusChange,
  onDelete,
  readOnly = false,
}: SortableProjectItemProps) {
  const {
    attributes,
    listeners,
    setNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({ id: project.id })

  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.5 : 1,
  }

  const statusIcons: Record<string, React.ReactNode> = {
    planning: <IconClock size={14} />,
    drafting: <IconPencil size={14} />,
    reviewing: <IconEye size={14} />,
    done: <IconCheck size={14} />,
  }

  return (
    <Paper
      ref={setNodeRef}
      key={project.id}
      withBorder
      radius="xs"
      p="xs"
      style={{
        ...style,
        cursor: 'grab',
        border: isActive
          ? `1px solid var(--mantine-color-primary-filled)`
          : '1px solid var(--mantine-color-default-border)',
        background: isActive
          ? 'var(--mantine-color-primary-light)'
          : 'var(--mantine-color-body)',
        transition: 'border 0.15s, background 0.15s',
        overflow: 'hidden',
        display: 'flex',
        alignItems: 'center',
        minHeight: 56,
      }}
      onClick={onSelect}
    >
      {/* Только ручка тянет карточку: иначе перетаскивание перехватывало бы
          клики по кнопкам внутри карточки. */}
      <IconGripVertical
        size={16}
        style={{ cursor: 'grabbing', marginRight: 8, color: 'var(--mantine-color-dimmed)' }}
        {...attributes}
        {...listeners}
      />
      <Group justify="space-between" align="center" wrap="nowrap" style={{ width: '100%', minWidth: 0 }}>
        <Stack gap={0} style={{ minWidth: 0, flex: 1 }}>
          <Text
            size="sm"
            fw={600}
            style={{
              whiteSpace: 'nowrap',
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              minWidth: 0,
            }}
          >
            {project.title}
          </Text>
        </Stack>
        {isActive && (
          <Group gap="xs" align="center" style={{ flexShrink: 0, marginLeft: 'auto' }}>
            <Text c="dimmed">{statusIcons[project.status]}</Text>
            <Select
              data={projectStatusOptions(STATUSES)}
              value={project.status}
              onChange={(value) => {
                if (!value) return
                onStatusChange(value)
              }}
              disabled={readOnly}
              allowDeselect={false}
              w={200}
              size="xs"
            />
            <Button
              color="error"
              variant="light"
              onClick={onDelete}
              disabled={readOnly}
              size="xs"
              leftSection={<IconTrash size={12} />}
            >
              Удалить
            </Button>
          </Group>
        )}
      </Group>
    </Paper>
  )
}