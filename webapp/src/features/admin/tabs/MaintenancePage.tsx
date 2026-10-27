/**
 * Страница «Обслуживание» админки (бэкапы, сброс).
 * Бэкапы/сброс с DangerZone.
 */

import React from 'react'
import {
  Stack,
  Title,
  Text,
  Group,
  Select,
  Button,
  Alert,
  Paper,
  Checkbox,
} from '@mantine/core'

import { useMaintenancePage, RESET_SCOPES } from './hooks/useMaintenancePage'
import { SimpleTable } from '../components'
import { DangerZone } from '../components'
import { shortWhen, fullWhen } from '../../../lib/format'

function errorText(cause: unknown, fallback: string): string {
  return cause instanceof Error ? cause.message : fallback
}

export default function MaintenancePage() {
  const {
    backups,
    create,
    remove,
    plan,
    scope,
    includeModels,
    setIncludeModels,
    current,
    expected,
    canReset,
    handleCreateBackup,
    handleDeleteBackup,
    handleReset,
    handleScopeChange,
  } = useMaintenancePage()

  // Все useMemo до early return
  const backupColumns = React.useMemo(() => [
    { id: 'name', accessorKey: 'name', header: 'Копия' },
    {
      id: 'human_size',
      accessorKey: 'human_size',
      header: 'Размер',
      cell: (row: { human_size: string }) => row.human_size,
    },
    {
      id: 'created_at',
      accessorKey: 'created_at',
      header: 'Создана',
      cell: (row: { created_at: string }) => {
        const v = row.created_at
        return v ? <span title={fullWhen(v)}>{shortWhen(v)}</span> : '—'
      },
    },
    {
      id: 'actions',
      header: '',
      cell: (row: { name: string }) => (
        <Group gap="xs" wrap="nowrap">
          <DangerZone
            confirmText={row.name}
            onConfirm={() => handleDeleteBackup(row.name)}
            warning="Резервную копию восстановить нельзя."
          >
            <Button size="xs" variant="subtle" color="red">
              Удалить
            </Button>
          </DangerZone>
        </Group>
      ),
    },
  ], [handleDeleteBackup])

  if (backups.isLoading) return <Text c="dimmed">Загрузка...</Text>
  if (backups.isError) {
    return <Alert color="red">{errorText(backups.error, 'Ошибка загрузки')}</Alert>
  }

  const items = backups.data?.backups ?? []
  const planInfo = backups.data?.plan

  return (
    <Stack gap="sm">
      <Title order={3}>Обслуживание</Title>

      {/* ====== Резервные копии ====== */}
      <Title order={4}>Резервные копии</Title>

      <Alert color="info" title="Копия снимается на сервере">
        Архив содержит базу данных (согласованный снимок), файлы сессий и документов и
        манифест с ревизией схемы. Копии складываются в каталог{' '}
        <code>{planInfo?.backup_dir ?? '—'}</code> — он намеренно вынесен за пределы
        данных, иначе копия попала бы сама в себя.
      </Alert>

      {planInfo?.db_exists === false && (
        <Alert color="error" role="alert">
          База данных не найдена — копия получится без данных. Проверьте, что платформа
          видит свой каталог данных.
        </Alert>
      )}

      {planInfo && (
        <Paper withBorder p="sm">
          <Text size="sm">
            Данные: <code>{planInfo.data_dir}</code> · файлов: {planInfo.files} ·{' '}
            {planInfo.source_human}
          </Text>
          <Text size="sm">
            Копия займёт около {planInfo.estimated_human}
            {planInfo.free_human ? `, свободно на диске ${planInfo.free_human}` : ''}
          </Text>
          <Text size="sm" c="dimmed">
            Хранится копий:{' '}
            {planInfo.keep === 0 ? 'без ограничения' : `последние ${planInfo.keep}`}
            (сейчас {planInfo.existing}); при создании новой более старые удаляются
            автоматически.
          </Text>
        </Paper>
      )}

      <Group>
        <Button
          onClick={handleCreateBackup}
          disabled={backups.isPending || planInfo?.db_exists === false}
        >
          Создать копию…
        </Button>
        <Button
          variant="default"
          onClick={() => void backups.refetch()}
          loading={backups.isFetching}
        >
          Обновить
        </Button>
      </Group>

      {create.isError && (
        <Alert color="error" role="alert">
          {errorText(create.error, 'Не удалось создать копию')}
        </Alert>
      )}

      {items.length > 0 && (
        <SimpleTable
          columns={backupColumns as never}
          data={items as never}
          pagination={{ pageIndex: 0, pageSize: 50, pageCount: 1 }}
          onPaginationChange={() => {}}
          sorting={[]}
          onSortingChange={() => {}}
          filters={[]}
          onFiltersChange={() => {}}
          rowActions={() => null}
          isLoading={backups.isPending}
          emptyMessage="Копий пока нет."
        />
      )}
      {items.length === 0 && backups.isSuccess && (
        <Text size="sm" c="dimmed" role="status">Копий пока нет.</Text>
      )}
      {remove.isError && (
        <Alert color="error" role="alert">
          {errorText(remove.error, 'Не удалось удалить копию')}
        </Alert>
      )}

      <Alert color="warning" title="Восстановление — только скриптом">
        Восстановление требует остановки платформы, поэтому из браузера его делать
        нельзя. После копии выполните в корне проекта:
        <code> ./scripts/restore.sh путь/к/архиву.tar.gz</code>
      </Alert>

      {/* ====== Сброс состояния ====== */}
      <Title order={4}>Сброс состояния</Title>

      <Alert color="warning" title="Сброс необратим">
        Удалённые сессии, документы и переписка восстановить нельзя — только из бэкапа (
        <code>make backup</code>). Сначала посмотрите план.
      </Alert>

      <Select
        label="Что сбросить"
        data={RESET_SCOPES.map((item) => ({ value: item.value, label: item.label }))}
        value={scope}
        onChange={(value) => value && handleScopeChange(value)}
        allowDeselect={false}
        w={520}
      />
      {current && (
        <Text size="sm" c="dimmed">{current.hint}</Text>
      )}

      <Checkbox
        label="Также удалить кэш моделей (HF/Torch)"
        description="Обычно НЕ нужно: без него после сброса платформа не сможет считать эмбеддинги в оффлайне, пока модель не будет скачана заново."
        checked={includeModels}
        onChange={(event) => setIncludeModels(event.currentTarget.checked)}
      />

      {plan.isPending && <Text c="dimmed">Считаем план сброса…</Text>}
      {plan.isError && (
        <Alert color="error" role="alert">
          {errorText(plan.error, 'Ошибка запроса')}
        </Alert>
      )}
      {plan.data && !plan.data.allowed && (
        <Alert color="error" role="alert">
          Сброс запрещён: {plan.data.blocked_reason}
        </Alert>
      )}

      {plan.data && plan.data.allowed && (
        <Paper withBorder p="sm">
          <Stack gap="xs">
            <Text fw={600}>Будет удалено</Text>
            <SimpleTable
              columns={[
                { id: 'table', header: 'Таблица', cell: (row: { table: string }) => row.table },
                { id: 'rows', header: 'Строк', cell: (row: { rows: number }) => row.rows },
              ] as never}
              data={Object.entries(plan.data.tables).map(([table, rows]) => ({
                id: table,
                table,
                rows,
              })) as never}
              pagination={{ pageIndex: 0, pageSize: 100, pageCount: 1 }}
              onPaginationChange={() => {}}
              sorting={[]}
              onSortingChange={() => {}}
              filters={[]}
              onFiltersChange={() => {}}
              rowActions={() => null}
              emptyMessage="Нет таблиц для удаления."
            />
            {plan.data.paths.map((item) => (
              <Text key={item.path} size="sm">
                <code>{item.path}</code> — {item.files} файлов,{' '}
                {humanBytes(item.bytes)}
              </Text>
            ))}
            <Text size="sm" fw={600}>
              Итого: {plan.data.rows} строк, {plan.data.files} файлов,{' '}
              {humanBytes(plan.data.total_bytes)}
            </Text>
            {plan.data.kept_paths.length > 0 && (
              <Text size="sm" c="dimmed">
                Не трогаем: {plan.data.kept_paths.join(', ')} (кэш моделей — нужен для
                эмбеддингов).
              </Text>
            )}
          </Stack>
        </Paper>
      )}

      <Group>
        <DangerZone
          confirmText={expected}
          onConfirm={() => handleReset(expected, includeModels)}
          warning="Сброс необратим. Восстановление возможно только из резервной копии."
        >
          <Button color="error" disabled={!plan.data?.allowed || !canReset}>
            Сбросить…
          </Button>
        </DangerZone>
      </Group>
    </Stack>
  )
}

function humanBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} Б`
  const units = ['КБ', 'МБ', 'ГБ']
  let value = bytes / 1024
  let unit = 0
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024
    unit += 1
  }
  return `${value.toFixed(1)} ${units[unit]}`
}