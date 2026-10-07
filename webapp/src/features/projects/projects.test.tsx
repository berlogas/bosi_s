/**
 * Тесты вкладки «Проекты» (Фаза 3, паритет project_editor.py):
 * создание, выбор, статус, разделы (черновик → сохранить), генерация,
 * привязка документов, пустой список, read-only архива.
 */

import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient } from '@tanstack/react-query'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { AppProviders } from '../../app/AppProviders'
import { AppRoutes } from '../../routes'
import { loginAs, mockApi, resetAuth } from '../../test/helpers'

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

const DETAIL = {
  ...SESSION,
  writable: true,
  days_left: 84,
  summary: {
    documents: 1,
    documents_limit: 50,
    storage_bytes: 0,
    storage_limit_bytes: 524288000,
  },
}

const PROJECT = {
  id: 'p-1',
  session_id: 's-1',
  title: 'Статья о приливах',
  target_journal: 'ICES',
  status: 'planning',
  sections: [],
  created_at: '2026-10-01T00:00:00+00:00',
  updated_at: '2026-10-01T00:00:00+00:00',
}

const SECTION = {
  name: 'Introduction',
  required: true,
  order: 1,
  word_target: 600,
  notes: '',
  content_md: 'Серверный текст',
  words: 3,
  written: false,
}

const DOC = {
  id: 'd-1',
  dockey: 'abcd1234',
  docname: 'doc',
  title: 'Отчёт',
  category: 'temp_literature',
}

function renderApp(path = '/s/s-1/projects') {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  })
  return render(
    <AppProviders initialPath={path} queryClient={queryClient}>
      <AppRoutes />
    </AppProviders>,
  )
}

function mockProjectsApi(routes: Record<string, unknown> = {}) {
  return mockApi({
    'GET /api/health': HEALTH,
    'GET /api/sessions/s-1': DETAIL,
    'GET /api/sessions': [SESSION],
    'GET /api/tasks': { tasks: [], active: 0 },
    'GET /api/chat/messages': { messages: [], total: 0, offset: 0 },
    'GET /api/sessions/s-1/documents': [DOC],
    'GET /api/sessions/s-1/projects': [PROJECT],
    'GET /api/sessions/s-1/projects/p-1/sections': [SECTION],
    'GET /api/sessions/s-1/projects/p-1/documents': [],
    'GET /api/sessions/s-1/projects/p-1/progress': {
      project_id: 'p-1',
      status: 'planning',
      sections: 5,
      written: 1,
      words: 3,
      percent: 20,
    },
    ...routes,
  })
}

beforeEach(() => {
  sessionStorage.clear()
  loginAs()
})

afterEach(() => {
  vi.unstubAllGlobals()
  resetAuth()
})

