/**
 * Хук для страницы «Обслуживание» админки: бэкапы и сброс состояния.
 * URL-параметры имеют префикс `maint_`.
 */

import React, { useCallback } from 'react'
import { useSearchParams } from 'react-router-dom'

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
    hint: 'Удаляются и учётные записи. После этого нужен make create-admin.',
  },
] as const

const PARAM_PREFIX = 'maint_'

function getParam(searchParams: URLSearchParams, key: string): string | null {
  return searchParams.get(`${PARAM_PREFIX}${key}`)
}

function setParam(searchParams: URLSearchParams, key: string, value: string | null) {
  const fullKey = `${PARAM_PREFIX}${key}`
  if (value) searchParams.set(fullKey, value)
  else searchParams.delete(fullKey)
}

export function useMaintenancePage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const backups = useBackups()
  const create = useCreateBackup()
  const remove = useDeleteBackup()

  const [scope, setScope] = React.useState<ResetScope>(
    (getParam(searchParams, 'scope') as ResetScope) || 'data'
  )
  const [includeModels, setIncludeModels] = React.useState(false)

  const plan = useResetPreview(scope, includeModels)
  const reset = useResetState()

  const current = RESET_SCOPES.find((item) => item.value === scope)
  const expected = plan.data?.confirmation ?? ''
  const canReset = Boolean(expected) && !reset.isPending

  const handleScopeChange = useCallback((value: string) => {
    setScope(value as ResetScope)
    const params = new URLSearchParams(searchParams)
    setParam(params, 'scope', value)
    setSearchParams(params, { replace: true })
  }, [searchParams, setSearchParams])

  const handleCreateBackup = useCallback(() => {
    create.mutate(undefined)
  }, [create])

  const handleDeleteBackup = useCallback(
    (name: string) => {
      remove.mutate(name)
    },
    [remove]
  )

  const handleReset = useCallback(
    (confirm: string, include_models: boolean) => {
      reset.mutate(
        { scope, confirm, include_models: include_models },
        { onSuccess: () => setScope('data') }
      )
    },
    [reset, scope]
  )

  return {
    backups,
    create,
    remove,
    plan,
    reset,
    scope,
    includeModels,
    setIncludeModels,
    current,
    expected,
    canReset,
    RESET_SCOPES,
    handleCreateBackup,
    handleDeleteBackup,
    handleReset,
    handleScopeChange,
  }
}