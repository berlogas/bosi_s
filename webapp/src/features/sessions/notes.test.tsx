/**
 * Тесты вкладки «Заметки» (Фазы 2/4, паритет notes_tab):
 * сохранение resume_note + снапшота, подтверждение/ошибка, read-only.
 * Снапшот («точка возврата») сохраняется, но в интерфейсе не показывается.
 */

import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient } from '@tanstack/react-query'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { AppProviders } from '../../app/AppProviders'
import { AppRoutes } from '../../routes'
import { json, loginAs, mockApi, resetAuth } from '../../test/helpers'

const HEALTH = {
  status: 'ok',
  llm_model: 'test-model',
  embedding_model: 'test-embed',
  ollama: {},
}

function session(extra: Record<string, unknown> = {}) {
  return {
    id: 's-1',
    title: 'Сессия',
    status: 'active',
    writable: true,
    created_at: '2026-10-01T00:00:00+00:00',
    expires_at: '2026-12-30T00:00:00+00:00',
    days_left: 84,
    resume_note: 'доделать раздел Methods',
    state_snapshot: { tab: 'chat' },
    summary: {
      documents: 0,
      documents_limit: 50,
      storage_bytes: 0,
      storage_limit_bytes: 524288000,
    },
    ...extra,
  }
}

function renderNotes(overrides: Record<string, unknown> = {}) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  })
  const { calls } = mockApi({
    'GET /api/health': HEALTH,
    'GET /api/sessions': [],
    'GET /api/tasks': { tasks: [], active: 0 },
    'GET /api/chat/messages': { messages: [], total: 0, offset: 0 },
    'GET /api/sessions/s-1/documents': [],
    'GET /api/sessions/s-1/projects': [],
    'GET /api/sessions/s-1': session(),
    ...overrides,
  })
  render(
    <AppProviders initialPath="/s/s-1/notes" queryClient={queryClient}>
      <AppRoutes />
    </AppProviders>,
  )
  return calls
}

beforeEach(() => {
  sessionStorage.clear()
  loginAs()
})

afterEach(() => {
  vi.unstubAllGlobals()
  resetAuth()
})

describe('вкладка Заметки', () => {
  it('заметка из detail, сохранение шлёт PUT state', async () => {
    const calls = renderNotes({
      'PUT /api/sessions/s-1/state': session({
        resume_note: 'новая заметка',
        last_action_label: 'Заметка сохранена',
        state_snapshot: { tab: 'notes', saved_at: '2026-10-07T10:00:00+00:00' },
      }),
    })

    const area = await screen.findByLabelText('Заметка о работе')
    expect(area).toHaveValue('доделать раздел Methods')

    await userEvent.clear(area)
    await userEvent.type(area, 'новая заметка')
    await userEvent.click(screen.getByRole('button', { name: 'Сохранить заметку' }))

    await waitFor(() => {
      const call = calls.find(
        (c) => c.init.method === 'PUT' && c.url.includes('/state'),
      )
      expect(call).toBeDefined()
      const body = JSON.parse(String(call?.init.body))
      expect(body.resume_note).toBe('новая заметка')
      // снапшот несёт активную вкладку — после F5 откроемся здесь же
      expect(body.snapshot.tab).toBe('notes')
      expect(body.force).toBe(true)
    })

    expect(await screen.findByText('Заметка сохранена.')).toBeInTheDocument()
    // отладочный JSON снапшота в интерфейс не выводится (убран на Фазе 11)
    expect(screen.queryByText(/"tab": "notes"/)).toBeNull()
    expect(screen.queryByText('Состояние (точка возврата)')).toBeNull()
    expect(screen.queryByText(/saved_at/)).toBeNull()
  })

  it('пустая заметка сохраняется как null (паритет note или None)', async () => {
    const calls = renderNotes({
      'PUT /api/sessions/s-1/state': session({ resume_note: null }),
    })

    const area = await screen.findByLabelText('Заметка о работе')
    await userEvent.clear(area)
    await userEvent.click(screen.getByRole('button', { name: 'Сохранить заметку' }))

    await waitFor(() => {
      const call = calls.find((c) => c.init.method === 'PUT')
      expect(JSON.parse(String(call?.init.body)).resume_note).toBeNull()
    })
  })

  it('ошибка сохранения — alert, повтор возможен', async () => {
    renderNotes({
      'PUT /api/sessions/s-1/state': json({ detail: 'Сессия не найдена' }, 404),
    })

    const area = await screen.findByLabelText('Заметка о работе')
    await userEvent.clear(area)
    await userEvent.type(area, 'x')
    await userEvent.click(screen.getByRole('button', { name: 'Сохранить заметку' }))

    expect(await screen.findByText('Сессия не найдена')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Сохранить заметку' })).toBeEnabled()
  })

  it('архивная сессия: поле и кнопка заблокированы', async () => {
    renderNotes({
      'GET /api/sessions/s-1': session({
        status: 'archived',
        writable: false,
        state_snapshot: {},
      }),
    })

    expect(await screen.findByLabelText('Заметка о работе')).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Сохранить заметку' })).toBeDisabled()
  })

  it('снапшот не показывается: экран остаётся заметкой', async () => {
    // «точка возврата» продолжает сохраняться, но пользователю не нужна
    renderNotes({
      'GET /api/sessions/s-1': session({
        state_snapshot: { tab: 'notes', saved_at: '2026-10-07T09:00:00Z' },
      }),
    })

    expect(await screen.findByLabelText('Заметка о работе')).toBeInTheDocument()
    expect(screen.queryByText('Состояние (точка возврата)')).toBeNull()
    expect(screen.queryByText(/"tab": "notes"/)).toBeNull()
    // «Состояние системы» в подвале сайдбара — другое дело, его не трогаем
    expect(screen.queryByText(/точка возврата/i)).toBeNull()
  })
})
