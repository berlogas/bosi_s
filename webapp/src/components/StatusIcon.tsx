/**
 * Иконка статуса задачи/сессии — компонент, а не значение в модуле
 * форматирования.
 *
 * Регрессия, которую это предотвращает: `STATUS_ICONS` жил в `lib/format.ts`
 * и в `TaskPanel` подставлялся в JSX как значение. React падал с
 * «Objects are not valid as a React child (found: object with keys
 * {$$typeof, render})» на каждом завершённом вопросе.
 */

import {
  IconCheck,
  IconCircleStop,
  IconCircleX,
  IconClock,
  IconRefresh,
} from '@tabler/icons-react'
import type { ElementType } from 'react'

export const STATUS_ICONS: Record<string, ElementType> = {
  queued: IconClock,
  running: IconRefresh,
  done: IconCheck,
  error: IconCircleX,
  cancelled: IconCircleStop,
}

export function StatusIcon({
  status,
  size = 14,
  stroke = 1.5,
}: {
  status: string
  size?: number
  stroke?: number
}) {
  const Icon = STATUS_ICONS[status]
  return Icon ? <Icon size={size} stroke={stroke} /> : null
}
