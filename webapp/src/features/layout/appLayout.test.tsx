/**
 * Пункт меню «Текущая сессия»: не гаснет при выходе из сессии.
 *
 * Пункт определялся разбором адреса (`/s/<id>`), поэтому уход в меню гасил
 * его, хотя сессия никуда не делась, и вернуться можно было только через
 * дашборд. Теперь помнится последняя открытая сессия.
 */

import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient } from '@tanstack/react-query'
import { beforeEach, describe, expect, it } from 'vitest'

import { AppProviders } from '../../app/AppProviders'
import { AppRoutes } from '../../routes'
import {
  loginAs,
  mockApi,
  TEST_ADMIN,
  TEST_OTHER_USER,
  TEST_USER,
  type TestUser,
} from '../../test/helpers'
import { isNavItemActive } from './AppLayout'

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
    // Админка видна только администратору, но её вкладка «Пользователи»
    // открывается сразу и спрашивает список.
    'GET /api/admin/users': [],
    ...routes,
  })
}

/** Пункт меню по подписи: тот же текст бывает заголовком страницы. */
function navItem(label: string): HTMLElement {
  const item = screen.getAllByText(label).find((node) => node.closest('a'))
  if (!item) throw new Error(`Пункт меню «${label}» не найден`)
  return item
}

