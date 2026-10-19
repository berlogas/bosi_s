/**
 * Пункт меню «Текущая сессия»: не гаснет при выходе из сессии.
 *
 * Пункт определялся разбором адреса (`/s/<id>`), поэтому уход в меню гасил
 * его, хотя сессия никуда не делась, и вернуться можно было только через
 * дашборд. Теперь помнится последняя открытая сессия.
 */

import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient } from '@tanstack/react-query'
import { beforeEach, describe, expect, it } from 'vitest'

import { AppProviders } from '../../app/AppProviders'
import { AppRoutes } from '../../routes'
import { loginAs, mockApi, TEST_USER } from '../../test/helpers'

const HEALTH = {
  status: 'ok',
  llm_model: 'test-model',
  embedding_model: 'test-embed',
  ollama: {},
}

const SESSION = {
  id: 's-1',
  title: 'Сессия',
  status: 'active',
  created_at: '2026-10-01T00:00:00+00:00',
  expires_at: '2026-12-30T00:00:00+00:00',
}

function mockLayoutApi(routes: Record<string, unknown> = {}) {
  return mockApi({
    'GET /api/health': HEALTH,
    'GET /api/sessions': [SESSION],
    'GET /api/sessions/s-1': {
      ...SESSION,
      user_id: 'u-1',
      writable: true,
      days_left: 84,
      resume_note: null,
      state_snapshot: {},
      usage: {
        sources: 0,
        messages: 0,
        downloads: 0,
        export_count: 0,
        minutes_used: 0,
      },
      summary: {
        title: '',
        sources: 0,
        documents: 0,
        documents_limit: 50,
        storage_bytes: 0,
        storage_limit_bytes: 524288000,
        projects: 0,
        projects_limit: 10,
        messages: 0,
        links: 0,
        read_only: false,
      },
      settings: { k: 10, category: 'all', scope: 'best', no_cache: false },
      upstream: [],
      questions: [],
      history: [],
      recent_sources: [],
      recent_documents: [],
    },
    'GET /api/tasks': { tasks: [], active: 0 },
    'GET /api/chat/messages': { messages: [], total: 0, offset: 0 },
    'GET /api/chat/quick-history': [],
    'GET /api/documents': [],
    'GET /api/documents/stats': { total: 0, storage_bytes: 0, by_category: {} },
    ...routes,
  })
}

function renderPath(path: string) {
  loginAs(TEST_USER)
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  })
  return render(
    <AppProviders initialPath={path} queryClient={queryClient}>
      <AppRoutes />
    </AppProviders>,
  )
}

describe('пункт «Текущая сессия»', () => {
  beforeEach(() => {
    sessionStorage.clear()
  })

  it('вне сессии пункт серый: сессию ещё не открывали', async () => {
    mockLayoutApi()
    renderPath('/')

    await screen.findByRole('heading', { name: 'Новая сессия' })
    expect(screen.getByText('Текущая сессия')).toBeVisible()
    // серый = disabled у Mantine NavLink
    expect(
      screen.getByText('Текущая сессия').closest('[data-disabled="true"]'),
    ).not.toBeNull()
  })

  it('после выхода в меню пункт остаётся доступным и возвращает в сессию', async () => {
    mockLayoutApi()
    renderPath('/s/s-1/chat')

    // в сессии пункт активен
    await screen.findByText('Текущая сессия')
    expect(
      screen.getByText('Текущая сессия').closest('[data-disabled="true"]'),
    ).toBeNull()

    // уходим в меню — пункт не должен погаснуть
    await userEvent.click(screen.getByText('Информационная панель'))
    await screen.findByRole('heading', { name: 'Новая сессия' })
    expect(
      screen.getByText('Текущая сессия').closest('[data-disabled="true"]'),
    ).toBeNull()

    // и ведёт обратно в ту же сессию
    await userEvent.click(screen.getByText('Текущая сессия'))
    await screen.findByRole('heading', { name: 'Сессия' })
  })

  it('после перезагрузки страницы вне сессии пункт помнит сессию', async () => {
    mockLayoutApi()
    // эмулируем перезагрузку: sessionStorage живёт, а рендер начинается с /
    window.sessionStorage.setItem('boasi.lastSessionPath', '/s/s-1')
    renderPath('/')

    await screen.findByRole('heading', { name: 'Новая сессия' })
    expect(
      screen.getByText('Текущая сессия').closest('[data-disabled="true"]'),
    ).toBeNull()
  })

  it('битое значение в хранилище не ломает пункт', async () => {
    mockLayoutApi()
    window.sessionStorage.setItem('boasi.lastSessionPath', 'не путь')
    renderPath('/')

    await screen.findByRole('heading', { name: 'Новая сессия' })
    // значение отброшено, пункт серый — но приложение работает
    expect(
      screen.getByText('Текущая сессия').closest('[data-disabled="true"]'),
    ).not.toBeNull()
  })
})
