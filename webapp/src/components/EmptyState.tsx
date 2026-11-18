/**
 * Пустое состояние с действием — альтернатива голому тексту "Нет данных".
 * Аналог пустых состояний в v0.app: иконка + заголовок + описание + кнопка действия.
 */

import { Box, Group, Stack, Text } from '@mantine/core'
import { IconDatabase } from '@tabler/icons-react'

interface EmptyStateProps {
  title: string
  description?: string
  action?: React.ReactNode
  icon?: React.ReactNode
}

export function EmptyState({ title, description, action, icon }: EmptyStateProps) {
  return (
    <Stack align="center" p="xl" style={{ textAlign: 'center' }}>
      <Box
        style={{
          width: 64,
          height: 64,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
        }}
      >
        {icon || <IconDatabase size={32} />}
      </Box>
      <Text size="lg" fw={500}>
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
