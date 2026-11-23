/**
 * A11y-тесты ключевых компонентов админки и базы знаний (Волна 6, п.1).
 *
 * Проверяем отсутствие нарушений доступности (axe-core) для:
 *  - SimpleTable (таблицы админки)
 *  - EmptyState (пустые состояния)
 *  - InboxPanel (массовое добавление)
 *  - DangerZone (подтверждение удаления)
 */

import React from 'react'
import { render } from '@testing-library/react'
import { axe } from 'vitest-axe'
import { describe, expect, it } from 'vitest'
import { MantineProvider } from '@mantine/core'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'

import { SimpleTable, DangerZone } from '../features/admin/components'
import { EmptyState } from '../components/EmptyState'
import { InboxPanel } from '../features/admin/components/InboxPanel'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { retry: false },
  },
})

// SimpleTable синхронизирует страницу с URL — ему нужен роутер.
const renderWithProviders = (ui: React.ReactNode) =>
  render(
    <MemoryRouter>
      <QueryClientProvider client={queryClient}>
        <MantineProvider>{ui}</MantineProvider>
      </QueryClientProvider>
    </MemoryRouter>,
  )

describe('SimpleTable a11y', () => {
  it('table is accessible', async () => {
    const columns = [
      { id: 'name', accessorKey: 'name', header: 'Имя' },
      { id: 'role', accessorKey: 'role', header: 'Роль' },
    ]
    const data = [
      { id: '1', name: 'Иван', role: 'admin' },
      { id: '2', name: 'Мария', role: 'researcher' },
    ]
    const pagination = { pageIndex: 0, pageSize: 10, pageCount: 1 }

    const { container } = renderWithProviders(
      <SimpleTable
        columns={columns as any}
        data={data as any}
        pagination={pagination}
        onPaginationChange={() => {}}
        sorting={[]}
        onSortingChange={() => {}}
        filters={[]}
        onFiltersChange={() => {}}
        emptyMessage="Нет данных"
      />,
    )
    const result = await axe(container)
    expect(result.violations).toHaveLength(0)
  })

  it('empty table message is accessible', async () => {
    const columns = [{ id: 'name', accessorKey: 'name', header: 'Имя' }]
    const pagination = { pageIndex: 0, pageSize: 10, pageCount: 1 }

    const { container } = renderWithProviders(
      <SimpleTable
        columns={columns as any}
        data={[]}
        pagination={pagination}
        onPaginationChange={() => {}}
        sorting={[]}
        onSortingChange={() => {}}
        filters={[]}
        onFiltersChange={() => {}}
        emptyMessage="Нет данных"
      />,
    )
    const result = await axe(container)
    expect(result.violations).toHaveLength(0)
  })
})

describe('EmptyState a11y', () => {
  it('empty state with action is accessible', async () => {
    const { container } = renderWithProviders(
      <EmptyState
        title="Нет данных"
        description="Создайте первую запись."
        action={<button>Создать</button>}
        icon={<span>Иконка</span>}
      />,
    )
    const result = await axe(container)
    expect(result.violations).toHaveLength(0)
  })

  it('empty state without action is accessible', async () => {
    const { container } = renderWithProviders(
      <EmptyState title="Нет данных" description="Описание." />,
    )
    const result = await axe(container)
    expect(result.violations).toHaveLength(0)
  })
})

describe('DangerZone a11y', () => {
  it('danger zone modal is accessible', async () => {
    const { container } = renderWithProviders(
      <DangerZone
        label="Удалить"
        confirmText="ivanov"
        onConfirm={() => {}}
        warning="Предупреждение"
      />,
    )
    const result = await axe(container)
    expect(result.violations).toHaveLength(0)
  })
})

describe('InboxPanel a11y', () => {
  it('inbox panel is accessible', async () => {
    const { container } = renderWithProviders(<InboxPanel />)
    const result = await axe(container)
    expect(result.violations).toHaveLength(0)
  })
})
