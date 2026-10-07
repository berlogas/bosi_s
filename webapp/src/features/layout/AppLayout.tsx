/**
 * Боковая панель и общий layout — паритет `sidebar()` из frontend/app.py.
 *
 * Метка сборки обязательна: по ней видно, что браузер подхватил новый код,
 * а не закэшировал старый (та же роль, что UI_BUILD в Streamlit).
 */

import {
  AppShell,
  AppShellNavbar,
  Badge,
  Button,
  Divider,
  Group,
  Loader,
  NavLink,
  ScrollArea,
  Stack,
  Text,
  Title,
} from '@mantine/core'
import { useQuery } from '@tanstack/react-query'
import { Outlet, useLocation, useNavigate } from 'react-router-dom'

import { client } from '../../api/client'
import { useAuth } from '../auth/authStore'

/** Метка сборки интерфейса (аналог UI_BUILD в frontend/app.py). */
export const UI_BUILD = '2026-10-07a'

function SystemStatus() {
  const { data, error, isPending } = useQuery({
    queryKey: ['health'],
    queryFn: () => client.health(),
    refetchInterval: 30_000,
    retry: false,
  })

  if (isPending) return <Text size="xs">Проверяю состояние системы…</Text>
  if (error) {
    return (
      <Text size="xs" c="red">
        {error instanceof Error ? error.message : 'Состояние системы недоступно'}
      </Text>
    )
  }
  if (!data) return null

  const ollama = data.ollama as { reachable?: boolean } | undefined
  return (
    <Stack gap={2}>
      <Text size="xs">
        API: <Badge size="xs">{data.status}</Badge>
      </Text>
      <Text size="xs">Модель: {data.llm_model}</Text>
      <Text size="xs">Эмбеддинги: {data.embedding_model}</Text>
      <Text size="xs">
        Ollama:{' '}
        <Badge size="xs" color={ollama?.reachable ? 'green' : 'red'}>
          {ollama?.reachable ? 'доступен' : 'недоступен'}
        </Badge>
      </Text>
    </Stack>
  )
}

export function AppLayout() {
  const { user, logout } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  // Крутилка в подвале сайдбара, пока идёт восстановление сессии после F5.
  const bootPending = useAuth((state) => state.status === 'boot')

  // Текущая сессия: /s/:id в адресной строке — переживает F5 (в отличие
  // от session_state у Streamlit).
  const currentSessionMatch = /^\/s\/[^/]+/.exec(location.pathname)
  const currentSessionPath = currentSessionMatch ? currentSessionMatch[0] : null

  const items = [
    { to: '/', label: 'Дашборд', enabled: true },
    // «Текущая сессия» — та, что открыта сейчас (в Streamlit — state.current_session_id())
    {
      to: currentSessionPath ?? '',
      label: 'Текущая сессия',
      enabled: currentSessionPath !== null,
    },
    ...(user?.role === 'admin'
      ? [{ to: '/admin', label: 'Администрирование', enabled: true }]
      : []),
  ]

  return (
    <AppShell
      navbar={{ width: 260, breakpoint: 'sm', collapsed: { mobile: false } }}
      padding="md"
    >
      <AppShellNavbar p="md" component={ScrollArea}>
        <Title order={4} mb="xs">
          📚 boasi_s
        </Title>

        {!user ? (
          <Text size="sm" c="dimmed">
            Войдите, чтобы начать работу.
          </Text>
        ) : (
          <>
            <Text size="xs" tt="uppercase" c="dimmed" mb={4}>
              Навигация
            </Text>
            <Stack gap={2}>
              {items.map((item) => (
                <NavLink
                  key={item.label}
                  label={item.label}
                  disabled={!item.enabled}
                  active={item.enabled && location.pathname === item.to}
                  onClick={() => item.enabled && navigate(item.to)}
                />
              ))}
            </Stack>

            <Divider my="md" />

            <Text size="xs" c="dimmed" mb={4}>
              👤 {user.username} ({user.role})
            </Text>
            <Button
              variant="light"
              fullWidth
              onClick={() => {
                void logout().then(() => navigate('/login', { replace: true }))
              }}
            >
              Выйти
            </Button>

            <Divider my="md" />
            <Text size="xs" c="dimmed" mb={4}>
              Состояние системы
            </Text>
            <SystemStatus />
          </>
        )}

        <Divider my="md" />
        <Group gap="xs">
          <Text size="xs" c="dimmed">
            сборка {UI_BUILD}
          </Text>
          {bootPending && <Loader size="xs" />}
        </Group>
      </AppShellNavbar>

      <AppShell.Main>
        <Outlet />
      </AppShell.Main>
    </AppShell>
  )
}
