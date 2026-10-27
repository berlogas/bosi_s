/**
 * Страница «Глобальная база» админки.
 * SimpleTable + Drag&Drop загрузка + InboxPanel.
 */

import React from 'react'
import {
  Stack,
  Title,
  Text,
  Group,
  TextInput,
  Button,
  Alert,
  Progress,
  UnstyledButton,
} from '@mantine/core'
import { useRef, useState } from 'react'

import { useDocumentsPage } from './hooks/useDocumentsPage'
import { SimpleTable, DangerZone, InboxPanel } from '../components'

function errorTextLocal(cause: unknown, fallback: string): string {
  return cause instanceof Error ? cause.message : fallback
}

export default function DocumentsPage() {
  const {
    data,
    isLoading,
    isError,
    error,
    pagination,
    sorting,
    filters,
    setPagination,
    setSorting,
    setFilters,
    handleAddPath,
    handleUpload,
    handleDelete,
    handleReindex,
    addPath,
    upload,
    remove,
    reindex,
  } = useDocumentsPage()

  // Все хуки должны быть до любых early return
  const [path, setPath] = useState('')
  const [files, setFiles] = useState<File[]>([])
  const [dragOver, setDragOver] = useState(false)
  const [message, setMessage] = useState<string | null>(null)
  const [reindexDone, setReindexDone] = useState(false)
  const [uploadPercent, setUploadPercent] = useState<number | null>(null)
  const fileInput = useRef<HTMLInputElement>(null)

  // --- Колонки с рендерингом ячеек ---
  const customColumns = React.useMemo(() => [
    { id: 'title', accessorKey: 'title', header: 'Название' },
    { id: 'filename', accessorKey: 'filename', header: 'Файл' },
    {
      id: 'category',
      accessorKey: 'category',
      header: 'Категория',
      cell: (row: Record<string, unknown>) => String(row.category ?? '—'),
    },
    {
      id: 'status',
      accessorKey: 'status',
      header: 'Статус',
      cell: (row: Record<string, unknown>) => String(row.status ?? '—'),
    },
    {
      id: 'size_bytes',
      accessorKey: 'size_bytes',
      header: 'Размер (КБ)',
      cell: (row: Record<string, unknown>) =>
        Math.round((Number(row.size_bytes) || 0) / 1024),
    },
    {
      id: 'chunk_count',
      accessorKey: 'chunk_count',
      header: 'Чанков',
      cell: (row: Record<string, unknown>) => Number(row.chunk_count) || 0,
    },
    {
      id: 'tags',
      accessorKey: 'tags',
      header: 'Теги',
      cell: (row: Record<string, unknown>) => {
        const tags = row.tags as string[] | undefined
        return tags?.length ? tags.join(', ') : '—'
      },
    },
    {
      id: 'actions',
      header: '',
      cell: (row: { id: string | number }) => (
        <Group gap="xs" wrap="nowrap">
          <DangerZone
            confirmText="УДАЛИТЬ"
            onConfirm={() => handleDelete(String(row.id))}
            warning="Документ будет удалён безвозвратно."
          >
            <Button size="xs" variant="subtle" color="red">
              Удалить
            </Button>
          </DangerZone>
        </Group>
      ),
    },
  ], [handleDelete])

  if (isLoading) return <Text c="dimmed">Загрузка...</Text>
  if (isError) return <Alert color="red">{errorTextLocal(error, 'Ошибка загрузки')}</Alert>

  // --- Обработчики загрузки ---
  const handleAddPathSubmit = () => {
    setMessage(null)
    handleAddPath(path)
    setPath('')
  }

  const handleUploadFiles = () => {
    if (files.length === 0) return
    setMessage(null)
    setUploadPercent(0)
    handleUpload(files, '', setUploadPercent)
  }

  const onDrop = (event: React.DragEvent) => {
    event.preventDefault()
    setDragOver(false)
    const dropped = Array.from(event.dataTransfer.files)
    if (dropped.length > 0) setFiles((current) => [...current, ...dropped])
  }

  const onFileSelect = (event: React.ChangeEvent<HTMLInputElement>) => {
    const selected = Array.from(event.target.files ?? [])
    if (selected.length > 0) setFiles((current) => [...current, ...selected])
    event.target.value = ''
  }

  return (
    <Stack gap="sm">
      {message && (
        <Alert color="success" role="status">{message}</Alert>
      )}
      {addPath.isError && (
        <Alert color="error" role="alert">
          {errorTextLocal(addPath.error, 'Ошибка запроса')}
        </Alert>
      )}
      {upload.isError && (
        <Alert color="error" role="alert">
          {errorTextLocal(upload.error, 'Загрузка не удалась')}
        </Alert>
      )}
      {remove.isError && (
        <Alert color="error" role="alert">
          {errorTextLocal(remove.error, 'Не удалось удалить документ')}
        </Alert>
      )}
      {reindex.isError && (
        <Alert color="error" role="alert">
          {errorTextLocal(reindex.error, 'Ошибка запроса')}
        </Alert>
      )}

      {/* Добавить по пути */}
      <Group align="flex-end" gap="sm" wrap="nowrap">
        <TextInput
          label="Путь к файлу"
          value={path}
          onChange={(e) => setPath(e.currentTarget.value)}
          style={{ flex: 1 }}
        />
        <Button
          loading={addPath.isPending}
          disabled={!path.trim()}
          onClick={handleAddPathSubmit}
        >
          Добавить
        </Button>
      </Group>

      {/* Drag&Drop зона */}
      <UnstyledButton
        component="div"
        onClick={() => fileInput.current?.click()}
        onDragOver={(event) => {
          event.preventDefault()
          setDragOver(true)
        }}
        onDragLeave={() => setDragOver(false)}
        onDrop={onDrop}
        data-testid="admin-doc-dropzone"
        style={{
          border: `2px dashed ${dragOver ? 'var(--mantine-color-blue-filled)' : 'var(--mantine-color-default-border)'}`,
          borderRadius: 'var(--mantine-radius-md)',
          padding: 'var(--mantine-spacing-md)',
          textAlign: 'center',
          cursor: 'pointer',
          background: dragOver ? 'var(--mantine-color-blue-light)' : undefined,
        }}
      >
        <Text size="sm" c="dimmed">
          Перетащите файлы сюда или нажмите, чтобы выбрать
        </Text>
      </UnstyledButton>
      <input
        ref={fileInput}
        type="file"
        multiple
        hidden
        data-testid="admin-doc-file-input"
        onChange={onFileSelect}
      />

      {files.length > 0 && (
        <Group justify="space-between">
          <Text size="sm">
            Выбрано файлов: {files.length}{' '}
            <Text component="span" c="dimmed" size="xs">
              ({files.map((file) => file.name).join(', ')})
            </Text>
          </Text>
          <Group gap="xs">
            <Button
              variant="subtle"
              size="xs"
              onClick={() => setFiles([])}
              disabled={upload.isPending}
            >
              Очистить
            </Button>
            <Button
              onClick={handleUploadFiles}
              loading={upload.isPending}
              disabled={files.length === 0}
            >
              Загрузить файлы
            </Button>
          </Group>
        </Group>
      )}

      {upload.isPending && (
        <Stack gap={4}>
          <Progress
            value={uploadPercent ?? 0}
            aria-label="Прогресс загрузки файлов"
            data-testid="admin-upload-progress"
          />
          <Text size="sm" c="dimmed">
            {uploadPercent !== null && uploadPercent < 100
              ? `Отправляю файлы: ${uploadPercent}%…`
              : 'Файлы отправлены. Индексирую — это может занять минуты…'}
          </Text>
        </Stack>
      )}

      {/* Массовое добавление (inbox) */}
      <Title order={5}>Массовое добавление</Title>
      <Text size="sm" c="dimmed">
        Файлы кладутся в папку-приёмник, затем нажимается кнопка: backend проиндексирует
        их и перенесёт в постоянную библиотеку, а приёмник снова освободится.
      </Text>
      <InboxPanel />

      {/* Таблица документов */}
      <Group justify="space-between">
        <Title order={5}>Документы глобальной базы</Title>
        <Button
          color="warning"
          variant="light"
          size="xs"
          loading={reindex.isPending}
          onClick={() => {
            setReindexDone(false)
            handleReindex()
            setReindexDone(true)
          }}
        >
          Переиндексировать всё
        </Button>
      </Group>
      {reindexDone && (
        <Alert color="success" role="status">Готово.</Alert>
      )}
      {data.length === 0 && !isLoading && (
        <Text c="dimmed">Документов пока нет.</Text>
      )}
      {data.length > 0 && (
        <SimpleTable
          columns={customColumns as never}
          data={data as never}
          pagination={pagination}
          onPaginationChange={setPagination}
          sorting={sorting}
          onSortingChange={setSorting}
          filters={filters}
          onFiltersChange={setFilters}
          rowActions={() => null}
          isLoading={isLoading}
          emptyMessage="Документов пока нет."
        />
      )}
    </Stack>
  )
}