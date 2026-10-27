/**
 * Скелетон для ленивых страниц админки.
 */

import { Skeleton } from '@mantine/core'

export function AdminSkeleton() {
  return (
    <div style={{ padding: 'var(--mantine-spacing-xl)' }}>
      <Skeleton height={32} width="30%" style={{ marginBottom: 'var(--mantine-spacing-lg)' }} />
      <Skeleton height={16} width="100%" style={{ marginBottom: 'var(--mantine-spacing-xs)' }} />
      <Skeleton height={16} width="80%" style={{ marginBottom: 'var(--mantine-spacing-xs)' }} />
      <Skeleton height={16} width="60%" style={{ marginBottom: 'var(--mantine-spacing-lg)' }} />
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(300px, 1fr))', gap: 'var(--mantine-spacing-md)' }}>
        {[...Array(5)].map((_, i) => (
          <div key={i} style={{ padding: 'var(--mantine-spacing-md)', border: '1px solid var(--mantine-color-default-border)', borderRadius: 'var(--mantine-radius-md)' }}>
            <Skeleton height={20} width="60%" style={{ marginBottom: 'var(--mantine-spacing-sm)' }} />
            <Skeleton height={14} width="100%" style={{ marginBottom: 'var(--mantine-spacing-xs)' }} />
            <Skeleton height={14} width="80%" />
          </div>
        ))}
      </div>
    </div>
  )
}