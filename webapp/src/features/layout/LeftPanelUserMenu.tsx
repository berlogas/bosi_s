/**
 * Выдвигающееся меню пользователя в левой панели сайдбара.
 * Аналог UserMenu, но позиционирован для левого края и снизу.
 *
 * Поведение:
 * - При клике на аватара/имя открывается выпадающее меню вниз-лево
 * - Меню содержит: имя + роль, разделитель, пункт "Аккаунт" (disabled), Выйти
 * - Выход очищает auth и переходит на /login
 */
import { Avatar, Box, Button, Menu } from '@mantine/core'
import { IconLogout } from '@tabler/icons-react'
import { useNavigate } from 'react-router-dom'

import { useAuth } from '../auth/authStore'
import { displayName, roleLabel } from '../../lib/roles'

export function LeftPanelUserMenu() {
  const { user, logout } = useAuth()
  const navigate = useNavigate()

  return (
    <Menu withinPortal position="bottom-start" shadow="md">
      <Menu.Target>
        <Button
          variant="subtle"
          size="compact-sm"
          px={6}
          aria-label="Меню пользователя"
          rightSection={
            <Avatar
              size={24}
              color="primary"
              radius="xl"
              name={user ? displayName(user) : undefined}
            />
          }
        >
          <Box visibleFrom="md">{user ? displayName(user) : 'Профиль'}</Box>
        </Button>
      </Menu.Target>
      <Menu.Dropdown>
        {user && (
          <>
            <Menu.Label>
              {displayName(user)} · {roleLabel(user.role)}
            </Menu.Label>
            <Menu.Divider />
          </>
        )}
        <Menu.Item
          leftSection={<IconLogout size={16} stroke={1.5} />}
          onClick={() => {
            void logout().then(() => navigate('/login', { replace: true }))
          }}
        >
          Выйти
        </Menu.Item>
      </Menu.Dropdown>
    </Menu>
  )
}
