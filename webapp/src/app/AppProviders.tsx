/**
 * Общие провайдеры приложения — используются и в main.tsx, и в тестах,
 * чтобы тесты рендерили ровно то же дерево, что видит пользователь.
 */

import { MantineProvider } from '@mantine/core'
import { Notifications } from '@mantine/notifications'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { BrowserRouter, MemoryRouter } from 'react-router-dom'

export function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        // Ошибки API — это ApiError с русским текстом: показываем их на месте,
        // а не ретраями по умолчанию.
        retry: false,
        staleTime: 30_000,
        refetchOnWindowFocus: false,
      },
    },
  })
}

export function AppProviders({
  children,
  queryClient = createQueryClient(),
  /** Для тестов: стартовый маршрут вместо BrowserRouter (окно браузера). */
  initialPath,
}: {
  children: ReactNode
  queryClient?: QueryClient
  initialPath?: string
}) {
  const router =
    initialPath === undefined ? (
      <BrowserRouter>{children}</BrowserRouter>
    ) : (
      <MemoryRouter initialEntries={[initialPath]}>{children}</MemoryRouter>
    )

  return (
    <MantineProvider defaultColorScheme="light">
      <Notifications position="top-right" />
      <QueryClientProvider client={queryClient}>{router}</QueryClientProvider>
    </MantineProvider>
  )
}
