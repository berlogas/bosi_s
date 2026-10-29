/**
 * Боковая панель и общий layout — паритет `sidebar()` из Streamlit-версии app.py.
 *
 * Подписей «Навигация» и метки сборки в подвале нет: пунктов и так видно, по
 * одному взгляду, а «Навигация» над списком ссылок и дата сборки в углу —
 * шум, который занимает место и ничего не сообщает пользователю.
 */

import {
  ActionIcon,
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
  NavLink,
  Popover,
  ScrollArea,
  Stack,
  Text,
  Title,
  useMantineColorScheme,
} from '@mantine/core'
import {
  IconBook,
  IconDeviceDesktop,
  IconMoonStars,
  IconSearch,
  IconSun,
  IconUser,
} from '@tabler/icons-react'
import { Suspense, useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link, Outlet, useLocation, useNavigate } from 'react-router-dom'

import { client } from '../../api/client'
import { RouteErrorBoundary } from '../../components/RouteErrorBoundary'
import { displayName, roleLabel } from '../../lib/roles'
import { useAuth } from '../auth/authStore'
import { useCurrentSessionPath } from '../sessions/useCurrentSession'
import { TaskEventsProvider } from '../tasks/TaskEventsProvider'
import { TaskIndicator } from './TaskIndicator'
import { UserMenu } from './UserMenu'
import { CommandPalette, openCommandPalette } from '../../components/CommandPalette'
import { SkeletonList } from '../../components/SkeletonList'
import { Kbd } from '@mantine/core'

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
 * Активен ли пункт меню для текущего адреса.
 *
 * Подпути включают пункт (`/s/<id>/chat` → «Текущая сессия»), но `/` — только
 * сам корень: иначе панель была бы активна на всех страницах.
 */
export function isNavItemActive(pathname: string, to: string): boolean {
  if (to === '/') return pathname === '/'
  return pathname === to || pathname.startsWith(`${to}/`)
}

/**
 * Переключатель темы: светлая / системная / тёмная.
 *
 * `setColorScheme('auto')` — «Системная»: тема следует за настройками ОС,
 * пока пользователь не выбрал явно. Менеджер провайдера
 * (localStorageColorSchemeManager) сохраняет выбор — тема живёт до F5,
 * а inline-скрипт в index.html применяет её до первого кадра, без вспышки.
 */
/**
 * Триггер палитры в шапке: на узких экранах — только иконка, на широких —
 * с подсказкой хоткея. Открывает того же Spotlight, что Ctrl/Cmd+K.
 */
function PaletteTrigger({ visibleFrom }: { visibleFrom?: string }) {
  return (
    <Button
      variant="default"
      size="compact-sm"
      visibleFrom={visibleFrom}
      leftSection={<IconSearch size={14} stroke={1.5} />}
      onClick={openCommandPalette}
      aria-label="Поиск по разделам и сессиям (Ctrl+K)"
    >
      <Group gap={6} wrap="nowrap">
        <span>Поиск</span>
        <Group visibleFrom="md" gap={4} wrap="nowrap">
          <Kbd size="xs">Ctrl</Kbd>
          <Kbd size="xs">K</Kbd>
        </Group>
      </Group>
    </Button>
  )
}

