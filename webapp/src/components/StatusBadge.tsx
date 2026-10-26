/**
 * Семантический бейдж статуса: сессия, задача, документ.
 *
 * Цвета берутся из темы (success/warning/error/info), не хардкод. Подпись
 * можно передать явно (`label`), а можно вывести из `kind` + `status` —
 * тогда один и тот же статус выглядит одинаково на всех экранах.
 */

import { Badge } from '@mantine/core'
import type { BadgeProps } from '@mantine/core'

export type StatusKind = 'session' | 'task' | 'document'

const STATUS_META: Record<
  StatusKind,
  Record<string, { label: string; color: string }>
> = {
  session: {
    active: { label: 'активная', color: 'success' },
    paused: { label: 'приостановлена', color: 'warning' },
    archived: { label: 'в архиве', color: 'gray' },
  },
  task: {
    queued: { label: 'в очереди', color: 'gray' },
    running: { label: 'выполняется', color: 'info' },
    done: { label: 'готово', color: 'success' },
    error: { label: 'ошибка', color: 'error' },
    cancelled: { label: 'отменено', color: 'warning' },
  },
  document: {
    ready: { label: 'готов', color: 'success' },
    pending: { label: 'в обработке', color: 'warning' },
    error: { label: 'ошибка', color: 'error' },
  },
}

export interface StatusBadgeProps extends Omit<BadgeProps, 'color'> {
  /** Явная подпись; если не задана — берётся из `kind` + `status`. */
  label?: string
  /** Статус из API (`active`, `running`, `ready`, …). */
  status?: string
  /** Какая сущность: у неё свой набор подписей и цветов. */
  kind?: StatusKind
  /** Семантический цвет темы: 'success' | 'warning' | 'error' | 'info' | 'dimmed' */
  color?: BadgeProps['color']
  size?: BadgeProps['size']
}

export function StatusBadge({
  label,
  status,
  kind = 'task',
  color,
  size = 'xs',
  ...rest
}: StatusBadgeProps) {
  const meta = status ? STATUS_META[kind][status] : undefined
  return (
    <Badge color={color ?? meta?.color ?? 'gray'} size={size} {...rest}>
      {label ?? meta?.label ?? status ?? '—'}
    </Badge>
  )
}
