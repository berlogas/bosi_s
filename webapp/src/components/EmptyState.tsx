/**
 * Пустое состояние с действием — альтернатива голому тексту "Нет данных".
 * Аналог пустых состояний в v0.app: иконка + заголовок + описание + кнопка действия.
 */

import { Box, Button, Group, Stack, Text } from '@mantine/core'
import {
  IconArchive,
  IconDatabase,
  IconFilePlus,
  IconUsers,
  IconLayoutDashboard,
  IconFileAnalytics,
  IconAdjustments,
} from '@tabler/icons-react'

interface EmptyStateProps {
  title: string
  description?: string
  action?: React.ReactNode
  icon?: React.ReactNode
}

export function EmptyState({ title, description, action, icon }: EmptyStateProps) {
  const defaultIcons: Record<string, React.ReactNode> = {
    users: <IconUsers size={32} />,
    documents: <IconDatabase size={32} />,
    sessions: <IconLayoutDashboard size={32} />,
    audit: <IconFileAnalytics size={32} />,
    maintenance: <IconAdjustments size={32} />,
    backups: <IconArchive size={32} />,
    upload: <IconFilePlus size={32} />,
  }

  return (
    <Stack align="center" p="xl" textAlign="center">
      <Box sx={{ width: 64, height: 64, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        {icon || <IconDatabase size={32} />}
      </Box>
      <Text size="lg" weight={500}>
        {title}
      </Text>
      {description && <Text size="sm" c="dimmed" mt="xs">{description}</Text>}
      {action && (
        <Group mt="md" justify="center">
          {action}
        </Group>
      )}
    </Stack>
  )
}