function renderPath(path: string, user: TestUser = TEST_USER) {
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

describe('активный пункт меню', () => {
  it('подпуть включает пункт, а корень — только сам себя', () => {
    expect(isNavItemActive('/s/s-1/chat', '/s/s-1')).toBe(true)
    expect(isNavItemActive('/s/s-1/documents', '/s/s-1')).toBe(true)
    expect(isNavItemActive('/s/s-1', '/s/s-1')).toBe(true)
    expect(isNavItemActive('/s/s-2/chat', '/s/s-1')).toBe(false)
    expect(isNavItemActive('/knowledge', '/s/s-1')).toBe(false)
    expect(isNavItemActive('/admin/audit', '/admin')).toBe(true)
    expect(isNavItemActive('/', '/')).toBe(true)
    expect(isNavItemActive('/knowledge', '/')).toBe(false)
    expect(isNavItemActive('/admin', '/')).toBe(false)
  })

  it('пункты меню — настоящие ссылки: Tab и Enter работают', async () => {
    sessionStorage.clear()
    mockLayoutApi()
    renderPath('/s/s-1/chat')

    await screen.findByText('Текущая сессия')
    const sessionLink = navItem('Текущая сессия').closest('a')
    const panelLink = navItem('Информационная панель').closest('a')

    // Без `href` это не ссылка: Tab пролетает мимо, Ctrl-клик и «открыть в
    // новой вкладке» не работают.
    expect(sessionLink).toHaveAttribute('href', '/s/s-1')
    expect(panelLink).toHaveAttribute('href', '/')

    panelLink!.focus()
    expect(panelLink).toHaveFocus()
    await userEvent.keyboard('{Enter}')
    await screen.findByRole('heading', { name: 'Новая сессия' })
  })

  it('в сессии активен только её пункт, панель — нет', async () => {
    sessionStorage.clear()
    mockLayoutApi()
    renderPath('/s/s-1/chat')

    await screen.findByText('Текущая сессия')
    expect(
      screen.getByText('Текущая сессия').closest('[aria-current="page"]'),
    ).not.toBeNull()
    expect(
      screen.getByText('Информационная панель').closest('[aria-current="page"]'),
    ).toBeNull()
  })

  it('на вкладке документов пункт сессии остаётся активным', async () => {
    sessionStorage.clear()
    mockLayoutApi()
    renderPath('/s/s-1/documents')

    await screen.findByText('Текущая сессия')
    expect(
      screen.getByText('Текущая сессия').closest('[aria-current="page"]'),
    ).not.toBeNull()
  })

  it('на /knowledge активна только «База знаний»', async () => {
    sessionStorage.clear()
    mockLayoutApi()
    renderPath('/knowledge')

    await screen.findByRole('heading', { name: 'База знаний' })
    expect(navItem('База знаний').closest('[aria-current="page"]')).not.toBeNull()
    expect(navItem('Информационная панель').closest('[aria-current="page"]')).toBeNull()
    expect(navItem('Текущая сессия').closest('[aria-current="page"]')).toBeNull()
  })

  it('на / активна только панель', async () => {
    sessionStorage.clear()
    mockLayoutApi()
    renderPath('/')

    await screen.findByRole('heading', { name: 'Новая сессия' })
    expect(
      navItem('Информационная панель').closest('[aria-current="page"]'),
    ).not.toBeNull()
    expect(navItem('База знаний').closest('[aria-current="page"]')).toBeNull()
  })
})

describe('мобильный drawer', () => {
  it('Burger открывает и закрывает меню', async () => {
    sessionStorage.clear()
    mockLayoutApi()
    renderPath('/')

    await screen.findByRole('heading', { name: 'Новая сессия' })
    const burger = screen.getByRole('button', { name: 'Меню' })
    expect(burger).toHaveAttribute('aria-expanded', 'false')

    await userEvent.click(burger)
    expect(screen.getByRole('button', { name: 'Меню' })).toHaveAttribute(
      'aria-expanded',
      'true',
    )

    await userEvent.click(screen.getByRole('button', { name: 'Меню' }))
    expect(screen.getByRole('button', { name: 'Меню' })).toHaveAttribute(
      'aria-expanded',
      'false',
    )
  })

  it('переход по пункту меню закрывает drawer', async () => {
    sessionStorage.clear()
    mockLayoutApi()
    renderPath('/')

    await screen.findByRole('heading', { name: 'Новая сессия' })
    await userEvent.click(screen.getByRole('button', { name: 'Меню' }))
    await userEvent.click(navItem('База знаний'))

    expect(await screen.findByRole('button', { name: 'Меню' })).toHaveAttribute(
      'aria-expanded',
      'false',
    )
  })
})

describe('пункт «Текущая сессия»', () => {
  beforeEach(() => {
    sessionStorage.clear()
  })

  it('вне сессии пункт серый и не ловит Tab', async () => {
    mockLayoutApi()
    renderPath('/')

    await screen.findByRole('heading', { name: 'Новая сессия' })
    const label = screen.getByText('Текущая сессия')
    expect(label).toBeVisible()
    // серый = disabled у Mantine NavLink
    expect(label.closest('[data-disabled="true"]')).not.toBeNull()

    // Неактивный пункт — не ссылка и не цель Tab: адреса у него нет.
    const item = label.closest('.mantine-NavLink-root') as HTMLElement
    expect(item).not.toHaveAttribute('href')
    item.focus()
    expect(item).not.toHaveFocus()
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
    // значение хранит и сессию, и её владельца: чужая вкладка не должна
    // подхватить чужую сессию
    window.sessionStorage.setItem(
      'boasi.lastSessionPath',
      JSON.stringify({ path: '/s/s-1', userId: TEST_USER.id }),
    )
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

  it('значение без владельца не подставляется', async () => {
    mockLayoutApi()
    // старое значение (путь строкой) и путь без id владельца — подхватывать
    // нельзя: неясно, чья это сессия
    window.sessionStorage.setItem('boasi.lastSessionPath', '/s/s-1')
    renderPath('/')
    await screen.findByRole('heading', { name: 'Новая сессия' })
    expect(
      screen.getByText('Текущая сессия').closest('[data-disabled="true"]'),
    ).not.toBeNull()
  })

  it('после выхода из аккаунта пункт гаснет и следующему не достаётся', async () => {
    mockLayoutApi({ 'POST /api/auth/logout': null })
    const first = renderPath('/s/s-1/chat')

    await screen.findByText('Текущая сессия')
    expect(
      screen.getByText('Текущая сессия').closest('[data-disabled="true"]'),
    ).toBeNull()

    await userEvent.click(screen.getByRole('button', { name: 'Выйти' }))
    await screen.findByRole('heading', { name: /Вход/i })

    // выход забывает сессию: в следующей вкладке её предложить нельзя
    expect(window.sessionStorage.getItem('boasi.lastSessionPath')).toBeNull()
    first.unmount()

    // тот же браузер, та же вкладка — зашёл другой человек
    const api = mockLayoutApi()
    renderPath('/', TEST_OTHER_USER)

    await screen.findByRole('heading', { name: 'Новая сессия' })
    expect(
      screen.getByText('Текущая сессия').closest('[data-disabled="true"]'),
    ).not.toBeNull()

    // и клик по серому пункту никуда не ведёт
    await userEvent.click(screen.getByText('Текущая сессия'))
    expect(
      api.calls.filter((call) => call.url.includes('/api/sessions/s-1')),
    ).toHaveLength(0)
    expect(screen.getByRole('heading', { name: 'Новая сессия' })).toBeVisible()
  })

  it('сессия, сохранённая другим пользователем, не предлагается', async () => {
    mockLayoutApi()
    // значение осталось от прошлого владельца (например, вкладку переиспользовали
    // без выхода) — второй пользователь её видеть не должен
    window.sessionStorage.setItem(
      'boasi.lastSessionPath',
      JSON.stringify({ path: '/s/s-1', userId: TEST_USER.id }),
    )
    renderPath('/', TEST_OTHER_USER)

    await screen.findByRole('heading', { name: 'Новая сессия' })
    expect(
      screen.getByText('Текущая сессия').closest('[data-disabled="true"]'),
    ).not.toBeNull()
  })
})

it('на вкладке projects активен пункт сессии', async () => {
  sessionStorage.clear()
  mockLayoutApi()
  renderPath('/s/s-1/projects')

  await screen.findByText('Текущая сессия')
  expect(
    screen.getByText('Текущая сессия').closest('[aria-current="page"]'),
  ).not.toBeNull()
  expect(
    screen.getByText('Информационная панель').closest('[aria-current="page"]'),
  ).toBeNull()
})

it('на вкладке notes активен пункт сессии', async () => {
  sessionStorage.clear()
  mockLayoutApi()
  renderPath('/s/s-1/notes')

  await screen.findByText('Текущая сессия')
  expect(
    screen.getByText('Текущая сессия').closest('[aria-current="page"]'),
  ).not.toBeNull()
  expect(
    screen.getByText('Информационная панель').closest('[aria-current="page"]'),
  ).toBeNull()
})

it('на /admin активен пункт администрирования', async () => {
  sessionStorage.clear()
  mockLayoutApi()
  // Пункт и страница админки — только для роли admin (см. AppLayout).
  renderPath('/admin', TEST_ADMIN)

  await screen.findByRole('heading', { name: 'Администрирование' })
  expect(screen.getByText('Текущая сессия').closest('[aria-current="page"]')).toBeNull()
  // Подпись есть и в заголовке страницы — пункт меню ищем по ссылке.
  expect(navItem('Администрирование').closest('[aria-current="page"]')).not.toBeNull()
})

it('на /knowledge активна только «База знаний»', async () => {
  sessionStorage.clear()
  mockLayoutApi()
  renderPath('/knowledge')

  await screen.findByRole('heading', { name: 'База знаний' })
  expect(navItem('База знаний').closest('[aria-current="page"]')).not.toBeNull()
  expect(navItem('Информационная панель').closest('[aria-current="page"]')).toBeNull()
  expect(navItem('Текущая сессия').closest('[aria-current="page"]')).toBeNull()
})

describe('переключатель темы', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  it('по умолчанию системная (auto), клик по «Тёмная» пишет localStorage', async () => {
    const user = userEvent.setup()
    sessionStorage.clear()
    mockLayoutApi()
    renderPath('/')

    const control = await screen.findByRole('radiogroup', { name: 'Тема интерфейса' })
    // по умолчанию auto: активна «Системная»
    expect(
      within(control).getByRole('radio', { name: 'Системная' }),
    ).toBeChecked()

    await user.click(within(control).getByRole('radio', { name: 'Тёмная' }))
    expect(
      within(control).getByRole('radio', { name: 'Тёмная' }),
    ).toBeChecked()
    // менеджер провайдера сохранил выбор — тема переживёт F5
    expect(localStorage.getItem('mantine-color-scheme-value')).toBe('dark')
    // и DOM-атрибут переключён: тёмная палитра активна
    expect(document.documentElement).toHaveAttribute(
      'data-mantine-color-scheme',
      'dark',
    )
  })

  it('выбор «Светлая» после тёмной возвращает light', async () => {
    const user = userEvent.setup()
    sessionStorage.clear()
    mockLayoutApi()
    localStorage.setItem('mantine-color-scheme-value', 'dark')
    renderPath('/')

    const control = await screen.findByRole('radiogroup', { name: 'Тема интерфейса' })
    expect(
      within(control).getByRole('radio', { name: 'Тёмная' }),
    ).toBeChecked()

    await user.click(within(control).getByRole('radio', { name: 'Светлая' }))
    expect(localStorage.getItem('mantine-color-scheme-value')).toBe('light')
    expect(document.documentElement).toHaveAttribute(
      'data-mantine-color-scheme',
      'light',
    )
  })
})
