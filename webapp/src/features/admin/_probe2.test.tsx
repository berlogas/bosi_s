import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient } from '@tanstack/react-query'
import { describe, expect, it, beforeEach, afterEach, vi } from 'vitest'

import { AppProviders } from '../../app/AppProviders'
import { AppRoutes } from '../../routes'
import { json, loginAs, mockApi, resetAuth, TEST_ADMIN } from '../../test/helpers'

const PLAN = {
  data_dir: '/data', backup_dir: 'N:\Development\boasi_s\backups', files: 26,
  source_bytes: 1, source_human: '1 МБ', estimated_bytes: 2,
  estimated_human: '2 МБ', free_bytes: 100, free_human: '100 МБ',
  existing: 6, keep: 14, db_exists: true, warning: 'w',
}
const ITEMS = [
  'boasi-20261008-185604.tar.gz', 'boasi-20261008-185251.tar.gz',
  'boasi-20261008-125119.tar.gz', 'boasi-20261008-111900.tar.gz',
  'boasi-20261008-105625.tar.gz', 'boasi-20261008-124917.tar.gz',
].map((name, i) => ({
  name, bytes: 385000 - i * 1000, human_size: `${376 - i}.1 КБ`,
  created_at: `2026-10-08T1${8 - i}:5${i}:00+00:00`,
  has_sha256: true, has_manifest: true,
}))

beforeEach(() => sessionStorage.clear())
afterEach(() => { vi.unstubAllGlobals(); resetAuth() })

describe('таблица копий', () => {
  it('показывает все строки', async () => {
    loginAs(TEST_ADMIN)
    mockApi({
      'GET /api/health': { status: 'ok', llm_model: 'm', embedding_model: 'e', ollama: {} },
      'GET /api/tasks': { tasks: [], active: 0 },
      'GET /api/sessions': [],
      'GET /api/admin/users': [],
      'GET /api/admin/audit': [],
      'GET /api/admin/documents': [],
      'GET /api/admin/backup': json({ backups: ITEMS, plan: PLAN }),
      'GET /api/admin/reset/preview': json({
        scope: 'data', tables: {}, rows: 0, paths: [], files: 0, total_bytes: 0,
        kept_paths: [], includes_models: false, allowed: true,
        blocked_reason: null, confirmation: 'X',
      }),
    })
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })
    render(<AppProviders initialPath="/admin" queryClient={qc}><AppRoutes /></AppProviders>)
    await userEvent.click(await screen.findByRole('tab', { name: 'Обслуживание' }))
    await screen.findByText(ITEMS[0].name)

    for (const item of ITEMS) {
      console.log(item.name, '->', screen.queryAllByText(item.name).length)
    }
    const table = screen.getByRole('table')
    console.log('строк в tbody:', within(table).getAllByRole('row').length - 1)
    expect(within(table).getAllByRole('row').length - 1).toBe(6)
  })
})
