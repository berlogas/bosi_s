/**
 * Пустое состояние списка: заголовок, пояснение и действие.
 *
 * Раньше пустые списки заканчивались строкой «Документов пока нет.» — без
 * подсказки, что делать дальше. Действие необязательно: у некоторых экранов
 * форма уже стоит выше, и кнопка только дублировала бы её.
 */

import { Stack, Text } from '@mantine/core'
import type { ReactNode } from 'react'

export function EmptyState({
  title,
  description,
  action,
  icon,
}: {
  /** Короткий заголовок — обычно та же фраза, что была в текстовой заглушке. */
  title: ReactNode
  /** Пояснение: что сделать, чтобы список перестал быть пустым. */
  description?: ReactNode
  /** Кнопка или ссылка действия. */
  action?: ReactNode
  /** Декоративная иконка над заголовком. */
  icon?: ReactNode
}) {
  return (
    <Stack align="center" justify="center" gap="xs" py="xl">
      {icon}
      <Text size="sm" fw={600} ta="center">
        {title}
      </Text>
      {description && (
        <Text size="sm" c="dimmed" ta="center" maw={420}>
          {description}
        </Text>
      )}
      {action}
    </Stack>
  )
}
