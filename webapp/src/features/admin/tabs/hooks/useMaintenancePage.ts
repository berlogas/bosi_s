/** Хук страницы «Обслуживание»: бэкапы + сброс состояния. */

import { useEffect, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { notifications } from '@mantine/notifications'

import {
  adminKeys,
  useBackups,
  useCreateBackup,
  useDeleteBackup,
  useResetPreview,
  useResetState,
} from '../../queries'
import { useTask } from '../../../chat/queries'
import type { BackupEntry, ResetScope } from '../../../../api/client'

export const RESET_SCOPES = [
  {
    value: 'data',
    label: 'Данные (сессии, документы, проекты, переписка)',
    hint: 'Пользователи и аудит остаются. Документы нужно загрузить заново.',
  },
  {
    value: 'users',
    label: 'Данные и входы (+ refresh-токены)',
    hint: 'Все пользователи останутся, но им придётся войти заново.',
  },
  {
    value: 'all',
    label: 'Всё (полностью пустая платформа)',
    hint: 'Удаляются и учётные записи. После этого нужен docker compose exec backend python scripts/create_admin.py.',
  },
] as const

export function useMaintenancePage() {
  const queryClient = useQueryClient()
  const [scope, setScope] = useState<ResetScope>('data')
  const [includeModels, setIncludeModels] = useState(false)
  const [backupTaskId, setBackupTaskId] = useState<string | null>(null)

  const backups = useBackups()
  const create = useCreateBackup()
  const backupTask = useTask(backupTaskId)
  const backupBusy = create.isPending || backupTaskId !== null
  const remove = useDeleteBackup()
  const plan = useResetPreview(scope, includeModels)
  const reset = useResetState()

  const handleCreateBackup = () => {
    create.mutate(undefined, {
      onSuccess: ({ task_id }) => setBackupTaskId(task_id),
    })
  }

  const refetchBackups = backups.refetch

  useEffect(() => {
    const task = backupTask.data
    if (!backupTaskId || !task) return
    if (task.status === 'done') {
      const result = task.result as
        { entry?: BackupEntry; deleted_old?: string[] } | undefined
      // Сначала кладём готовую копию в кэш: даже если перезапрос не дойдёт,
      // пользователь сразу видит результат. Затем синхронизируем с сервером.
      queryClient.setQueryData<{ backups: BackupEntry[] }>(adminKeys.backups, (old) => {
        if (!old) return old
        const removed = new Set(result?.deleted_old ?? [])
        const kept = old.backups.filter(
          (item) => !removed.has(item.name) && item.name !== result?.entry?.name,
        )
        return {
          ...old,
          backups: result?.entry ? [result.entry, ...kept] : kept,
        }
      })
      void refetchBackups()
      notifications.show({
        title: 'Копия создана',
        message: result?.entry?.name ?? 'Резервная копия появилась в списке',
        color: 'green',
      })
      setBackupTaskId(null)
    } else if (task.status === 'error' || task.status === 'cancelled') {
      notifications.show({
        title: 'Не удалось создать копию',
        message: task.error ?? 'Задача отменена',
        color: 'red',
      })
      setBackupTaskId(null)
    }
  }, [backupTask.data, backupTaskId, queryClient, refetchBackups])

  useEffect(() => {
    if (backupTask.isError && backupTaskId) {
      notifications.show({
        title: 'Не удалось получить статус копии',
        message:
          backupTask.error instanceof Error
            ? backupTask.error.message
            : 'Задача могла быть потеряна после перезапуска backend',
        color: 'red',
      })
      setBackupTaskId(null)
    }
  }, [backupTask.isError, backupTask.error, backupTaskId])

  const current = RESET_SCOPES.find((item) => item.value === scope)
  const expected = plan.data?.confirmation ?? ''

  const handleDeleteBackup = (name: string) => {
    void remove.mutate(name)
  }

  const handleReset = (expectedValue: string, includeModelsVal: boolean) => {
    void reset.mutate({
      scope,
      confirm: expectedValue,
      include_models: includeModelsVal,
    })
  }

  const handleScopeChange = (value: ResetScope) => {
    setScope(value)
  }

  return {
    backups,
    create,
    backupTask,
    backupBusy,
    remove,
    plan,
    scope,
    setScope: handleScopeChange,
    handleScopeChange,
    includeModels,
    setIncludeModels,
    current,
    expected,
    phrase: '',
    setPhrase: () => {},
    handleCreateBackup,
    handleDeleteBackup,
    handleReset,
  }
}
