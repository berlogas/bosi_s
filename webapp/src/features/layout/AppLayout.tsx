/**
 * Боковая панель и общий layout — десктопная версия.
 * Единый header, навигация через menuConfig.ts + NavSection.tsx.
 */

import {
  ActionIcon,
  AppShell,
  AppShellHeader,
  AppShellNavbar,
  Badge,
  Box,
  Button,
  Center,
  Divider,
  Group,
  Stack,
  Text,
  Title,
  useMantineColorScheme,
} from '@mantine/core'
import {
  IconBook,
  IconMoonStars,
  IconSearch,
  IconSun,
  IconUser,
} from '@tabler/icons-react'
import { Suspense } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Outlet } from 'react-router-dom'

import { client } from '../../api/client'
import { RouteErrorBoundary } from '../../components/RouteErrorBoundary'
import { displayName, roleLabel } from '../../lib/roles'
import { useAuth } from '../auth/authStore'
import { useCurrentSessionPath } from '../sessions/useCurrentSession'
import { TaskEventsProvider } from '../tasks/TaskEventsProvider'
import { LeftPanelUserMenu } from './LeftPanelUserMenu'
import { TaskIndicator } from './TaskIndicator'
import { CommandPalette, openCommandPalette } from '../../components/CommandPalette'
import { SkeletonList } from '../../components/SkeletonList'
import { Kbd } from '@mantine/core'
import { getMenuSections, isItemActive as isNavItemActive } from './menuConfig'
import { NavSection } from './NavSection'

// Реэкспорт для совместимости с тестами
export { isNavItemActive }

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
      <Text size="xs" c="error">
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
 * Десктопный header.
 */
function DesktopHeader({ bootPending }: { bootPending: boolean }) {
  const { colorScheme, setColorScheme } = useMantineColorScheme()

  const toggleTheme = () => {
    setColorScheme(colorScheme === 'dark' ? 'light' : 'dark')
  }

  const isDark = colorScheme === 'dark'

  return (
    <AppShellHeader
      h={56}
      px="md"
      style={{
        borderBottom: `1px solid var(--mantine-color-default-border)`,
        display: 'flex',
        alignItems: 'center',
      }}
    >
      <Group gap="sm" justify="space-between" w="100%" style={{ alignItems: 'center' }}>
        <Group gap="sm">
          <Title
            order={4}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 'var(--mantine-spacing-sm)',
            }}
          >
            <IconBook size={16} stroke={1.5} />
            <span>boasi_s</span>
          </Title>
        </Group>

        <Group gap="sm" style={{ marginLeft: 'auto' }}>
          {bootPending && <SkeletonList count={1} />}
          {/* Триггер палитры: Ctrl/Cmd+K */}
          <Button
            variant="default"
            size="compact-sm"
            leftSection={<IconSearch size={14} stroke={1.5} />}
            onClick={openCommandPalette}
            aria-label="Поиск по разделам и сессиям (Ctrl+K)"
          >
            <Group gap={6} wrap="nowrap">
              <span>Поиск</span>
              <Group gap={4} wrap="nowrap">
                <Kbd size="xs">Ctrl</Kbd>
                <Kbd size="xs">K</Kbd>
              </Group>
            </Group>
          </Button>

          {/* Индикатор активных задач — виден с любой страницы */}
          <TaskIndicator />

          <ActionIcon
            size="sm"
            variant="light"
            color={isDark ? 'gray' : 'yellow'}
            aria-label={`Текущая тема: ${colorScheme}. Нажмите для смены.`}
            onClick={toggleTheme}
            title={`Тема: ${colorScheme}. Клик — сменить.`}
          >
            {isDark ? (
              <IconSun size={16} stroke={1.5} />
            ) : (
              <IconMoonStars size={16} stroke={1.5} />
            )}
          </ActionIcon>
        </Group>
      </Group>
    </AppShellHeader>
  )
}

export function AppLayout() {
  const { user } = useAuth()
  const bootPending = useAuth((state) => state.status === 'boot')
  // Путь текущей сессии — из хука, а не из хранилища: пункт меню должен
  // реагировать на смену сессии, а не читать его один раз при отрисовке.
  const currentSessionPath = useCurrentSessionPath()

  const sections = getMenuSections(user, currentSessionPath)

  return (
    <TaskEventsProvider>
      <AppShell
        style={{ height: '100%' }}
        header={{ height: 56 }}
        navbar={{ width: 260, breakpoint: 'xs' }}
        padding="md"
      >
        {/* Десктопный header */}
        <DesktopHeader bootPending={bootPending} />

        <AppShellNavbar id="main-nav" p="md">
          <Box style={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
            <Group gap="xs" mb="xs" justify="space-between">
              {bootPending && <SkeletonList count={1} />}
            </Group>

            {/* Навигационные ссылки — скроллируемая область */}
            <Stack gap={2} style={{ flex: 1, overflowY: 'auto', minHeight: 0 }}>
              {!user ? (
                <Text size="sm" c="dimmed">
                  Войдите, чтобы начать работу.
                </Text>
              ) : (
                sections.map((section) => (
                  <NavSection key={section.id} section={section} user={user} />
                ))
              )}
            </Stack>

            {/* Пользователь и выход — закреплены в самом низу панели */}
            <Box style={{ marginTop: 'auto' }}>
              <Box>
                <Text size="xs" c="dimmed" mb={4}>
                  Состояние системы
                </Text>
                <SystemStatus />
              </Box>

              <Divider my="md" />

              <Text
                size="xs"
                c="dimmed"
                mb={4}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 'var(--mantine-spacing-xs)',
                }}
              >
                <IconUser size={16} stroke={1.5} />
                <span>
                  {user ? displayName(user) : 'Профиль'}
                  {user ? ` · ${roleLabel(user.role)}` : ''}
                </span>
              </Text>
              <LeftPanelUserMenu />
            </Box>
          </Box>
        </AppShellNavbar>

        <AppShell.Main>
          <Suspense
            fallback={
              <Center mih="40vh">
                <SkeletonList count={3} />
              </Center>
            }
          >
            <RouteErrorBoundary>
              <Outlet />
            </RouteErrorBoundary>
          </Suspense>
        </AppShell.Main>
      </AppShell>
      <CommandPalette />
    </TaskEventsProvider>
  )
}
