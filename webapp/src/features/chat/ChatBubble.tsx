/**
 * Пузырь чата — паритет `ui.chat_bubble` (Streamlit).
 *
 * Аватар, подпись и кнопка действия — в одной строке (у Streamlit это
 * были три колонки; кнопка «🗑» стоит на вопросе, потому что удаляет
 * всю пару «вопрос + ответ»).
 */

import { Avatar, Box, Group, Paper, Text } from '@mantine/core'
import type { ReactNode } from 'react'

export type ChatRole = 'user' | 'assistant'

export function ChatBubble({
  role,
  action,
  children,
}: {
  role: ChatRole
  /** Действие в шапке пузыря (например, «🗑» — удалить пару). */
  action?: ReactNode
  children: ReactNode
}) {
  const isUser = role === 'user'
  return (
    <Paper
      withBorder
      p="sm"
      bg={isUser ? 'gray.0' : undefined}
      data-testid="chat-bubble"
    >
      <Group gap="xs" align="center" wrap="nowrap">
        <Avatar size="sm" radius="xl" color={isUser ? 'green' : 'blue'}>
          {isUser ? '👨‍🔬' : '👨‍💻'}
        </Avatar>
        <Text size="sm" fw={700} style={{ flex: 1 }}>
          {isUser ? 'Вы' : 'Бо'}
        </Text>
        {action}
      </Group>
      <Box mt={4}>{children}</Box>
    </Paper>
  )
}
