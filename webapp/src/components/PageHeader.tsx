/**
 * Единый заголовок страницы — заменяет разрозненные `Title` + `Text` на
 * каждой странице. Рендерит заголовок, опциональное описание и действия
 * справа в одной строке.
 */

import { Group, Stack, Text, Title } from '@mantine/core'

export interface PageHeaderProps {
  /** Заголовок страницы (h2 по умолчанию). */
  title: React.ReactNode
  /** Краткое описание под заголовком. */
  description?: React.ReactNode
  /** Действия справа от заголовка (кнопки, селекты и т. п.). */
  actions?: React.ReactNode
  /** Уровень заголовка (по умолчанию 3). */
  order?: 1 | 2 | 3 | 4 | 5 | 6
}

export function PageHeader({
  title,
  description,
  actions,
  order = 3,
}: PageHeaderProps) {
  return (
    <Group justify="space-between" align="center" wrap="wrap" mb="md">
      <Stack gap="xs">
        <Title order={order}>{title}</Title>
        {description && (
          <Text size="sm" c="dimmed">
            {description}
          </Text>
        )}
      </Stack>
      {actions && <Group gap="sm">{actions}</Group>}
    </Group>
  )
}
