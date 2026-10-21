/**
 * Граница ошибок рендера: белый экран вместо приложения недопустим.
 *
 * React размонтирует всё дерево при необработанной ошибке. Граница ловит
 * её на уровне маршрута: пользователь видит текст ошибки и может уйти на
 * панель или обновить страницу, а остальные разделы остаются доступны.
 */

import { Alert, Button, Center, Group, Stack, Title } from '@mantine/core'
import { Component } from 'react'
import type { ErrorInfo, ReactNode } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'

interface BoundaryProps {
  children: ReactNode
  /** Смена адреса сбрасывает ошибку: другой раздел может быть исправен. */
  resetKey: string
  onReset: () => void
  onHome: () => void
}

interface BoundaryState {
  error: Error | null
}

class Boundary extends Component<BoundaryProps, BoundaryState> {
  override state: BoundaryState = { error: null }

  static getDerivedStateFromError(error: Error): BoundaryState {
    return { error }
  }

  override componentDidCatch(error: Error, info: ErrorInfo): void {
    // Ошибку не глотаем: без этого в консоли не останется следа.
    console.error('Ошибка рендера раздела', error, info.componentStack)
  }

  override componentDidUpdate(prev: BoundaryProps): void {
    if (prev.resetKey !== this.props.resetKey && this.state.error) {
      this.setState({ error: null })
    }
  }

  override render(): ReactNode {
    const { error } = this.state
    if (!error) return this.props.children

    return (
      <Center mih="40vh">
        <Stack gap="sm" maw={640}>
          <Title order={3}>Что-то сломалось</Title>
          <Alert color="red" role="alert">
            {error.message || 'Неизвестная ошибка'}
          </Alert>
          <Group>
            <Button
              onClick={() => {
                this.setState({ error: null })
                this.props.onReset()
              }}
            >
              Обновить
            </Button>
            <Button
              variant="light"
              onClick={() => {
                this.setState({ error: null })
                this.props.onHome()
              }}
            >
              На панель
            </Button>
          </Group>
        </Stack>
      </Center>
    )
  }
}

export function RouteErrorBoundary({ children }: { children: ReactNode }) {
  const navigate = useNavigate()
  const location = useLocation()
  return (
    <Boundary
      resetKey={location.pathname}
      onReset={() => window.location.reload()}
      onHome={() => navigate('/', { replace: true })}
    >
      {children}
    </Boundary>
  )
}
