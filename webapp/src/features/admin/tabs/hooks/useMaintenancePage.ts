/** Хук страницы «Обслуживание»: бэкапы + сброс состояния. */

import { useState } from 'react'

import {
  useBackups,
  useCreateBackup,
  useDeleteBackup,
  useResetPreview,
  useResetState,
} from '../../queries'
import type { ResetScope } from '../../../../api/client'

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
  const [scope, setScope] = useState<ResetScope>('data')
  const [includeModels, setIncludeModels] = useState(false)

  const backups = useBackups()
  const create = useCreateBackup()
  const remove = useDeleteBackup()
  const plan = useResetPreview(scope, includeModels)
  const reset = useResetState()

  const current = RESET_SCOPES.find((item) => item.value === scope)
  const expected = plan.data?.confirmation ?? ''

  const handleCreateBackup = () => {
    void create.mutate()
  }

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
