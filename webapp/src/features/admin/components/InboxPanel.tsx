/**
 * Папка-приёмник: состояние, кнопка запуска и журнал добавления (массовое добавление).
 *
 * Вынесено из монолитного AdminPageLegacy (Волна 5: разбивка AdminPage на компоненты).
 * Кнопка активна, только когда в папке есть принимаемые файлы. Отчёт хранится в БД,
 * поэтому виден после перезагрузки страницы и перезапуска контейнера.
 */

import { useState } from 'react'
import {
  Alert,
  Badge,
  Button,
  Group,
  Paper,
  Stack,
  Text,
} from '@mantine/core'
import { SkeletonList } from '../../../components/SkeletonList'
import {
  useClearJournal,
  useClearRejected,
  useInboxRuns,
  useInboxScan,
  useInboxStatus,
} from '../queries'
import type { InboxRun } from '../../../api/client'
import { fullWhen, shortWhen } from '../../../lib/format'

function errorText(cause: unknown, fallback: string): string {
  return cause instanceof Error ? cause.message : fallback
}

const INBOX_STATUS_LABEL: Record<string, string> = {
  discovered: 'обнаружен',
  parsed: 'распознан',
  indexed: 'проиндексирован',
  archived: 'в библиотеке',
  rejected: 'отклонён',
  failed: 'ошибка',
}

function InboxRunFiles({ run }: { run: InboxRun }) {
  const [opened, setOpened] = useState<string | null>(null)
  const files = run.files ?? []
  if (files.length === 0) return null

  return (
    <Stack gap={4}>
      {files.map((file) => {
        const bad = file.status === 'rejected' || file.status === 'failed'
        const label = INBOX_STATUS_LABEL[file.status] ?? file.status
        return (
          <Paper key={file.id} withBorder p="xs" bg={bad ? 'red.0' : undefined}>
            <Group justify="space-between" wrap="nowrap" gap="xs">
              <Text size="xs" style={{ flex: 1 }} truncate>
                {file.rel_path}
              </Text>
              <Badge
                size="xs"
                color={bad ? 'red' : file.status === 'archived' ? 'green' : 'gray'}
              >
                {label}
              </Badge>
              {file.reason_text && (
                <Button
                  size="compact-xs"
                  variant="subtle"
                  onClick={() => setOpened(opened === file.id ? null : file.id)}
                >
                  {opened === file.id ? 'скрыть причину' : 'почему?'}
                </Button>
              )}
            </Group>
            {opened === file.id && file.reason_text && (
              <Text size="xs" c="error" mt={4} role="note">
                {file.reason_text}
              </Text>
            )}
          </Paper>
        )
      })}
    </Stack>
  )
}

export function InboxPanel() {
  const status = useInboxStatus()
  const runs = useInboxRuns()
  const scan = useInboxScan()
  const clearRejected = useClearRejected()
  const clearJournal = useClearJournal()
  const [message, setMessage] = useState<string | null>(null)

  const usable = status.data?.usable_files ?? 0
  const unsupported = status.data?.unsupported_files ?? 0
  const busy = status.data?.busy ?? false
  const canScan = usable > 0 && !busy && !scan.isPending

  return (
    <Stack gap="sm">
      <Paper withBorder p="sm">
        <Group justify="space-between" wrap="nowrap" align="center">
          <Stack gap={2} style={{ flex: 1 }}>
            <Text size="sm">
              {status.isPending
                ? 'Проверяем папку-приёмник…'
                : status.isError
                  ? errorText(status.error, 'Не удалось проверить папку-приёмник')
                  : status.data?.exists
                    ? `В папке: ${status.data.files} (принимаемых ${usable}${
                        unsupported ? `, неподдерживаемых ${unsupported}` : ''
                      })`
                    : `Папка не найдена: ${status.data?.inbox_dir ?? ''}`}
            </Text>
            {status.data?.exists && (
              <Text size="xs" c="dimmed" style={{ wordBreak: 'break-all' }}>
                {status.data.inbox_dir}
              </Text>
            )}
          </Stack>
          <Button
            onClick={() => {
              setMessage(null)
              scan.mutate(undefined, {
                onSuccess: (result) => {
                  const run = result.run
                  setMessage(
                    `Готово: проиндексировано ${run.indexed}, отклонено ${run.rejected}, ошибок ${run.failed}.`,
                  )
                },
              })
            }}
            disabled={!canScan}
            loading={scan.isPending}
          >
            Запустить массовое добавление
          </Button>
        </Group>
        {message && (
          <Text size="sm" c="success" role="status" mt="xs">
            {message}
          </Text>
        )}
        {scan.isError && (
          <Alert color="error" role="alert" mt="xs">
            {errorText(scan.error, 'Ошибка запроса')}
          </Alert>
        )}
        {status.data?.exists === false && (
          <Text size="xs" c="dimmed" mt="xs">
            Создайте папку и проверьте монтирование в docker-compose.yml
            (./inbox:/data/inbox).
          </Text>
        )}
      </Paper>

      <Group justify="space-between">
        <Text fw={500}>Журнал добавления</Text>
        <Group gap="xs">
          <Button
            size="compact-xs"
            variant="subtle"
            color="red"
            loading={clearJournal.isPending}
            onClick={() => clearJournal.mutate()}
          >
            Очистить журнал
          </Button>
          <Button
            size="compact-xs"
            variant="subtle"
            loading={clearRejected.isPending}
            onClick={() => clearRejected.mutate()}
          >
            Очистить ошибочные
          </Button>
        </Group>
      </Group>
      {clearJournal.isSuccess && (
        <Text size="xs" c="success" role="status">
          {`Удалено прогонов: ${clearJournal.data.removed}`}
        </Text>
      )}
      {clearRejected.isSuccess && (
        <Text size="xs" c="success" role="status">
          {`Удалено файлов: ${clearRejected.data.removed}`}
        </Text>
      )}
      {runs.isPending && <SkeletonList count={3} />}
      {runs.isError && (
        <Alert color="error" role="alert">
          {errorText(runs.error, 'Не удалось загрузить журнал')}
        </Alert>
      )}
      {runs.data?.length === 0 && <Text c="dimmed">Прогонов пока не было.</Text>}
      {runs.data?.map((run) => (
        <Paper key={run.id} withBorder p="sm">
          <Group justify="space-between" wrap="nowrap">
            <Text size="sm" title={fullWhen(run.started_at)}>
              {shortWhen(run.started_at)}
            </Text>
            <Badge
              size="sm"
              color={
                run.status === 'done'
                  ? 'green'
                  : run.status === 'failed'
                    ? 'red'
                    : 'yellow'
              }
            >
              {run.status === 'done'
                ? 'завершён'
                : run.status === 'failed'
                  ? 'прерван'
                  : 'идёт'}
            </Badge>
          </Group>
          <Text size="xs" c="dimmed">
            {`принято ${run.archived}, заменено ${run.replaced}, отклонено ${run.rejected}, ошибок ${run.failed}`}
          </Text>
          {run.error && (
            <Text size="xs" c="error" role="note">
              {run.error}
            </Text>
          )}
          <InboxRunFiles run={run} />
        </Paper>
      ))}
    </Stack>
  )
}
