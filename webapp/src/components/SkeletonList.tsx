/**
 * Скелетоны-заглушки вместо голого `Loader`: карточки сессий, история чата,
 * таблицы документов и проектов. Рендерит N строк-полос с разной длиной.
 */

import { Skeleton, Stack } from '@mantine/core'

interface SkeletonListProps {
  /** Количество строк-заглушек. */
  count?: number
  /** Высота строки. */
  rowHeight?: string | number
  /** Доля коротких строк (0..1) — для ритма. */
  shortRatio?: number
}

export function SkeletonList({
  count = 4,
  rowHeight = '16px',
  shortRatio = 0.4,
}: SkeletonListProps) {
  const rows = Array.from({ length: count }, (_, i) => (
    <Skeleton
      key={i}
      height={rowHeight}
      width={i % Math.max(1, Math.floor(1 / shortRatio)) === 0 ? '60%' : '100%'}
    />
  ))
  return <Stack gap="xs">{rows}</Stack>
}
