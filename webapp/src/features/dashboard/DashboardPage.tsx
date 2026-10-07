/**
 * Дашборд — заглушка Фазы 0.
 *
 * Приёмка этапа: «пустой дашборд после логина через новую обёртку».
 * Содержимое (сессии, быстрый чат, активные задачи) — Фаза 1.
 */

import { Alert, Card, Group, Stack, Text, Title } from '@mantine/core'

import { useAuth } from '../auth/authStore'

export function DashboardPage() {
  const user = useAuth((state) => state.user)

  return (
    <Stack>
      <Group justify="space-between">
        <Title order={3}>Дашборд</Title>
        {user && (
          <Text size="sm" c="dimmed">
            Здравствуйте, {user.username}!
          </Text>
        )}
      </Group>

      <Card withBorder>
        <Text size="sm" c="dimmed">
          Здесь будут сессии и быстрый чат по глобальной базе — Фаза 1.
        </Text>
      </Card>

      <Alert color="blue" title="Каркас (Фаза 0)">
        Рабочие экраны переносятся поэтапно: следом — авторизация, сессии и дашборд
        целиком.
      </Alert>
    </Stack>
  )
}
