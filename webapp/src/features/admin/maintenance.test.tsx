/**
 * Раздел «Обслуживание»: резервные копии + сброс в одном месте.
 *
 * Ключевое, что здесь проверяется: бэкап требует фразы подтверждения,
 * восстановление в UI отсутствует намеренно (нужна остановка платформы),
 * а после сброса клиент сбрасывается целиком.
 */

import { notifications } from '@mantine/notifications'
import { cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient } from '@tanstack/react-query'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { AppProviders, createQueryClient } from '../../app/AppProviders'
import { AppRoutes } from '../../routes'
import { json, loginAs, mockApi, resetAuth, TEST_ADMIN, TEST_USER } from '../../test/helpers'

const HEALTH = {
  status: 'ok',
  llm_model: 'test-model',
  embedding_model: 'test-embed',
  ollama: {},
}

const PLAN = {
  data_dir: '/data',
  backup_dir: '/backups',
  files: 26,
  source_bytes: 1_427_851,
  source_human: '1.4 МБ',
  estimated_bytes: 2_446_533,
  estimated_human: '2.3 МБ',
  free_bytes: 397_897_162_752,
  free_human: '370.6 ГБ',
  existing: 2,
  keep: 14,
  db_exists: true,
  warning: 'Копия займёт около 2.3 МБ; более старых копий будет удалено: 0',
}

const BACKUP = {
  name: 'boasi-20261008-120000.tar.gz',
  bytes: 383_540,
  human_size: '374.6 КБ',
  created_at: '2026-10-08T12:00:00+00:00',
  has_sha256: true,
  has_manifest: true,
}

const RESET_PLAN = {
  scope: 'data',
  tables: { research_sessions: 4 },
  rows: 4,
  paths: [],
  files: 0,
  total_bytes: 0,
  kept_paths: ['/data/hf'],
  includes_models: false,
  allowed: true,
  blocked_reason: null,
  confirmation: 'СБРОС ДАННЫХ',
}

function routes(overrides: Record<string, unknown> = {}) {
  return {
    'GET /api/health': HEALTH,
    'GET /api/tasks': { tasks: [], active: 0 },
    'GET /api/sessions': [],
    'GET /api/admin/users': [],
    'GET /api/admin/audit': [],
    'GET /api/admin/documents': [],
    'GET /api/admin/backup': { backups: [BACKUP], plan: PLAN },
    'GET /api/admin/reset/preview': RESET_PLAN,
    ...overrides,
  }
}

function renderAdmin() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  })
  return render(
    <AppProviders initialPath="/admin" queryClient={queryClient}>
      <AppRoutes />
    </AppProviders>,
  )
}

async function openServiceTab() {
  renderAdmin()
  await userEvent.click(await screen.findByRole('tab', { name: 'Обслуживание' }))
}

beforeEach(() => sessionStorage.clear())

afterEach(() => {
  // Без явного cleanup предыдущий render() остаётся в document.body —
  // и findByText начинает находить элементы чужого теста.
  cleanup()
  // Уведомления живут в отдельном портале и переживают размонтирование:
  // их текст тоже мешал бы findByText.
  notifications.clean()
  vi.unstubAllGlobals()
  resetAuth()
})

