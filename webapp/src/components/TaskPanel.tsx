/**
 * Панель фоновой задачи — паритет `ui.task_panel` (Streamlit).
 *
 * Живая строка: этап тикает секундомером этапа и общим временем, проценты
 * обновляет владелец (поллинг задачи каждые 2 с). Плюс кнопка «Отменить» —
 * долгая операция не должна оставлять висящий спиннер.
 *
 * Панель «controlled»: `task` приходит снаружи, поэтому одна и та же
 * строка прогресса работает и на дашборде (список активных задач), и в
 * чате (опрос одной задачи до done/error/cancelled).
 */

import { useEffect, useRef, useState } from 'react'
import { Alert, Box, Button, Group, Progress, Stack, Text } from '@mantine/core'

import type { Task } from '../api/types'
import { fmtSeconds, taskStatusLabel } from '../lib/format'
import { StatusIcon } from './StatusIcon'

export function TaskPanel({
  task,
  onCancel,
  cancelPending = false,
}: {
  task: Task
  /** Отменить задачу; кнопка рисуется только при наличии колбэка. */
  onCancel?: (task: Task) => void
  cancelPending?: boolean
}) {
  const running = task.status === 'running' || task.status === 'queued'
  // Секундомер тикает локально: сервер присылает `seconds`/`stage_seconds`
  // только вместе с событием (SSE/опрос), а между ними прибавляем сами
  // от момента последнего обновления задачи. Дрифт — state, а не расчёт
  // в рендере: render должен оставаться чистым (react-hooks/purity).
  const [drift, setDrift] = useState(0)
  const receivedAt = useRef(0)
  useEffect(() => {
    receivedAt.current = Date.now()
    setDrift(0) // новое событие задачи — база заново с сервера
  }, [task])
  useEffect(() => {
    if (!running) return
    const tick = () => setDrift((Date.now() - receivedAt.current) / 1000)
    tick()
    const timer = setInterval(tick, 1000)
    return () => clearInterval(timer)
  }, [running])
  const stage = fmtSeconds(
    task.stage_seconds != null ? task.stage_seconds + drift : task.stage_seconds,
  )
  const total = fmtSeconds(task.seconds != null ? task.seconds + drift : task.seconds)

  return (
    <Stack gap="xs" py="xs" aria-busy={running ? 'true' : undefined}>
      <Group align="flex-start" wrap="nowrap">
        <Box style={{ flex: 1 }}>
          {running ? (
            <>
              <Progress
                value={Math.min(100, task.progress)}
                size="lg"
                aria-label={`${task.title}: ${task.progress}%`}
              />
              <Text size="sm" mt={4}>
                <StatusIcon status={task.status} />{' '}
                {[
                  task.step ?? '',
                  stage,
                  `(${task.progress}%)`,
                  total && `всего ${total}`,
                ]
                  .filter(Boolean)
                  .join(' · ')}
              </Text>
            </>
          ) : (
            <>
              <Text size="sm">
                <b>
                  <StatusIcon status={task.status} /> {task.title}
                </b>{' '}
                — {taskStatusLabel(task.status)}
              </Text>
              {task.step && (
                <Text size="xs" c="dimmed">
                  {task.step}
                </Text>
              )}
            </>
          )}
        </Box>

        {running && onCancel && (
          <Button
            size="xs"
            variant="light"
            loading={cancelPending}
            onClick={() => onCancel(task)}
          >
            {task.cancel_requested ? 'Отменяется…' : 'Отменить'}
          </Button>
        )}
      </Group>

      {task.status === 'error' && (
        <Alert color="error">{task.error || 'Задача завершилась с ошибкой'}</Alert>
      )}
      {task.status === 'cancelled' && <Alert color="warning">Задача отменена</Alert>}
      {task.status === 'done' && (
        <Alert color="success">
          Готово{task.seconds !== null ? ` за ${task.seconds} с` : ''}
        </Alert>
      )}
    </Stack>
  )
}
