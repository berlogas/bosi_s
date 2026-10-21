/**
 * Боковая панель и общий layout — паритет `sidebar()` из Streamlit-версии app.py.
 *
 * Подписей «Навигация» и метки сборки в подвале нет: пунктов и так видно, по
 * одному взгляду, а «Навигация» над списком ссылок и дата сборки в углу —
 * шум, который занимает место и ничего не сообщает пользователю.
 */

import {
  AppShell,
  AppShellHeader,
  AppShellNavbar,
  Badge,
  Box,
  Burger,
  Button,
  Center,
  Divider,
  Group,
  Loader,
  NavLink,
  Popover,
  ScrollArea,
  Stack,
  Text,
  Title,
} from '@mantine/core'
import { Suspense, useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Outlet, useLocation, useNavigate } from 'react-router-dom'

import { client } from '../../api/client'
import { RouteErrorBoundary } from '../../components/RouteErrorBoundary'
import { displayName, roleLabel } from '../../lib/roles'
import { useAuth } from '../auth/authStore'
import { useCurrentSessionPath } from '../sessions/useCurrentSession'
import { TaskEventsProvider } from '../tasks/TaskEventsProvider'

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
      <Group gap={4}>
        <Text size="xs">API:</Text>
        <Badge size="xs">{data.status}</Badge>
      </Group>
      <Text size="xs">Модель: {data.llm_model}</Text>
      <Text size="xs">Эмбеддинги: {data.embedding_model}</Text>
      <Group gap={4}>
        <Text size="xs">Ollama:</Text>
        <Badge size="xs" color={ollama?.reachable ? 'green' : 'red'}>
          {ollama?.reachable ? 'доступен' : 'недоступен'}
        </Badge>
      </Group>
    </Stack>
  )
}

/**
 * Активен ли пункт меню для текущего адреса.
 *
 * Подпути включают пункт (`/s/<id>/chat` → «Текущая сессия»), но `/` — только
 * сам корень: иначе панель была бы активна на всех страницах.
 */
export function isNavItemActive(pathname: string, to: string): boolean {
  if (to === '/') return pathname === '/'
  return pathname === to || pathname.startsWith(`${to}/`)
}

export function AppLayout() {
  const { user, logout } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  // Крутилка в подвале сайдбара, пока идёт восстановление сессии после F5.
  const bootPending = useAuth((state) => state.status === 'boot')
  // Мобильный drawer: на узком экране сайдбар скрыт, Burger — в шапке.
  const [navOpened, setNavOpened] = useState(false)

  // Переход закрывает drawer, иначе он накрывает только что открытый раздел.
  useEffect(() => {
    setNavOpened(false)
  }, [location.pathname])

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
    <TaskEventsProvider>
      <AppShell
        // На desktop шапка не нужна: высота 0 и сама шапка скрыта, чтобы не
        // отнимать 56px у рабочей области.
        header={{ height: { base: 56, sm: 0 } }}
        navbar={{
          width: 260,
          breakpoint: 'sm',
          collapsed: { mobile: !navOpened },
        }}
        padding="md"
      >
        <AppShellHeader hiddenFrom="sm">
          <Group h="100%" px="md" gap="sm">
            <Burger
              opened={navOpened}
              onClick={() => setNavOpened((value) => !value)}
              aria-label="Меню"
              aria-expanded={navOpened}
              aria-controls="main-nav"
            />
            <Title order={4}>📚 boasi_s</Title>
            {bootPending && <Loader size="xs" />}
          </Group>
        </AppShellHeader>

        <AppShellNavbar id="main-nav" p="md" component={ScrollArea}>
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
                {items.map((item) => {
                  // Подпути: `/s/<id>/chat`, `/s/<id>/documents`, ... Строгое
                  // равенство гасило «Текущую сессию» на всех вкладках, кроме
                  // корневой. Для `/` равенство остаётся строгим, иначе панель
                  // была бы активна везде.
                  const active =
                    item.enabled && isNavItemActive(location.pathname, item.to)
                  return (
                    <NavLink
                      key={item.label}
                      label={item.label}
                      disabled={!item.enabled}
                      active={active}
                      aria-current={active ? 'page' : undefined}
                      onClick={() => {
                        if (!item.enabled) return
                        setNavOpened(false)
                        navigate(item.to)
                      }}
                    />
                  )
                })}
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
              {/* На телефоне подробности не должны занимать пол-экрана:
                свёрнуты в поповер, на desktop — как раньше. */}
              <Box visibleFrom="sm">
                <Text size="xs" c="dimmed" mb={4}>
                  Состояние системы
                </Text>
                <SystemStatus />
              </Box>
              <Popover position="top" withArrow>
                <Popover.Target>
                  <Button hiddenFrom="sm" variant="subtle" size="xs" fullWidth>
                    Состояние системы
                  </Button>
                </Popover.Target>
                <Popover.Dropdown>
                  <SystemStatus />
                </Popover.Dropdown>
              </Popover>
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
            <RouteErrorBoundary>
              <Outlet />
            </RouteErrorBoundary>
          </Suspense>
        </AppShell.Main>
      </AppShell>
    </TaskEventsProvider>
  )
}
