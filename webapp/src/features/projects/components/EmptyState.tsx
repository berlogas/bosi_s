import { Stack, Text, Paper, Button } from '@mantine/core'
import { IconFilePlus, IconFilePencil, IconPlus } from '@tabler/icons-react'

interface EmptyStateProps {
  icon: React.ReactNode
  title: string
  description: string
  actionLabel?: string
  onAction?: () => void
  minHeight?: number
}

export function EmptyState({
  icon,
  title,
  description,
  actionLabel,
  onAction,
  minHeight = 200,
}: EmptyStateProps) {
  return (
    <Paper withBorder p="xl" style={{ textAlign: 'center', minHeight }}>
      <Stack align="center" gap="sm" style={{ textAlign: 'center' }}>
        <div style={{ color: 'var(--mantine-color-primary-filled)' }}>{icon}</div>
        <Text fw={500}>{title}</Text>
        <Text size="sm" c="dimmed">
          {description}
        </Text>
        {actionLabel && onAction && (
          <Button onClick={onAction} leftSection={<IconPlus size={14} />}>
            {actionLabel}
          </Button>
        )}
      </Stack>
    </Paper>
  )
}

export function EmptyProjectsState({ onCreate }: { onCreate: () => void }) {
  return (
    <EmptyState
      icon={<IconFilePlus size={48} />}
      title="Проектов пока нет"
      description="Создайте первый проект статьи, чтобы начать работу с разделами, генерацией и экспортом."
      actionLabel="Создать проект"
      onAction={onCreate}
    />
  )
}

export function EmptySectionsState({ onGenerate }: { onGenerate?: () => void }) {
  return (
    <EmptyState
      icon={<IconFilePencil size={48} />}
      title="Разделов нет"
      description="Сгенерируйте разделы автоматически или создайте их вручную через настройки проекта."
      actionLabel={onGenerate ? 'Сгенерировать разделы' : undefined}
      onAction={onGenerate}
    />
  )
}
