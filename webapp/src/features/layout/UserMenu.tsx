/**
 * Меню пользователя в тонкой шапке (план Волны 2, п. 2): имя, роль, выход.
 *
 * Выход — настоящий: раньше кнопка «Выйти» только перебрасывала на /login,
 * а токены и состояние auth-store оставались — «вход» под другим
 * пользователем восстанавливал старую сессию.
 *
 * Переключатель темы живёт в сайдбаре (ThemeSwitch) — дублировать его
 * в шапке нечего: два одинаковых контрола на одном экране — шум.
 */

import { Avatar, Box, Button, Menu } from '@mantine/core'
import { IconLogout, IconUserCircle } from '@tabler/icons-react'
import { useNavigate } from 'react-router-dom'

import { useAuth } from '../../features/auth/authStore'
import { displayName, roleLabel } from '../../lib/roles'

export function UserMenu() {
  const { user, logout } = useAuth()
  const navigate = useNavigate()

  return (
    <Menu withinPortal position="bottom-end" shadow="md">
      <Menu.Target>
        <Button
          variant="subtle"
          size="compact-sm"
          px={6}
          aria-label="Меню пользователя"
          leftSection={
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
            <Menu.Item leftSection={<IconUserCircle size={16} stroke={1.5} />} disabled>
              Аккаунт
            </Menu.Item>
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
