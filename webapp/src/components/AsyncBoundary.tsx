/**
 * Единый компонент границы асинхронной загрузки (QueryState / AsyncBoundary).
 *
 * Инкапсулирует все четыре состояния загрузки данных:
 *  1. loading  — скелетоны вместо голого Loader
 *  2. error    — Alert с кнопкой «Повторить»
 *  3. empty    — EmptyState с действием вместо текстовой заглушки
 *  4. success  — рендер children
 *
 * Вместо повторяющихся блоков if/else в каждой странице:
 *   if (isLoading) return <SkeletonList />
 *   if (isError) return <Alert color="error">{error.message}</Alert>
 *   if (!data.length) return <EmptyState ... />
 *   return <Table data={data} />
 *
 * пишется однострочно:
 *   <AsyncBoundary data={data} isLoading={isLoading} error={error} onRetry={refetch}>
 *     <Table data={data} />
 *   </AsyncBoundary>
 *
 * Это критерий приёмки Волны 6, п.4: «Единый QueryState/AsyncBoundary».
 */

import { Alert, Button, Group, Text } from '@mantine/core'
import { EmptyState } from './EmptyState'
import { SkeletonList } from './SkeletonList'

interface AsyncBoundaryProps<T> {
  /** Данные. Если undefined/null и не loading — показывается EmptyState. */
  data: T | null | undefined
  /** Идёт ли загрузка. При true показываются скелетоны. */
  isLoading?: boolean
  /** Ошибка загрузки. При наличии показывается Alert с кнопкой повтора. */
  error: Error | null | undefined
  /** Содержимое при успешной загрузке. */
  children: React.ReactNode
  /** Callback при клике на «Повторить». */
  onRetry?: () => void
  /** Заголовок пустого состояния. */
  emptyTitle?: string
  /** Пояснение пустого состояния. */
  emptyDescription?: string
  /** Действие (кнопка/ссылка) в пустом состоянии. */
  emptyAction?: React.ReactNode
  /** Количество скелетонов в состоянии загрузки. */
  skeletonCount?: number
  /** Высота строки скелетона. */
  skeletonRowHeight?: string | number
}

export function AsyncBoundary<T>({
  data,
  isLoading = false,
  error,
  children,
  onRetry,
  emptyTitle = 'Данных пока нет.',
  emptyDescription,
  emptyAction,
  skeletonCount = 6,
  skeletonRowHeight,
}: AsyncBoundaryProps<T>) {
  // 1. Ошибка — приоритет высший: показываем Alert с возможностью повтора
  if (error) {
    return (
      <Alert color="error" role="alert">
        <Text size="sm">{error instanceof Error ? error.message : String(error)}</Text>
        {onRetry && (
          <Group justify="flex-end" mt="xs">
            <Button
              size="xs"
              variant="default"
              onClick={onRetry}
              aria-label="Повторить"
            >
              Повторить
            </Button>
          </Group>
        )}
      </Alert>
    )
  }

  // 2. Загрузка — скелетоны вместо голого Loader
  if (isLoading) {
    return <SkeletonList count={skeletonCount} rowHeight={skeletonRowHeight} />
  }

  // 3. Пусто — EmptyState с действием, а не только текстом
  if (!data || (Array.isArray(data) && data.length === 0)) {
    return (
      <EmptyState
        title={emptyTitle}
        description={emptyDescription}
        action={emptyAction}
      />
    )
  }

  // 4. Успех — рендер children
  return <>{children}</>
}

export type { AsyncBoundaryProps }
