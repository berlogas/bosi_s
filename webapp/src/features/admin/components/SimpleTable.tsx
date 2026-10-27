/**
 * Простая таблица данных с пагинацией и синхронизацией URL.
 * Не делает клиентскую фильтрацию/сортировку — ожидает, что data уже готов хуком.
 */

import { useRef, useEffect, useMemo } from 'react'
import { Table } from '@mantine/core'
import { useSearchParams } from 'react-router-dom'

export interface SimpleColumn<T> {
  id: string
  accessorKey?: string
  header: string
  cell?: (row: T) => React.ReactNode
}

export interface SimpleTableProps<T> {
  columns: SimpleColumn<T>[]
  data: T[]
  pagination: { pageIndex: number; pageSize: number; pageCount: number }
  onPaginationChange: (next: { pageIndex: number; pageSize: number; pageCount: number }) => void
  sorting: { id: string; desc: boolean }[]
  onSortingChange: (next: { id: string; desc: boolean }[]) => void
  filters: { id: string; value: unknown }[]
  onFiltersChange: (next: { id: string; value: unknown }[]) => void
  rowActions?: (row: { original: T }) => React.ReactNode
  isLoading?: boolean
  emptyMessage?: string
}

export function SimpleTable<T extends { id: string | number }>({
  columns,
  data,
  pagination,
  onPaginationChange,
  sorting,
  onSortingChange,
  filters,
  onFiltersChange,
  rowActions,
  isLoading = false,
  emptyMessage = 'Нет данных',
}: SimpleTableProps<T>) {
  const [, setSearchParams] = useSearchParams()

  // Рефы для отслеживания предыдущих значений (избегаем бесконечного цикла навигации)
  const prevPagination = useRef(pagination)
  const prevSorting = useRef(sorting)
  const prevFilters = useRef(filters)

  // Синхронизация с URL — только если значения реально изменились
  useEffect(() => {
    const paginationChanged =
      prevPagination.current.pageIndex !== pagination.pageIndex ||
      prevPagination.current.pageSize !== pagination.pageSize
    const sortingChanged = JSON.stringify(prevSorting.current) !== JSON.stringify(sorting)
    const filtersChanged = JSON.stringify(prevFilters.current) !== JSON.stringify(filters)

    if (paginationChanged || sortingChanged || filtersChanged) {
      prevPagination.current = pagination
      prevSorting.current = sorting
      prevFilters.current = filters

      const params = new URLSearchParams()
      params.set('page', String(pagination.pageIndex + 1))
      params.set('size', String(pagination.pageSize))
      if (sorting.length) params.set('sort', JSON.stringify(sorting))
      if (filters.length) params.set('filters', JSON.stringify(filters))
      setSearchParams(params, { replace: true })
    }
  }, [pagination, sorting, filters, setSearchParams])

  // Сообщаем хуку (и URL) об изменении фильтров извне (например, при вводе в поле поиска)
  useEffect(() => {
    onFiltersChange?.(filters)
  }, [filters, onFiltersChange])

  // Пагинация — используем переданные данные напрямую (хуки уже сделали фильтрацию/сортировку)
  const pageCount = Math.max(1, pagination.pageCount || 1)
  const safePageIndex = Math.min(pagination.pageIndex || 0, pageCount - 1)
  const pageData = useMemo(() => {
    const start = safePageIndex * pagination.pageSize
    return data.slice(start, start + pagination.pageSize)
  }, [data, safePageIndex, pagination.pageSize])

  if (isLoading) {
    return <div style={{ padding: 16, textAlign: 'center', color: '#666' }}>Загрузка...</div>
  }

  return (
    <div style={{ overflowX: 'auto', minWidth: '100%' }}>
      <Table>
        <thead>
          <tr
            style={{
              position: 'sticky',
              top: 0,
              zIndex: 2,
              background: '#f5f5f5',
            }}
          >
            {columns.map((col) => {
              const canSort = !!col.accessorKey
              return (
                <th
                  key={col.id}
                  style={{
                    cursor: canSort ? 'pointer' : 'default',
                    userSelect: 'none',
                    whiteSpace: 'nowrap',
                    padding: '8px 12px',
                    borderBottom: '2px solid #ddd',
                    textAlign: 'left',
                    background: '#f5f5f5',
                    position: 'sticky',
                    top: 0,
                  }}
                  onClick={
                    canSort
                      ? () =>
                          onSortingChange([
                            {
                              id: col.accessorKey!,
                              desc:
                                sorting[0]?.id === col.accessorKey &&
                                !sorting[0]?.desc,
                            },
                          ])
                      : undefined
                  }
                >
                  {col.header}
                  {canSort &&
                    sorting[0]?.id === col.accessorKey && (
                      <span style={{ marginLeft: 4 }}>
                        {sorting[0]?.desc ? '▼' : '▲'}
                      </span>
                    )}
                </th>
              )
            })}
            {rowActions && (
              <th
                style={{
                  padding: '8px 12px',
                  borderBottom: '2px solid #ddd',
                  textAlign: 'right',
                  background: '#f5f5f5',
                  position: 'sticky',
                  top: 0,
                }}
              ></th>
            )}
          </tr>
        </thead>
        <tbody>
          {data.length === 0 ? (
            <tr>
              <td
                colSpan={columns.length + (rowActions ? 1 : 0)}
                style={{ textAlign: 'center', padding: '2rem', color: '#999' }}
              >
                {emptyMessage}
              </td>
            </tr>
          ) : (
            pageData.map((row) => (
              <tr
                key={String(row.id) || JSON.stringify(row)}
                style={{
                  contentVisibility: 'auto',
                  containIntrinsicSize: '100px 60px',
                }}
              >
                {columns.map((col) => (
                  <td
                    key={col.id}
                    style={{
                      padding: '8px 12px',
                      borderBottom: '1px solid #eee',
                    }}
                  >
                    {col.cell
                      ? col.cell(row)
                      : String(
                          (row as Record<string, unknown>)[
                            col.accessorKey ?? ''
                          ] ?? '',
                        )}
                  </td>
                ))}
                {rowActions && (
                  <td
                    style={{
                      whiteSpace: 'nowrap',
                      textAlign: 'right',
                      padding: '8px 12px',
                    }}
                  >
                    {rowActions({ original: row })}
                  </td>
                )}
              </tr>
            ))
          )}
        </tbody>
      </Table>

      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          marginTop: '1rem',
          flexWrap: 'wrap',
          gap: '0.5rem',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
          <button
            style={{
              padding: '4px 8px',
              border: '1px solid #ddd',
              background: 'white',
              borderRadius: 4,
              cursor: 'pointer',
            }}
            disabled={pagination.pageIndex === 0}
            onClick={() =>
              onPaginationChange({
                ...pagination,
                pageIndex: pagination.pageIndex - 1,
              })
            }
          >
            ◀ Назад
          </button>
          <span
            style={{
              minWidth: '80px',
              textAlign: 'center',
              display: 'inline-block',
            }}
          >
            {pagination.pageIndex + 1} /{' '}
            {Math.max(1, pagination.pageCount || 1)}
          </span>
          <button
            style={{
              padding: '4px 8px',
              border: '1px solid #ddd',
              background: 'white',
              borderRadius: 4,
              cursor: 'pointer',
            }}
            disabled={
              pagination.pageIndex >=
              Math.max(1, pagination.pageCount || 1) - 1
            }
            onClick={() =>
              onPaginationChange({
                ...pagination,
                pageIndex: pagination.pageIndex + 1,
              })
            }
          >
            Вперед ▶
          </button>
        </div>
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: '0.5rem',
            color: '#999',
            fontSize: 14,
          }}
        >
          <span>Стр.:</span>
          <select
            value={pagination.pageSize}
            onChange={(e) =>
              onPaginationChange({
                ...pagination,
                pageSize: Number(e.target.value),
                pageIndex: 0,
              })
            }
            style={{
              padding: '4px 8px',
              border: '1px solid #ddd',
              borderRadius: 4,
            }}
          >
            <option value={10}>10</option>
            <option value={25}>25</option>
            <option value={50}>50</option>
            <option value={100}>100</option>
          </select>
          <span>Всего: {data.length}</span>
        </div>
      </div>
    </div>
  )
}
