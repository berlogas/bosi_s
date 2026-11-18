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
  Modal,
  Progress,
  UnstyledButton,
} from '@mantine/core'
import { useRef, useState } from 'react'

import { useDocumentsPage } from './hooks/useDocumentsPage'
import { EmptyState } from '../../../components/EmptyState'
import { IconDatabase } from '@tabler/icons-react'
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
    handleReindexDocument,
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
  /** Окно подтверждения замены прежних версий документов с теми же именами. */
  const [replaceOpen, setReplaceOpen] = useState(false)
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
      cell: (row: { id: string | number; path?: string | null }) => (
        <Group gap="xs" wrap="nowrap">
          {row.path && (
            <Button
              size="xs"
              variant="subtle"
              onClick={() => handleReindexDocument(String(row.path))}
              title="Переиндексировать документ (после смены настроек индексации)"
            >
              Переиндексировать
            </Button>
          )}
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
  ], [handleDelete, handleReindexDocument])

  // Об успешном добавлении сообщаем сами: мутация молча уходила в сервер,
  // и админ не видел, что документ добавился. Эффект — до ранних возвратов,
  // иначе порядок хуков ломается при перерисовке.
  React.useEffect(() => {
    if (addPath.isSuccess && addPath.data) setMessage('Добавлено.')
  }, [addPath.isSuccess, addPath.data])

  if (isLoading) return <Text c="dimmed">Загрузка...</Text>
  if (isError) return <Alert color="red">{errorTextLocal(error, 'Ошибка загрузки')}</Alert>

  // --- Обработчики загрузки ---
  const handleAddPathSubmit = () => {
    setMessage(null)
    handleAddPath(path)
    setPath('')
  }

  /**
   * Файлы с теми же именами, что уже есть в базе.
   *
   * Дедуп PaperQA идёт по содержимому: изменённый файл получил бы другой
   * dockey и лёг бы вторым документом, а старая версия осталась бы в индексе.
   * Поэтому перед загрузкой спрашиваем, заменять ли прежние версии.
   */
  const conflictingNames = files
    .map((file) => file.name)
    .filter((name) => data.some((doc) => doc.filename === name))

  const startUpload = (replace: boolean) => {
    setMessage(null)
    setUploadPercent(0)
    handleUpload(files, '', setUploadPercent, replace)
    setFiles([])
    setReplaceOpen(false)
  }

  const handleUploadFiles = () => {
    if (files.length === 0) return
    // Есть файлы с именами, которые уже в базе: спросим, заменять ли их.
    if (conflictingNames.length > 0) {
      setReplaceOpen(true)
      return
    }
    startUpload(false)
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

      {/* Итог загрузки: сколько добавили, сколько дубликатов и что не разобрали. */}
      {upload.data && (
        <Alert
          color={upload.data.failed?.length ? 'yellow' : 'success'}
          title="Итог загрузки"
          role="status"
        >
          <Stack gap={2}>
            <Text size="sm">
              {`Добавлено: ${upload.data.added?.length ?? 0}`}
              {upload.data.duplicates?.length
                ? `, дубликатов: ${upload.data.duplicates.length}`
                : ''}
              {upload.data.failed?.length
                ? `, с ошибкой: ${upload.data.failed.length}`
                : ''}
            </Text>
            {(upload.data.failed ?? []).map((item) => (
              <Text key={item.name} size="xs" c="dimmed">
                {`${item.name}: ${item.error}`}
              </Text>
            ))}
          </Stack>
        </Alert>
      )}

      {/* Замена прежней версии документа с тем же именем. */}
      <Modal
        opened={replaceOpen}
        onClose={() => setReplaceOpen(false)}
        title="Заменить прежние версии?"
        centered
      >
        <Stack>
          <Text size="sm">
            В базе уже есть файлы с теми же именами. Загрузка заменит их:
            прежние версии исчезнут из индекса, новые займут их место.
          </Text>
          <Stack gap={2}>
            {conflictingNames.map((name) => (
              <Text key={name} size="sm" fw={500}>
                {name}
              </Text>
            ))}
          </Stack>
          <Group justify="flex-end">
            <Button variant="default" onClick={() => setReplaceOpen(false)}>
              Отмена
            </Button>
            <Button onClick={() => startUpload(true)}>
              Заменить и загрузить
            </Button>
          </Group>
        </Stack>
      </Modal>
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
          background: dragOver ? 'var(--mantine-color-blue-light)' : 'transparent',
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
        <EmptyState
          title="Документов пока нет"
          description="Загрузите файлы через зону выше или добавьте по пути к файлу."
          action={<Button>Загрузить файл</Button>}
          icon={<IconDatabase size={32} />}
        />
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