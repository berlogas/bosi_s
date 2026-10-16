/**
 * Регрессия: «Продолжить» открывает пустое окно.
 *
 * `useSaveState` сохраняет активную вкладку в точку возврата (PUT /state) и
 * вливает ответ в кэш `sessionDetail`. Ответ PUT — это SessionOut, у которого
 * нет `summary`. Если detail ещё не загружен, такая запись подменяла кэш
 * объектом без `summary`, и `SessionPage` падал на `session.summary.documents`:
 * React размонтировал дерево и страница оставалась пустой до F5.
 *
 * Гонка «ответ PUT раньше GET detail» и делала баг «иногда».
 */

import { QueryClient } from '@tanstack/react-query'
import { describe, expect, it } from 'vitest'

import { queryKeys } from '../dashboard/queries'
import { applySaveState } from './queries'

/** Ответ PUT /state — SessionOut: без summary, days_left, writable. */
const SESSION_OUT = {
  id: 's-1',
  user_id: 'u-1',
  title: 'Баренцево море',
  status: 'active',
  state_snapshot: { tab: 'chat' },
}

/** Ответ GET /api/sessions/{id} — SessionDetailOut: с summary. */
const SESSION_DETAIL = {
  ...SESSION_OUT,
  days_left: 84,
  writable: true,
  summary: { documents: 2, documents_limit: 50 },
}

describe('точка возврата: ответ PUT /state не подменяет detail', () => {
  it('detail ещё не загружен — не создаём запись без summary', () => {
    const client = new QueryClient()

    applySaveState(client, 's-1', SESSION_OUT)

    expect(client.getQueryData(queryKeys.sessionDetail('s-1'))).toBeUndefined()
  })

  it('detail загружен — вливаем поля, summary сохраняется', () => {
    const client = new QueryClient()
    client.setQueryData(queryKeys.sessionDetail('s-1'), SESSION_DETAIL)

    applySaveState(client, 's-1', {
      ...SESSION_OUT,
      state_snapshot: { tab: 'projects' },
      resume_note: 'не забыть',
    })

    const cached = client.getQueryData<typeof SESSION_DETAIL & { resume_note?: string }>(
      queryKeys.sessionDetail('s-1'),
    )
    expect(cached?.summary).toEqual({ documents: 2, documents_limit: 50 })
    expect(cached?.days_left).toBe(84)
    expect(cached?.state_snapshot).toEqual({ tab: 'projects' })
    expect(cached?.resume_note).toBe('не забыть')
  })
})