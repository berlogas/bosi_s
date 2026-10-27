/**
 * Скелетон для ленивых страниц админки.
 */

import { Skeleton } from '@mantine/core'

export function AdminSkeleton() {
  return (
    <div style={{ padding: '2rem' }}>
      <Skeleton height={32} width="30%" style={{ marginBottom: '1.5rem' }} />
      <Skeleton height={16} width="100%" style={{ marginBottom: '0.5rem' }} />
      <Skeleton height={16} width="80%" style={{ marginBottom: '0.5rem' }} />
      <Skeleton height={16} width="60%" style={{ marginBottom: '1.5rem' }} />
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(300px, 1fr))', gap: '1rem' }}>
        {[...Array(5)].map((_, i) => (
          <div key={i} style={{ padding: '1rem', border: '1px solid var(--mantine-color-default-border)', borderRadius: 'var(--mantine-radius-md)' }}>
            <Skeleton height={20} width="60%" style={{ marginBottom: '0.75rem' }} />
            <Skeleton height={14} width="100%" style={{ marginBottom: '0.5rem' }} />
            <Skeleton height={14} width="80%" />
          </div>
        ))}
      </div>
    </div>
  )
}