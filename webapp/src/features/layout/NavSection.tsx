/**
 * Рендер секции меню с поддержкой вложенных пунктов и сворачивания.
 */

import { useState } from 'react'
import { NavLink, Divider, Stack, Box } from '@mantine/core'
import { Link, useLocation } from 'react-router-dom'
import { IconChevronDown } from '@tabler/icons-react'
import { isItemActive, isSectionActive, type MenuSection, type MenuItem } from './menuConfig'
import type { User } from '../auth/authStore'

interface NavSectionProps {
  section: MenuSection
  user: User | null
}

function NavItem({ item, currentPath, level = 0 }: { item: MenuItem; currentPath: string; level?: number }) {
  const to = item.to
  const active = isItemActive(currentPath, to)
  // disabled: enabled === false ИЛИ функция вернула false
  const disabled = item.enabled === false || (typeof item.enabled === 'function' && !item.enabled(null as any))
  const hasChildren = item.children && item.children.length > 0

  // Отступ для вложенных пунктов
  const indentStyle = level > 0 ? { paddingLeft: `${level * 16 + 8}px` } : {}

  if (hasChildren) {
    const [open, setOpen] = useState(true)
    const sectionActive = isSectionActive(currentPath, item.children!)

    return (
      <Box>
        <div
          onClick={() => setOpen(!open)}
          style={{
            ...indentStyle,
            display: 'flex',
            alignItems: 'center',
            gap: 'var(--mantine-spacing-xs)',
            padding: 'var(--mantine-spacing-xs) var(--mantine-spacing-sm)',
            borderRadius: 'var(--mantine-radius-sm)',
            cursor: 'pointer',
            color: sectionActive ? 'var(--mantine-color-primary-filled)' : 'var(--mantine-color-text)',
            backgroundColor: sectionActive ? 'var(--mantine-color-primary-light)' : 'transparent',
            fontWeight: sectionActive ? 500 : 400,
            fontSize: 'var(--mantine-font-size-sm)',
            userSelect: 'none',
          }}
          role="button"
          tabIndex={0}
          aria-expanded={open}
        >
          <IconChevronDown size={14} style={{ transform: open ? 'rotate(0deg)' : 'rotate(-90deg)', transition: 'transform 150ms' }} />
          {item.icon}
          <span>{item.label}</span>
        </div>
        {open && (
          <Stack gap={1} style={{ marginTop: 'var(--mantine-spacing-xs)' }}>
            {item.children!.map((child) => (
              <NavItem key={child.to} item={child} currentPath={currentPath} level={level + 1} />
            ))}
          </Stack>
        )}
      </Box>
    )
  }

  if (disabled) {
    return (
      <NavLink
        label={item.label}
        leftSection={item.icon}
        disabled
        style={indentStyle}
      />
    )
  }

  return (
    <NavLink
      component={Link}
      to={to}
      label={item.label}
      leftSection={item.icon}
      active={active}
      aria-current={active ? 'page' : undefined}
      style={indentStyle}
    />
  )
}

export function NavSection({ section, user }: NavSectionProps) {
  const location = useLocation()
  const currentPath = location.pathname

  // Фильтруем пункты: скрываем только по roles (авторизация), НЕ по enabled
  // enabled=false → рендерим как disabled (серый, некликабельный)
  const visibleItems = section.items.filter((item) => {
    if (item.roles && user && !item.roles.includes(user.role)) return false
    return true
  })

  if (visibleItems.length === 0) return null

  const [open, setOpen] = useState(section.defaultOpen ?? true)

  return (
    <>
      {section.header && (
        <>
          {!section.collapsible ? (
            <Divider label={section.header} labelPosition="left" mb="xs" />
          ) : (
            <div
              onClick={() => setOpen(!open)}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 'var(--mantine-spacing-xs)',
                padding: 'var(--mantine-spacing-xs) var(--mantine-spacing-sm)',
                borderRadius: 'var(--mantine-radius-sm)',
                cursor: 'pointer',
                color: 'var(--mantine-color-dimmed)',
                fontSize: 'var(--mantine-font-size-xs)',
                fontWeight: 600,
                textTransform: 'uppercase',
                letterSpacing: '0.05em',
                userSelect: 'none',
                marginBottom: 'var(--mantine-spacing-xs)',
              }}
              role="button"
              tabIndex={0}
              aria-expanded={open}
            >
              <IconChevronDown size={12} style={{ transform: open ? 'rotate(0deg)' : 'rotate(-90deg)', transition: 'transform 150ms' }} />
              {section.header}
            </div>
          )}
        </>
      )}
      {open && (
        <Stack gap={2}>
          {visibleItems.map((item) => (
            <NavItem key={item.to || item.label} item={item} currentPath={currentPath} />
          ))}
        </Stack>
      )}
    </>
  )
}