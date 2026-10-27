/**
 * A11y-тест AsyncBoundary (Волна 6, п.1).
 *
 * Проверяем, что компонент не вносит барьеров доступности:
 *  - в состоянии загрузки (скелетоны) — нет блокирующих элементов
 *   в состоянии ошибки — Alert имеет роль alert и кнопку Повторить
 *  в состоянии пустого — EmptyState имеет правильную структуру
 *  в состоянии успеха — дети рендерятся без нарушений
 */

import React from 'react'
import { render, screen } from '@testing-library/react'
import { axe } from 'vitest-axe'
import { describe, expect, it } from 'vitest'
import { MantineProvider } from '@mantine/core'
import { AsyncBoundary } from './AsyncBoundary'

const renderWithProviders = (ui: React.ReactNode) =>
  render(<MantineProvider>{ui}</MantineProvider>)

describe('AsyncBoundary a11y', () => {
  it('loading state is accessible', async () => {
    const { container } = renderWithProviders(
      <AsyncBoundary<string[]> data={null} isLoading={true} error={null}>
        <div>Содержимое</div>
      </AsyncBoundary>,
    )
    const result = await axe(container)
    expect(result.violations).toHaveLength(0)
  })

  it('error state is accessible', async () => {
    const { container } = renderWithProviders(
      <AsyncBoundary<string[]>
        data={null}
        isLoading={false}
        error={new Error('Тестовая ошибка')}
        onRetry={() => {}}
      >
        <div>Содержимое</div>
      </AsyncBoundary>,
    )
    const result = await axe(container)
    if (result.violations.length > 0) {
      console.log('A11y violations:', JSON.stringify(result.violations, null, 2))
    }
    expect(result.violations).toHaveLength(0)
    expect(screen.getByRole('alert')).toBeVisible()
    expect(screen.getByRole('button', { name: 'Повторить' })).toBeVisible()
  })

  it('empty state is accessible', async () => {
    const { container } = renderWithProviders(
      <AsyncBoundary<string[]>
        data={[]}
        isLoading={false}
        error={null}
        emptyTitle="Нет данных"
        emptyAction={
          <button>Сбросить</button>
        }
      >
        <div>Содержимое</div>
      </AsyncBoundary>,
    )
    const result = await axe(container)
    expect(result.violations).toHaveLength(0)
  })

  it('success state is accessible', async () => {
    const { container } = renderWithProviders(
      <AsyncBoundary<string[]>
        data={['один', 'два']}
        isLoading={false}
        error={null}
      >
        <ul>
          <li>один</li>
          <li>два</li>
        </ul>
      </AsyncBoundary>,
    )
    const result = await axe(container)
    expect(result.violations).toHaveLength(0)
  })
})
