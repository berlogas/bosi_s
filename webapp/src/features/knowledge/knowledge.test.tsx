/**
 * Страница «База знаний» для исследователя, который не может наполнять базу.
 *
 * Проверяем ровно то, ради чего страница и делалась: список виден обычному
 * пользователю, поиск уходит на сервер, а кнопок наполнения на странице нет —
 * иначе исследователь увидел бы то, на что у него прав нет.
 *
 * Тесты рендерят маршрут `/knowledge` напрямую (`initialPath`), а не кликают
 * по меню: пункт навигации проверяется отдельно, одним тестом, и не тянет на
 * себе проверку содержимого страницы.
 */

import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient } from '@tanstack/react-query'
import { describe, expect, it, vi } from 'vitest'

import { AppProviders } from '../../app/AppProviders'
import { AppRoutes } from '../../routes'
import { json, loginAs, mockApi, TEST_ADMIN, TEST_USER } from '../../test/helpers'

const HEALTH = {
  status: 'ok',
  llm_model: 'test-model',
  embedding_model: 'test-embed',
  ollama: {},
}

const DOCUMENTS = [
  {
    id: 'g-1',
    dockey: 'glob1',
    title: 'Хлорофилл и фотосинтез',
    filename: 'chlorophyll.pdf',
    citation: 'Ivanov, 2025',
    category: 'global_knowledge',
    status: 'ready',
    size_bytes: 2048,
    chunk_count: 7,
    tags: ['биология'],
    source: 'upload',
    created_at: '2026-10-07T09:00:00+00:00',
  },
  {
    id: 'g-2',
    dockey: 'glob2',
    title: 'CTD-зонды',
    filename: 'ctd.pdf',
    citation: null,
    category: 'temp_literature',
    status: 'error',
    size_bytes: 1024 * 1024,
    chunk_count: 3,
    tags: [],
    source: 'path',
    created_at: '2026-10-07T09:00:00+00:00',
  },
]

const STATS = {
  total: 2,
  storage_bytes: 2048 + 1024 * 1024,
  by_category: { global_knowledge: 1, temp_literature: 1 },
}

function renderPath(
  path = '/knowledge',
  user: typeof TEST_USER | typeof TEST_ADMIN = TEST_USER,
) {
  loginAs(user)
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  })
  return render(
    <AppProviders initialPath={path} queryClient={queryClient}>
      <AppRoutes />
    </AppProviders>,
  )
}

function mockKnowledgeApi(routes: Record<string, unknown> = {}) {
  return mockApi({
    'GET /api/health': HEALTH,
    'GET /api/documents': DOCUMENTS,
    'GET /api/documents/stats': STATS,
    ...routes,
  })
}

describe('База знаний', () => {
  it('исследователь видит список глобальной базы и сводку', async () => {
    mockKnowledgeApi()
    renderPath()

    expect(await screen.findByRole('heading', { name: 'База знаний' })).toBeVisible()
    expect(await screen.findByText('Хлорофилл и фотосинтез')).toBeVisible()
    expect(screen.getByText('CTD-зонды')).toBeVisible()
    // статусы и метки из ответа, а не заглушка
    expect(screen.getByText('готов')).toBeVisible()
    expect(screen.getByText('ошибка')).toBeVisible()
    expect(screen.getByText('биология')).toBeVisible()
    // сводка из /api/documents/stats
    expect(screen.getByText(/документов: 2/)).toBeVisible()

    // исследователю не показывают кнопок наполнения
    expect(screen.queryByRole('button', { name: /Управлять базой/ })).toBeNull()
    expect(screen.queryByRole('button', { name: /Добавить/ })).toBeNull()
    expect(screen.queryByText('Администрирование')).toBeNull()
  })

  it('пункт меню есть у исследователя, а админка ему не видна', async () => {
    mockKnowledgeApi()
    renderPath('/')

    // NavLink без href не получает роль link, поэтому пункт ищем текстом
    expect(await screen.findByText('База знаний')).toBeVisible()
    expect(screen.queryByText('Администрирование')).toBeNull()
  })

  it('администратору предлагается перейти к управлению базой', async () => {
    mockKnowledgeApi()
    renderPath('/knowledge', TEST_ADMIN)

    expect(await screen.findByRole('button', { name: 'Управлять базой' })).toBeVisible()
  })

  it('поиск уходит на сервер с введённым словом после debounce', async () => {
    const { calls } = mockKnowledgeApi()
    renderPath()

    await screen.findByText('Хлорофилл и фотосинтез')
    await userEvent.type(screen.getByLabelText('Поиск по базе'), 'ctd')

    await waitFor(() =>
      expect(calls.some((call) => call.url.includes('q=ctd'))).toBe(true),
    )
  })

  it('debounce: три буквы дают один запрос, а не три', async () => {
    const { calls } = mockKnowledgeApi()
    renderPath()

    await screen.findByText('Хлорофилл и фотосинтез')
    await userEvent.type(screen.getByLabelText('Поиск по базе'), 'ctd')
    await waitFor(() =>
      expect(calls.some((call) => call.url.includes('q=ctd'))).toBe(true),
    )

    const searchCalls = calls.filter((call) => call.url.includes('q='))
    expect(searchCalls).toHaveLength(1)
    expect(searchCalls[0]?.url).toContain('q=ctd')
  })

  it('категория применяется сразу, без кнопки', async () => {
    const { calls } = mockKnowledgeApi()
    renderPath()

    await screen.findByText('Хлорофилл и фотосинтез')
    await userEvent.click(screen.getByRole('combobox', { name: 'Категория' }))
    // Mantine держит выпадающий список в слое с display:none — по умолчанию
    // его не видно в дереве доступности, поэтому ищем с hidden: true.
    await userEvent.click(
      screen.getByRole('option', { name: 'Временная литература', hidden: true }),
    )

    await waitFor(() =>
      expect(calls.some((call) => call.url.includes('category=temp_literature'))).toBe(
        true,
      ),
    )
  })

  it('пустая база объясняет, кто её наполняет', async () => {
    mockKnowledgeApi({
      'GET /api/documents': [],
      'GET /api/documents/stats': { total: 0, storage_bytes: 0, by_category: {} },
    })
    renderPath()

    expect(
      await screen.findByText('База пока пуста. Наполняет её администратор.'),
    ).toBeVisible()
  })

  it('ошибка запроса показывается, а не роняет страницу', async () => {
    const spy = vi.spyOn(console, 'error').mockImplementation(() => {})
    mockKnowledgeApi({
      'GET /api/documents': json({ detail: 'внутренняя ошибка' }, 500),
    })
    renderPath()

    expect(await screen.findByText('Не удалось загрузить список')).toBeVisible()
    spy.mockRestore()
  })
})