describe('раздел «Обслуживание»', () => {
  it('бэкап и сброс живут на одной вкладке', async () => {
    loginAs(TEST_ADMIN)
    mockApi(routes())
    await openServiceTab()

    expect(await screen.findByRole('button', { name: 'Создать копию…' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Сбросить…' })).toBeInTheDocument()
    expect(screen.getByText('Сброс состояния')).toBeInTheDocument()
  })

  it('показывает план: каталог копий, объём и хранение', async () => {
    loginAs(TEST_ADMIN)
    mockApi(routes())
    await openServiceTab()

    expect(screen.getByText(/2.3 МБ/)).toBeInTheDocument()
    expect(screen.getByText(/2.3 МБ/)).toBeInTheDocument()
    expect(screen.getByText(/последние 14/)).toBeInTheDocument()
    expect(screen.getByText('boasi-20261008-120000.tar.gz')).toBeInTheDocument()
    expect(screen.getByText('374.6 КБ')).toBeInTheDocument()
  })

  it('копия создаётся без ввода фразы — обычное подтверждение', async () => {
    loginAs(TEST_ADMIN)
    const calls: { url: string; init: RequestInit }[] = []
    mockApi(
      routes({
        'POST /api/admin/backup': (url: string, init: RequestInit) => {
          calls.push({ url, init })
          return Promise.resolve(
            json({
              entry: BACKUP,
              deleted_old: [],
              restore_hint: './scripts/restore.sh',
            }),
          )
        },
      }),
    )
    await openServiceTab()

    await userEvent.click(await screen.findByRole('button', { name: 'Создать копию…' }))

    // никаких полей для ввода фразы — только кнопки
    expect(screen.queryByTestId('backup-confirm-input')).toBeNull()

    const submit = await screen.findByRole('button', { name: 'Создать' })
    expect(submit).toBeEnabled()

    await userEvent.click(submit)
    await waitFor(() => expect(calls).toHaveLength(1))
  })

  it('после создания окно закрывается и список обновляется', async () => {
    loginAs(TEST_ADMIN)
    const calls: { url: string; init: RequestInit }[] = []
    mockApi(
      routes({
        'POST /api/admin/backup': (url: string, init: RequestInit) => {
          calls.push({ url, init })
          return Promise.resolve(
            json({
              entry: {
                ...BACKUP,
                name: 'boasi-20261008-130000.tar.gz',
              },
              deleted_old: ['boasi-20261007-120000.tar.gz'],
              restore_hint: './scripts/restore.sh',
            }),
          )
        },
      }),
    )
    await openServiceTab()

    await userEvent.click(await screen.findByRole('button', { name: 'Создать копию…' }))
    await userEvent.click(await screen.findByRole('button', { name: 'Создать' }))

    await waitFor(() => expect(calls).toHaveLength(1))
    expect(JSON.parse(String(calls[0]?.init.body))).toEqual({ keep: undefined })
    await waitFor(() =>
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument(),
    )
  })

  it('восстановление предлагает только скрипт', async () => {
    loginAs(TEST_ADMIN)
    mockApi(routes())
    await openServiceTab()

    expect(
      await screen.findByText('Восстановление — только скриптом'),
    ).toBeInTheDocument()
    expect(screen.getByText(/scripts\/restore\.sh/)).toBeInTheDocument()
    // кнопки восстановления в UI нет намеренно
    expect(screen.queryByRole('button', { name: /восстановить/i })).toBeNull()
  })

  it('удаляет копию', async () => {
    loginAs(TEST_ADMIN)
    const calls: string[] = []
    mockApi(
      routes({
        'DELETE /api/admin/backup/boasi-20261008-120000.tar.gz': (url: string) => {
          calls.push(url)
          return Promise.resolve(new Response(null, { status: 204 }))
        },
      }),
    )
    await openServiceTab()

    const row = (await screen.findByText('boasi-20261008-120000.tar.gz')).closest('tr')
    const button = within(row as HTMLElement).getByRole('button', { name: 'Удалить' })
    await userEvent.click(button)

    await waitFor(() => expect(calls).toHaveLength(1))
    expect(calls[0]).toContain('/api/admin/backup/boasi-20261008-120000.tar.gz')
  })

  it('предупреждает, когда базы данных нет', async () => {
    loginAs(TEST_ADMIN)
    mockApi(routes({ 'GET /api/admin/backup': { backups: [], plan: { ...PLAN, db_exists: false } } }))
    await openServiceTab()

    expect(
      screen.getByRole('button', { name: 'Создать копию…' }),
    ).toBeDisabled()
    expect(
      screen.getByRole('button', { name: 'Создать копию…' }),
    ).toBeDisabled()
  })

  it('показывает ошибку создания копии', async () => {
    loginAs(TEST_ADMIN)
    mockApi(
      routes({
        'POST /api/admin/backup': () =>
          Promise.resolve(json({ detail: 'Не хватает места' }, 409)),
      }),
    )
    await openServiceTab()

    await userEvent.click(await screen.findByRole('button', { name: 'Создать копию…' }))
    await userEvent.click(await screen.findByRole('button', { name: 'Создать' }))

    expect(await screen.findByText('Не хватает места')).toBeInTheDocument()
  })

  it('сброс по-прежнему доступен и требует своей фразы', async () => {
    loginAs(TEST_ADMIN)
    mockApi(routes())
    await openServiceTab()

    await userEvent.click(await screen.findByRole('button', { name: 'Сбросить…' }))
    const input = await screen.findByTestId('reset-confirm-input')
    await userEvent.type(input, 'СБРОС ДАННЫХ')
    expect(screen.getByRole('button', { name: 'Выполнить сброс' })).toBeEnabled()
  })

  it('не-админ не видит раздел', async () => {
    loginAs(TEST_USER)
    mockApi(routes())
    renderAdmin()

    expect(
      await screen.findByText('Раздел доступен только администратору.'),
    ).toBeInTheDocument()
  })

  it('сброс: показывает таблицы и сохранённый кэш моделей', async () => {
    loginAs(TEST_ADMIN)
    mockApi(
      routes({
        'GET /api/admin/reset/preview': {
          ...RESET_PLAN,
          paths: [{ path: '/data/sessions', files: 8, bytes: 2048 }],
          files: 8,
          total_bytes: 2048,
          tables: { research_sessions: 4, documents: 12, messages: 37 },
          rows: 53,
        },
      }),
    )
    await openServiceTab()

    await userEvent.click(await screen.findByRole('button', { name: 'Сбросить…' }))
    expect(await screen.findByText('research_sessions')).toBeInTheDocument()
    expect(screen.getByText('Итого: 53 строк, 8 файлов, 2.0 КБ')).toBeInTheDocument()
    expect(screen.getByText(/Не трогаем/)).toHaveTextContent('/data/hf')
  })

  it('сброс: отправляет запрос с фразой и закрывает окно', async () => {
    loginAs(TEST_ADMIN)
    const calls: { url: string; init: RequestInit }[] = []
    mockApi(
      routes({
        'POST /api/admin/reset': (url: string, init: RequestInit) => {
          calls.push({ url, init })
          return Promise.resolve(
            json({
              scope: 'data',
              dry_run: false,
              deleted_tables: { research_sessions: 4 },
              deleted_rows: 53,
              deleted_paths: ['/data/sessions'],
              freed_bytes: 2048,
              kept_paths: ['/data/hf'],
              includes_models: false,
            }),
          )
        },
      }),
    )
    await openServiceTab()

    await userEvent.click(await screen.findByRole('button', { name: 'Сбросить…' }))
    await userEvent.type(await screen.findByTestId('reset-confirm-input'), 'СБРОС ДАННЫХ')
    await userEvent.click(screen.getByRole('button', { name: 'Выполнить сброс' }))

    await waitFor(() => expect(calls).toHaveLength(1))
    expect(calls[0]?.url).toBe('/api/admin/reset')
    expect(JSON.parse(String(calls[0]?.init.body))).toEqual({
      scope: 'data',
      confirm: 'СБРОС ДАННЫХ',
      include_models: false,
    })
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
  })

  it('сброс: запрещён на боевом сервере', async () => {
    loginAs(TEST_ADMIN)
    mockApi(
      routes({
        'GET /api/admin/reset/preview': {
          ...RESET_PLAN,
          allowed: false,
          blocked_reason:
            'сброс состояния в prod запрещён: установите ALLOW_DESTRUCTIVE_RESET=true',
        },
      }),
    )
    await openServiceTab()

    expect(await screen.findByText(/ALLOW_DESTRUCTIVE_RESET/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Сбросить…' })).toBeDisabled()
  })

  it('сброс: галочка «кэш моделей» меняет план', async () => {
    loginAs(TEST_ADMIN)
    const urls: string[] = []
    mockApi({
      ...routes(),
      'GET /api/admin/reset/preview': (url: string) => {
        urls.push(url)
        return Promise.resolve(
          json(
            url.includes('include_models=true')
              ? { ...RESET_PLAN, includes_models: true, kept_paths: [] }
              : RESET_PLAN,
          ),
        )
      },
    })
    await openServiceTab()

    await userEvent.click(
      await screen.findByLabelText('Также удалить кэш моделей (HF/Torch)'),
    )
    await waitFor(() =>
      expect(urls.some((url) => url.includes('include_models=true'))).toBe(true),
    )
  })

  it('список обновляется по-боевому: копия появляется сразу после создания', async () => {
    // Регрессия: боевой QueryClient со staleTime=30s отличается от тестового.
    // Список обязан обновиться сам, без ручного нажатия «Обновить».
    loginAs(TEST_ADMIN)
    const NEW = { ...BACKUP, name: 'boasi-20261008-133000.tar.gz' }
    let created = false
    let gets = 0

    mockApi({
      ...routes(),
      'GET /api/admin/backup': () => {
        gets += 1
        return Promise.resolve(
          json({ backups: created ? [NEW, BACKUP] : [BACKUP], plan: PLAN }),
        )
      },
      'POST /api/admin/backup': () => {
        created = true
        return Promise.resolve(
          json({ entry: NEW, deleted_old: [], restore_hint: './scripts/restore.sh' }),
        )
      },
    })

    const queryClient = createQueryClient()
    render(
      <AppProviders initialPath="/admin" queryClient={queryClient}>
        <AppRoutes />
      </AppProviders>,
    )
    await userEvent.click(await screen.findByRole('tab', { name: 'Обслуживание' }))

    expect(await screen.findByText(BACKUP.name)).toBeInTheDocument()
    expect(screen.queryByText(NEW.name)).toBeNull()

    await userEvent.click(screen.getByRole('button', { name: 'Создать копию…' }))
    await userEvent.click(await screen.findByRole('button', { name: 'Создать' }))

    await waitFor(() => expect(screen.getByText(NEW.name)).toBeInTheDocument())
    expect(gets).toBeGreaterThan(1)
  })
})