describe('вкладка Проекты', () => {
  it('пустой список — «Проектов нет — создайте первый»', async () => {
    mockProjectsApi({ 'GET /api/sessions/s-1/projects': [] })

    renderApp()

    expect(
      await screen.findByText('Проектов нет — создайте первый.'),
    ).toBeInTheDocument()
  })

  it('создание проекта уходит с названием и журналом', async () => {
    const { calls } = mockProjectsApi({
      'GET /api/sessions/s-1/projects': [],
      'POST /api/sessions/s-1/projects': {
        ...PROJECT,
        id: 'p-new',
        title: 'Новый проект',
      },
      'GET /api/sessions/s-1/projects/p-new/sections': [],
      'GET /api/sessions/s-1/projects/p-new/documents': [],
      'GET /api/sessions/s-1/projects/p-new/progress': {
        project_id: 'p-new',
        sections: 0,
        written: 0,
        words: 0,
        percent: 0,
      },
    })

    renderApp()
    await screen.findByText('Проектов нет — создайте первый.')

    await userEvent.type(screen.getByLabelText('Название'), 'Новый проект')
    await userEvent.type(screen.getByLabelText('Целевой журнал'), 'ICES')
    await userEvent.click(screen.getByRole('button', { name: 'Создать' }))

    await waitFor(() => {
      const call = calls.find(
        (c) => c.url.endsWith('/projects') && c.init.method === 'POST',
      )
      expect(call).toBeDefined()
      expect(JSON.parse(String(call?.init.body))).toEqual({
        title: 'Новый проект',
        target_journal: 'ICES',
      })
    })
  })

  it('выбор проекта показывает прогресс, статус и раздел', async () => {
    mockProjectsApi()

    renderApp()

    expect(await screen.findByText(/1\/5 разделов/)).toBeInTheDocument()
    expect(screen.getByText(/3 слов/)).toBeInTheDocument()
    expect(screen.getByLabelText('Статус', { selector: 'input' })).toHaveValue(
      'planning',
    )
    // раздел из API, черновик берётся из серверного content_md
    const area = await screen.findByLabelText('Текст раздела: Introduction')
    expect(area).toHaveValue('Серверный текст')
  })

  it('правка раздела живёт в черновике и сохраняется PUT-ом', async () => {
    const { calls } = mockProjectsApi({
      'PUT /api/sessions/s-1/projects/p-1/sections/Introduction': {
        ...SECTION,
        content_md: 'Новый черновик',
        words: 2,
      },
    })

    renderApp()
    const area = await screen.findByLabelText('Текст раздела: Introduction')

    await userEvent.clear(area)
    await userEvent.type(area, 'Новый черновик')
    // черновик сразу в sessionStorage (паритет state.drafts)
    expect(sessionStorage.getItem('boasi.project.drafts')).toContain('Новый черновик')

    const sectionCard = area.closest('.mantine-Accordion-panel')
    await userEvent.click(
      within(sectionCard as HTMLElement).getByRole('button', { name: 'Сохранить' }),
    )

    await waitFor(() => {
      const call = calls.find(
        (c) => c.init.method === 'PUT' && c.url.includes('/sections/'),
      )
      expect(call).toBeDefined()
      expect(JSON.parse(String(call?.init.body))).toEqual({
        content_md: 'Новый черновик',
      })
    })
    expect(await screen.findByText('Раздел сохранён.')).toBeInTheDocument()
  })

  it('генерация раздела: спиннер → результат под разделом', async () => {
    mockProjectsApi({
      'POST /api/sessions/s-1/projects/p-1/generate': {
        project_id: 'p-1',
        section: 'Introduction',
        content_md: 'Сгенерированный текст [1].',
        word_count: 4,
        sources: [],
        references: ['[1] Отчёт'],
        citations_ok: false,
        warnings: ['Нет методики'],
        seconds: 1.5,
        from_cache: false,
      },
    })

    renderApp()
    const area = await screen.findByLabelText('Текст раздела: Introduction')
    const sectionCard = area.closest('.mantine-Accordion-panel')

    await userEvent.click(
      within(sectionCard as HTMLElement).getByRole('button', { name: 'Сгенерировать' }),
    )

    // parитет _generate: текст, предупреждение о ссылках и ⚠ warnings
    expect(await screen.findByText(/Сгенерированный текст/)).toBeInTheDocument()
    expect(
      screen.getByText('Проверьте ссылки: часть из них не разрешается в источники.'),
    ).toBeInTheDocument()
    expect(screen.getByText(/⚠ Нет методики/)).toBeInTheDocument()
    expect(screen.getByText(/Отчёт/)).toBeInTheDocument()
  })

  it('статус проекта сохраняется PATCH-ом', async () => {
    const { calls } = mockProjectsApi({
      'PATCH /api/sessions/s-1/projects/p-1': { ...PROJECT, status: 'drafting' },
    })

    renderApp()
    await screen.findByText(/1\/5 разделов/)

    // jsdom: listbox Mantine остаётся display:none — ищем option с hidden
    await userEvent.click(screen.getByLabelText('Статус', { selector: 'input' }))
    await userEvent.click(
      await screen.findByRole('option', { name: 'drafting', hidden: true }),
    )
    await userEvent.click(screen.getByRole('button', { name: 'Обновить' }))

    await waitFor(() => {
      const call = calls.find((c) => c.init.method === 'PATCH')
      expect(call).toBeDefined()
      expect(JSON.parse(String(call?.init.body))).toEqual({ status: 'drafting' })
    })
  })

  it('привязка документа уходит с ролью, отвязка — DELETE', async () => {
    const { calls } = mockProjectsApi({
      'GET /api/sessions/s-1/projects/p-1/documents': [{ document: DOC, role: 'data' }],
    })

    renderApp()

    expect(await screen.findByText(/Отчёт — роль: data/)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Отвязать' }))
    await waitFor(() =>
      expect(
        calls.some(
          (c) =>
            c.init.method === 'DELETE' && c.url.includes('/projects/p-1/documents/d-1'),
        ),
      ).toBe(true),
    )
  })

  it('разбор черновика: пробелы списком (паритет _generate_panel)', async () => {
    mockProjectsApi({
      'GET /api/sessions/s-1/projects/p-1/draft-analysis': {
        has_gaps: true,
        gaps: [
          {
            severity: 'high',
            where: 'Methods',
            hint: 'Раздел «Methods» не написан.',
            excerpt: '',
          },
        ],
        by_severity: { high: 1, medium: 0, low: 0 },
      },
    })

    renderApp()
    await screen.findByText(/1\/5 разделов/)

    await userEvent.click(screen.getByRole('button', { name: 'Разбор черновика' }))

    expect(
      await screen.findByText(/Найдено пробелов: 1 \(критичных 1\)/),
    ).toBeInTheDocument()
    expect(screen.getByText(/Methods.*не написан/)).toBeInTheDocument()
  })

  it('архивная сессия: редактирование заблокировано', async () => {
    mockProjectsApi({
      'GET /api/sessions/s-1': { ...DETAIL, status: 'archived', writable: false },
    })

    renderApp()

    expect(await screen.findByText(/1\/5 разделов/)).toBeInTheDocument()
    expect(screen.getByLabelText('Название')).toBeDisabled()
    expect(screen.getByLabelText('Статус', { selector: 'input' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Создать' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Обновить' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Удалить' })).toBeDisabled()
    const area = await screen.findByLabelText('Текст раздела: Introduction')
    expect(area).toBeDisabled()
    expect(screen.queryByRole('button', { name: 'Сохранить' })).toBeDisabled()
  })
})
