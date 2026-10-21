/**
 * Прямой заход в paused-сессию: баннер + возобновление (F5).
 *
 * Статус paused остаётся writable, поэтому чат не ломался — но оставался
 * paused навсегда: без resume пользователь не видел ни реактивации, ни
 * восстановления индекса. Баннер закрывает этот разрыв.
 */

import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient } from '@tanstack/react-query'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { AppProviders } from '../../app/AppProviders'
import { AppRoutes } from '../../routes'
import { json, loginAs, mockApi, resetAuth } from '../../test/helpers'

const HEALTH = { status: 'ok', llm_model: 'test', embedding_model: 'test', ollama: {} }

const SUMMARY = {
  documents: 1,
  documents_limit: 50,
  storage_bytes: 0,
  storage_limit_bytes: 524288000,
  projects: 0,
  projects_limit: 10,
  messages: 0,
  links: 0,
  read_only: false,
}

function detail(status: 'paused' | 'active') {
  return {
    id: 's-1',
    title: 'Сессия',
    status,
    created_at: '2026-10-01T00:00:00+00:00',
    expires_at: '2026-12-30T00:00:00+00:00',
    days_left: 84,
    writable: true,
    resume_note: null,
    state_snapshot: { tab: 'notes' },
    summary: SUMMARY,
    settings: { k: 10, category: 'all', scope: 'best', no_cache: false },
    upstream: [],
    questions: [],
    history: [],
    recent_sources: [],
    recent_documents: [],
  }
}

function renderPaused(overrides: Record<string, unknown> = {}) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  })
  const { calls } = mockApi({
    'GET /api/health': HEALTH,
    'GET /api/sessions': [],
    'GET /api/tasks': { tasks: [], active: 0 },
    'GET /api/chat/messages': { messages: [], total: 0, offset: 0 },
    'GET /api/sessions/s-1': detail('paused'),
    ...overrides,
  })
  render(
    <AppProviders initialPath="/s/s-1/chat" queryClient={queryClient}>
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

describe('paused-сессия по прямому адресу', () => {
  it('показывает баннер и после resume уходит на сохранённую вкладку', async () => {
    let resumed = false
    const calls = renderPaused({
      'GET /api/sessions/s-1': () => json(detail(resumed ? 'active' : 'paused')),
      'POST /api/sessions/s-1/resume': () => {
        resumed = true
        return json({
          session: { ...detail('active') },
          summary: SUMMARY,
          state: { tab: 'notes' },
          restored_documents: 4,
          days_left: 84,
          last_exchange: null,
        })
      },
      'PUT /api/sessions/s-1/state': detail('active'),
    })

    expect(await screen.findByText('Сессия на паузе')).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: 'Возобновить' }))

    await waitFor(() =>
      expect(
        calls.some(
          (call) => call.init.method === 'POST' && call.url.includes('/s-1/resume'),
        ),
      ).toBe(true),
    )
    // вкладка из state, а не чат по умолчанию
    expect(
      await screen.findByRole('tab', { name: 'Заметки', selected: true }),
    ).toBeInTheDocument()
    await waitFor(() =>
      expect(screen.queryByText('Сессия на паузе')).not.toBeInTheDocument(),
    )
    expect(await screen.findByText('Сессия возобновлена')).toBeInTheDocument()
  })

  it('ошибка resume остаётся видимой, баннер и статус не меняются', async () => {
    renderPaused({
      'POST /api/sessions/s-1/resume': json({ detail: 'Индекс недоступен' }, 503),
    })

    expect(await screen.findByText('Сессия на паузе')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Возобновить' }))

    expect(await screen.findByText('Индекс недоступен')).toBeInTheDocument()
    expect(screen.getByText('Сессия на паузе')).toBeInTheDocument()
    expect(screen.getByText(/Статус: приостановлена/)).toBeInTheDocument()
  })
})
