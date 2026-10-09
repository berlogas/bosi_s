/**
 * Приёмка Фазы 0: «пустой дашборд после логина через новую обёртку».
 *
 * Тест рендерит реальные роуты (login → dashboard) поверх подменённого
 * fetch: проверяем и форму входа, и то, что клиент API действительно
 * провёл пользователя дальше.
 */

import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { AppProviders } from '../../app/AppProviders'
import { tokens } from '../../api/tokens'
import { AppRoutes } from '../../routes'
import { useAuth } from './authStore'

const user = {
  id: 'u1',
  username: 'ivan',
  // ФИО заполнено — приветствие должно быть по нему, а не по логину
  full_name: 'Иванов Иван Иванович',
  role: 'researcher' as const,
  is_active: true,
}

function renderApp() {
  return render(
    <AppProviders initialPath="/login">
      <AppRoutes />
    </AppProviders>,
  )
}

beforeEach(() => {
  tokens.clear()
  useAuth.setState({
    user: null,
    status: 'anonymous',
    loginError: null,
    loginBusy: false,
  })
})

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe('вход в приложение', () => {
  it('логин → дашборд с приветствием', async () => {
    const spy = vi.fn((input: RequestInfo | URL) => {
      const url = String(input)
      if (url.endsWith('/api/auth/login')) {
        return Promise.resolve(
          new Response(
            JSON.stringify({
              user,
              tokens: {
                access_token: 'a1',
                refresh_token: 'r1',
                token_type: 'bearer',
                expires_in: 1800,
              },
            }),
            { status: 200, headers: { 'Content-Type': 'application/json' } },
          ),
        )
      }
      if (url.endsWith('/api/health')) {
        return Promise.resolve(
          new Response(
            JSON.stringify({
              status: 'ok',
              app: 'boasi_s',
              environment: 'test',
              version: '0',
              database: 'ok',
              llm_model: 'qwen',
              embedding_model: 'nomic',
              ollama: { reachable: true },
            }),
            { status: 200, headers: { 'Content-Type': 'application/json' } },
          ),
        )
      }
      return Promise.reject(new Error(`неожиданный запрос: ${url}`))
    })
    vi.stubGlobal('fetch', spy)

    renderApp()

    expect(await screen.findByText('Вход в boasi_s')).toBeInTheDocument()

    await userEvent.type(screen.getByLabelText('Логин'), 'ivan')
    await userEvent.type(screen.getByLabelText('Пароль'), 'secret')
    await userEvent.click(screen.getByRole('button', { name: 'Войти' }))

    // Дашборд после успешного входа (приёмка Фазы 0)
    expect(await screen.findByRole('heading', { name: 'Дашборд' })).toBeInTheDocument()
    expect(screen.getByText('Здравствуйте, Иванов Иван Иванович!')).toBeInTheDocument()

    // Боковая панель: метка сборки и пользователь
    expect(screen.getByText(/сборка \d{4}-\d{2}-\d{2}/)).toBeInTheDocument()
    // в сайдбаре — ФИО и русская подпись роли
    expect(screen.getByText(/Иванов Иван Иванович · Исследователь/)).toBeInTheDocument()

    await waitFor(() =>
      expect(spy.mock.calls.some(([u]) => String(u).endsWith('/api/auth/login'))).toBe(
        true,
      ),
    )
  })

  it('неверный пароль → ошибка на форме, маршрут не меняется', async () => {
    vi.stubGlobal('fetch', () =>
      Promise.resolve(
        new Response(
          JSON.stringify({ error: 'forbidden', detail: 'Неверный логин или пароль' }),
          {
            status: 403,
            headers: { 'Content-Type': 'application/json' },
          },
        ),
      ),
    )

    renderApp()

    await userEvent.type(screen.getByLabelText('Логин'), 'ivan')
    await userEvent.type(screen.getByLabelText('Пароль'), 'wrong')
    await userEvent.click(screen.getByRole('button', { name: 'Войти' }))

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Неверный логин или пароль',
    )
    expect(screen.getByText('Вход в boasi_s')).toBeInTheDocument()
  })

  it('пустая форма → подсказка, без сетевых запросов', async () => {
    const spy = vi.fn()
    vi.stubGlobal('fetch', spy)

    renderApp()
    await userEvent.click(screen.getByRole('button', { name: 'Войти' }))

    expect(
      await screen.findByText('Заполните оба поля: логин и пароль.'),
    ).toBeInTheDocument()
    expect(spy).not.toHaveBeenCalled()
  })
})
