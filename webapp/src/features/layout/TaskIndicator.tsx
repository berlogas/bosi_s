/**
 * Индикатор задач в шапке — план Волны 2, п. 4.
 *
 * Indicator с числом активных задач + Popover со списком последних 5 и
 * отменой: фоновая задача не должна жить только на дашборде. Счётчик
 * обновляется через общий SSE-канал (`TaskEventsProvider`), laughing запрос —
 * снимок и страховочный опрос из `useActiveTasks`.
 */

import { Button, Indicator, Popover, Stack, Text } from '@mantine/core'
import { IconListCheck } from '@tabler/icons-react'
import { useNavigate } from 'react-router-dom'

import { TaskPanel } from '../../components/TaskPanel'
import { useActiveTasks, useCancelTask } from '../dashboard/queries'

const RECENT_LIMIT = 5

export function TaskIndicator() {
  const navigate = useNavigate()
  const { data: tasks } = useActiveTasks()
  const cancel = useCancelTask()

  const recent = (tasks ?? []).slice(0, RECENT_LIMIT)
  const count = tasks?.length ?? 0

  return (
    <Popover width={380} position="bottom" withinPortal withArrow shadow="md">
      <Popover.Target>
        <Indicator
          size={16}
          offset={4}
          color="info"
          withBorder
          disabled={count === 0}
          label={count || undefined}
        >
          <Button
            variant="default"
            size="compact-sm"
            px="xs"
            c="dimmed"
            leftSection={<IconListCheck size={16} stroke={1.5} />}
            aria-label={
              count > 0 ? `Активных задач: ${count}. Открыть список задач` : 'Задачи'
            }
          >
            Задачи
          </Button>
        </Indicator>
      </Popover.Target>
      <Popover.Dropdown>
        {count === 0 ? (
          <Text size="sm" c="dimmed">
            Активных задач нет.
          </Text>
        ) : (
          <Stack gap="xs">
            {recent.map((task) => (
              <TaskPanel
                key={task.id}
                task={task}
                onCancel={(target) => cancel.mutate(target.id)}
                cancelPending={cancel.isPending && cancel.variables === task.id}
              />
            ))}
            {count > RECENT_LIMIT && (
              <Text size="xs" c="dimmed">
                И ещё {count - RECENT_LIMIT} — полный список на информационной панели.
              </Text>
            )}
            <Button
              variant="subtle"
              size="compact-xs"
              style={{ alignSelf: 'flex-start' }}
              onClick={() => navigate('/')}
            >
              Все задачи — на информационной панели
            </Button>
          </Stack>
        )}
      </Popover.Dropdown>
    </Popover>
  )
}
