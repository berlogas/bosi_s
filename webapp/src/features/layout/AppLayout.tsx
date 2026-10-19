/**
 * Боковая панель и общий layout — паритет `sidebar()` из Streamlit-версии app.py.
 *
 * Подписей «Навигация» и метки сборки в подвале нет: пунктов и так видно, по
 * одному взгляду, а «Навигация» над списком ссылок и дата сборки в углу —
 * шум, который занимает место и ничего не сообщает пользователю.
 */

import {
  AppShell,
  AppShellNavbar,
  Badge,
  Button,
  Center,
  Divider,
  Group,
  Loader,
  NavLink,
  ScrollArea,
  Stack,
  Text,
  Title,
} from '@mantine/core'
import { Suspense } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Outlet, useLocation, useNavigate } from 'react-router-dom'

import { client } from '../../api/client'
import { displayName, roleLabel } from '../../lib/roles'
import { useAuth } from '../auth/authStore'
import { useCurrentSessionPath } from '../sessions/useCurrentSession'

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

  // Текущая сессия — не из адресной строки, а последняя открытая: стоило уйти
  // в меню, пункт серел, хотя сессия никуда не делась, и вернуться можно было
  // только через дашборд. Хранится в sessionStorage (useCurrentSession).
  const currentSessionPath = useCurrentSessionPath()

  const items = [
    { to: '/', label: 'Информационная панель', enabled: true },
    // Глобальная база на чтение — всем вошедшим, включая исследователя:
    // наполняет её администратор, но видеть состав корпуса нужно каждому,
    // иначе ссылки в ответах ведут в никуда.
    { to: '/knowledge', label: 'База знаний', enabled: true },
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
        <Group gap="xs" mb="xs" justify="space-between">
          <Title order={4}>📚 boasi_s</Title>
          {bootPending && <Loader size="xs" />}
        </Group>

        {!user ? (
          <Text size="sm" c="dimmed">
            Войдите, чтобы начать работу.
          </Text>
        ) : (
          <>
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
              👤 {displayName(user)} · {roleLabel(user.role)}
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
      </AppShellNavbar>

      <AppShell.Main>
        {/* Страницы под Suspense: будущий code-split (React.lazy) и
            любые транзиентные suspends не должны ронять layout */}
        <Suspense
          fallback={
            <Center mih="40vh">
              <Loader />
            </Center>
          }
        >
          <Outlet />
        </Suspense>
      </AppShell.Main>
    </AppShell>
  )
}
