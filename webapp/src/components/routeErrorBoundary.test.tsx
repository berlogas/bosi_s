/**
 * Ошибка рендера не должна оставлять белый экран: пользователь видит текст
 * и может уйти в другой раздел.
 */

import { MantineProvider } from '@mantine/core'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, expect, it, vi } from 'vitest'

import { RouteErrorBoundary } from './RouteErrorBoundary'

function Boom(): never {
  throw new Error('раздел упал')
}

afterEach(() => {
  vi.restoreAllMocks()
})

it('ловит ошибку раздела и возвращает на панель', async () => {
  // React штатно логирует пойманную ошибку — в тесте это шум. Плюс
  // помечаем window-error обработанным, иначе Vitest считает тест упавшим.
  vi.spyOn(console, 'error').mockImplementation(() => {})
  const swallow = (event: ErrorEvent): void => event.preventDefault()
  window.addEventListener('error', swallow)

  try {
    render(
      <MantineProvider>
        <MemoryRouter initialEntries={['/boom']}>
          <Routes>
            <Route
              path="/boom"
              element={
                <RouteErrorBoundary>
                  <Boom />
                </RouteErrorBoundary>
              }
            />
            <Route path="/" element={<p>Панель жива</p>} />
          </Routes>
        </MemoryRouter>
      </MantineProvider>,
    )

    expect(await screen.findByText('Что-то сломалось')).toBeInTheDocument()
    expect(screen.getByRole('alert')).toHaveTextContent('раздел упал')
    expect(screen.getByRole('button', { name: 'Обновить' })).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: 'На панель' }))
    expect(await screen.findByText('Панель жива')).toBeInTheDocument()
  } finally {
    window.removeEventListener('error', swallow)
  }
})
