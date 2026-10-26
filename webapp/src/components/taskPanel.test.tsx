/**
 * Панель задачи рисует иконку статуса как компонент, а не как значение.
 *
 * Регрессия: `STATUS_ICONS` перевели с эмодзи-строк на компоненты
 * `@tabler/icons-react`, а `TaskPanel` продолжал подставлять их в JSX как
 * строку — React падал с «Objects are not valid as a React child» на любом
 * завершённом вопросе (done/error/cancelled).
 */

import { MantineProvider } from '@mantine/core'
import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import type { Task, TaskStatus } from '../api/types'
import { TaskPanel } from './TaskPanel'

function task(status: TaskStatus, patch: Partial<Task> = {}): Task {
  return {
    id: 't-1',
    kind: 'chat',
    title: 'Вопрос: тест',
    status,
    progress: status === 'done' ? 100 : 55,
    step: status === 'running' || status === 'queued' ? 'генерация ответа' : null,
    error: status === 'error' ? 'Ollama недоступен' : null,
    cancel_requested: false,
    user_id: 'u-1',
    session_id: 's-1',
    project_id: null,
    created_at: '2026-10-07T09:00:00+00:00',
    started_at: '2026-10-07T09:00:01+00:00',
    finished_at: null,
    seconds: 12.5,
    stage_seconds: 3.2,
    result: null,
    ...patch,
  }
}

function renderPanel(value: Task) {
  return render(
    <MantineProvider>
      <TaskPanel task={value} />
    </MantineProvider>,
  )
}

describe('TaskPanel: иконка статуса', () => {
  it('running: этап, проценты и иконка-компонент', () => {
    const { container } = renderPanel(task('running'))

    expect(screen.getByText(/генерация ответа/)).toBeInTheDocument()
    expect(screen.getByText(/55%/)).toBeInTheDocument()
    expect(container.querySelector('svg')).not.toBeNull()
    expect(container.textContent).not.toContain('[object Object]')
  })

  it.each<TaskStatus>(['done', 'error', 'cancelled'])(
    '%s: заголовок и статус без падения рендера',
    (status) => {
      const { container } = renderPanel(task(status))

      expect(screen.getByText(/Вопрос: тест/)).toBeInTheDocument()
      expect(container.querySelector('svg')).not.toBeNull()
      expect(container.textContent).not.toContain('[object Object]')
    },
  )

  it('done: показывает «готово» и время', () => {
    renderPanel(task('done', { seconds: 42 }))

    expect(screen.getByText(/готово/)).toBeInTheDocument()
    expect(screen.getByText(/за 42 с/)).toBeInTheDocument()
  })

  it('error: текст ошибки в алерте', () => {
    renderPanel(task('error'))

    expect(screen.getByRole('alert')).toHaveTextContent('Ollama недоступен')
  })
})