function ThemeIconToggle() {
  const { colorScheme, setColorScheme } = useMantineColorScheme()

  const toggle = () => {
    setColorScheme(colorScheme === 'dark' ? 'light' : 'dark')
  }

  const isDark = colorScheme === 'dark'

  return (
    <ActionIcon
      size="sm"
      variant="light"
      color={isDark ? 'gray' : 'yellow'}
      aria-label={`Текущая тема: ${colorScheme}. Нажмите для смены.`}
      onClick={toggle}
      title={`Тема: ${colorScheme}. Клик — сменить.`}
    >
      {isDark ? <IconSun size={16} stroke={1.5} /> : <IconMoonStars size={16} stroke={1.5} />}
    </ActionIcon>
  )
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
        // Тонкая шапка (48px) вмещает триггер палитры, индикатор задач и
        // меню пользователя — без неё глобальным элементам негде жить.
        header={{ height: { base: 56, sm: 48 } }}
        navbar={{
          width: 260,
          breakpoint: 'sm',
          collapsed: { mobile: !navOpened },
        }}
        padding="md"
      >
        <AppShellHeader hiddenFrom="sm">
          <Group h="100%" px="md" gap="sm" justify="space-between">
            <Group gap="sm">
              <Burger
                opened={navOpened}
                onClick={() => setNavOpened((value) => !value)}
                aria-label="Меню"
                aria-expanded={navOpened}
                aria-controls="main-nav"
              />
              <Title
                order={4}
                style={{ display: 'flex', alignItems: 'center', gap: 'var(--mantine-spacing-sm)' }}
              >
                <IconBook size={16} stroke={1.5} />
                <span>boasi_s</span>
              </Title>
            </Group>
            {bootPending && <SkeletonList count={1} />}
          </Group>
        </AppShellHeader>

        <AppShellHeader
          visibleFrom="sm"
          h={60}
          px="md"
          pt="md"
          style={{
            borderBottom: `1px solid var(--mantine-color-default-border)`,
          }}
        >
          <Group gap="sm" justify="space-between" w="100%">
            <Group gap="sm">
              <Title
                order={4}
                style={{ display: 'flex', alignItems: 'center', gap: 'var(--mantine-spacing-sm)' }}
              >
                <IconBook size={16} stroke={1.5} />
                <span>boasi_s</span>
              </Title>
              {/* Триггер палитры: Ctrl/Cmd+K тем, кто не в курсе хоткея */}
              <PaletteTrigger visibleFrom="xs" />
              {/* Индикатор активных задач — виден с любой страницы */}
              <TaskIndicator />
            </Group>
            <UserMenu />
          </Group>
        </AppShellHeader>

        <AppShellNavbar
          id="main-nav"
          p="md"
          style={{ display: 'flex', flexDirection: 'column', height: '100%' }}
        >
          <Group gap="xs" mb="xs" justify="space-between">
            {bootPending && <SkeletonList count={1} />}
          </Group>

          {/* Навигационные ссылки — забирают всё доступное место, скроллятся */}
          <Stack gap={2} style={{ flex: 1, overflowY: 'auto' }}>
            {!user ? (
              <Text size="sm" c="dimmed">
                Войдите, чтобы начать работу.
              </Text>
            ) : (
              <>
                {items.map((item) => {
                  // Подпути: `/s/<id>/chat`, `/s/<id>/documents`, ... Строгое
                  // равенство гасило «Текущую сессию» на всех вкладках, кроме
                  // корневой. Для `/` равенство остаётся строгим, иначе панель
                  // была бы активна везде.
                  const active =
                    item.enabled && isNavItemActive(location.pathname, item.to)

                  // Включённый пункт — настоящая ссылка: Mantine NavLink сам
                  // рендерит `<a>`, но без `href` он не фокусируется с
                  // клавиатуры и не даёт Ctrl-клик/«открыть в новой вкладке».
                  // Поэтому `component={Link}`: адрес настоящий, активность
                  // по-прежнему из предиката (`NavLink` из Mantine про роутер
                  // не знает). Выключенному пункту `to` не нужен — он остаётся
                  // неинтерактивным.
                  if (!item.enabled) {
                    return (
                      <NavLink
                        key={item.label}
                        label={item.label}
                        disabled
                        aria-current={undefined}
                      />
                    )
                  }
                  return (
                    <NavLink
                      key={item.label}
                      component={Link}
                      to={item.to}
                      label={item.label}
                      active={active}
                      aria-current={active ? 'page' : undefined}
                      onClick={() => setNavOpened(false)}
                    />
                  )
                })}
              </>
            )}
          </Stack>

          {/* Пользователь, тема и выход — закреплены в самом низу панели */}
          <Box style={{ marginTop: 'auto' }}>
            {/* Техническая информация о системе */}
            <Box visibleFrom="sm">
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
              style={{ display: 'flex', alignItems: 'center', gap: 'var(--mantine-spacing-xs)' }}
            >
              <IconUser size={16} stroke={1.5} />
              <span>
                {user ? displayName(user) : 'Профиль'}
                {user ? ` · ${roleLabel(user.role)}` : ''}
              </span>
            </Text>
            <ThemeIconToggle />
            <Button
              variant="light"
              fullWidth
              onClick={() => {
                void logout().then(() => navigate('/login', { replace: true }))
              }}
            >
              Выйти
            </Button>
          </Box>
        </AppShellNavbar>

        {/* На телефоне подробности не должны занимать пол-экрана:
          свёрнуты в поповер, на desktop — как раньше. */}
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

        <AppShell.Main>
          {/* Страницы под Suspense: будущий code-split (React.lazy) и
            любые транзиентные suspends не должны ронять layout */}
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
