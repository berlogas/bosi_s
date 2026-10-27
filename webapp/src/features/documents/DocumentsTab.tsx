/**
 * Вкладка «Документы» — паритет `documents_tab` из workspace.py.
 *
 * Верх: добавление по пути (категория, путь, теги) и dropzone
 * (@mantine/dropzone с валидацией форматов и размера). Низ: список,
 * сгруппированный по категориям в аккордеонах — размер, чанки, теги,
 * dockey, удаление. Пока идёт индексация — панели активных задач сессии.
 *
 * Допустимые форматы и лимиты совпадают с backend (config.py:
 * allowed_extensions, upload_max_mb).
 */

import {
  Accordion,
  Alert,
  Badge,
  Button,
  Drawer,
  Group,
  Progress,
  Select,
  Stack,
  Table,
  Text,
  TextInput,
} from '@mantine/core'
import { Dropzone, DropzoneProps } from '@mantine/dropzone'
import { TagsInput } from '@mantine/core'
import { notifications } from '@mantine/notifications'
import {
  createColumnHelper,
  getCoreRowModel,
  getSortedRowModel,
  getFilteredRowModel,
  useReactTable,
  type PaginationState,
  type SortingState,
} from '@tanstack/react-table'
import { useMemo, useState } from 'react'

import type { DocumentOut } from '../../api/types'
import { ConfirmDeleteModal } from '../../components/ConfirmDeleteModal'
import { TaskPanel } from '../../components/TaskPanel'
import { categoryLabel } from '../../lib/format'
import {
  useAddDocumentByPath,
  useDeleteDocument,
  useSessionDocuments,
  useSessionIndexingTasks,
  useUploadDocuments,
} from './queries'

/** CATEGORIES workspace.py (без глобальной — та только у админа). */
export const CATEGORIES = [
  'temp_literature',
  'project_data',
  'project_draft',
  'notes',
  'supplementary',
] as const

const CATEGORY_OPTIONS = CATEGORIES.map((value) => ({
  value,
  label: categoryLabel(value),
}));

/** Допустимые расширения — синхронно с backend config.py allowed_extensions. */
const ALLOWED_EXTENSIONS = [
  '.pdf',
  '.txt',
  '.md',
  '.html',
  '.htm',
  '.docx',
  '.xlsx',
  '.pptx',
  '.csv',
  '.tsv',
  '.json',
  '.yaml',
  '.yml',
  '.py',
] as const

/** Максимальный размер одного файла — синхронно с backend upload_max_mb (200 МБ). */
const MAX_FILE_SIZE_MB = 200
const MAX_FILE_SIZE = MAX_FILE_SIZE_MB * 1024 * 1024

/** MIME-типы для атрибута accept dropzone. */
const ACCEPT_MAP: Record<string, string> = {
  '.pdf': 'application/pdf',
  '.txt': 'text/plain',
  '.md': 'text/markdown',
  '.html': 'text/html',
  '.htm': 'text/html',
  '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
  '.xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  '.pptx': 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
  '.csv': 'text/csv',
  '.tsv': 'text/tab-separated-values',
  '.json': 'application/json',
  '.yaml': 'application/yaml',
  '.yml': 'application/yaml',
  '.py': 'text/x-python',
}

// ------------------------------------------------------------------- таблица
/** Таблица документов с сортировкой и пагинацией — показывается при >20 документов. */
function DocumentsTable({
  documents,
  readOnly,
  onDelete,
  setSelectedDoc,
}: {
  documents: DocumentOut[]
  readOnly: boolean
  onDelete: (document: DocumentOut) => void
  setSelectedDoc: (doc: DocumentOut) => void
}) {
  const [pagination, setPagination] = useState<PaginationState>({
    pageIndex: 0,
    pageSize: 25,
  })
  const [sorting, setSorting] = useState<SortingState>([
    { id: 'title', desc: false },
  ])

  const columnHelper = createColumnHelper<DocumentOut>()

  const columns = [
    columnHelper.accessor('title', {
      header: 'Название',
      cell: (info) => info.getValue() || info.row.original.docname,
    }),
    columnHelper.accessor('category', {
      header: 'Категория',
      cell: (info) => categoryLabel(info.getValue()),
    }),
    columnHelper.accessor('status', {
      header: 'Статус',
      cell: (info) => {
        const status = info.getValue() ?? '—'
        return <Badge size="xs">{status}</Badge>
      },
    }),
    columnHelper.accessor('chunk_count', {
      header: 'Чанков',
      cell: (info) => String(info.getValue() ?? 0),
    }),
    columnHelper.accessor('size_bytes', {
      header: 'Объём',
      cell: (info) => {
        const bytes = info.getValue() ?? 0
        if (bytes < 1024) return `${bytes} Б`
        if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} КБ`
        return `${(bytes / (1024 * 1024)).toFixed(1)} МБ`
      },
    }),
    columnHelper.accessor('tags', {
      header: 'Метки',
      cell: (info) => info.getValue()?.join(', ') || '—',
    }),
    columnHelper.accessor('dockey', {
      header: 'Dockey',
      cell: (info) => info.getValue()?.slice(0, 8) || '—',
    }),
    columnHelper.accessor('id', {
      id: 'actions',
      header: '',
      cell: (info) => {
        const doc = info.row.original
        return (
          <Group gap="xs">
            <Button
              size="compact-xs"
              variant="subtle"
              disabled={readOnly}
              onClick={() => setSelectedDoc(doc)}
              aria-label={`Подробнее: ${doc.title || doc.docname}`}
            >
              Подробнее
            </Button>
            <Button
              size="compact-xs"
              color="error"
              variant="subtle"
              disabled={readOnly}
              onClick={() => onDelete(doc)}
            >
              Удалить
            </Button>
          </Group>
        )
      },
    }),
  ]

  const table = useReactTable({
    data: documents,
    columns,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getFilteredRowModel: getFilteredRowModel(),
    initialState: {
      pagination,
      sorting,
    },
    state: {
      pagination,
      sorting,
    },
    onPaginationChange: setPagination,
    onSortingChange: (updater) => {
      const next = typeof updater === 'function' ? updater(sorting) : updater
      setSorting(next ?? [])
    },
  })

  const pageCount = Math.max(1, Math.ceil(documents.length / pageSize))
  const safePageIndex = Math.min(pagination.pageIndex, pageCount - 1)

  return (
    <div style={{ overflowX: 'auto', minWidth: '100%' }}>
      <Table>
        <thead>
          {table.getHeaderGroups().map((headerGroup) => (
            <tr key={headerGroup.id}>
              {headerGroup.headers.map((header) => {
                const canSort = header.column.getCanSort()
                return (
                  <th
                    key={header.id}
                    onClick={canSort ? header.column.getToggleSortingHandler() : undefined}
                    style={{
                      cursor: canSort ? 'pointer' : 'default',
                      userSelect: 'none',
                      padding: '8px 12px',
                      borderBottom: '2px solid #ddd',
                      textAlign: 'left',
                      background: '#f5f5f5',
                    }}
                  >
                    {header.isPlaceholder ? null : (
                      <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                        {header.renderHeader()}
                        {canSort && header.column.getIsSorted() && (
                          <span>
                            {header.column.getIsSorted() === 'desc' ? '▼' : '▲'}
                          </span>
                        )}
                      </div>
                    )}
                  </th>
                )
              })}
            </tr>
          ))}
        </thead>
        <tbody>
          {table.getRowModel().rows.length === 0 ? (
            <tr>
              <td colSpan={columns.length} style={{ textAlign: 'center', padding: '2rem', color: '#999' }}>
                Документов не найдено.
              </td>
            </tr>
          ) : (
            table.getRowModel().rows.map((row) => (
              <tr key={row.id}>
                {row.getVisibleCells().map((cell) => (
                  <td
                    key={cell.id}
                    style={{
                      padding: '8px 12px',
                      borderBottom: '1px solid #eee',
                    }}
                  >
                    {cell.renderCell()}
                  </td>
                ))}
              </tr>
            ))
          )}
        </tbody>
      </Table>

      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          marginTop: '1rem',
          flexWrap: 'wrap',
          gap: '0.5rem',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
          <button
            style={{
              padding: '4px 8px',
              border: '1px solid #ddd',
              background: 'white',
              borderRadius: 4,
              cursor: 'pointer',
            }}
            disabled={table.getPageIndex() === 0}
            onClick={() =>
              setPagination({
                ...table.getPageState(),
                pageIndex: table.getPageIndex() - 1,
              })
            }
          >
            ◀ Назад
          </button>
          <span style={{ minWidth: '80px', textAlign: 'center', display: 'inline-block' }}>
            {table.getPageIndex() + 1} / {pageCount}
          </span>
          <button
            style={{
              padding: '4px 8px',
              border: '1px solid #ddd',
              background: 'white',
              borderRadius: 4,
              cursor: 'pointer',
            }}
            disabled={table.getPageIndex() >= pageCount - 1}
            onClick={() =>
              setPagination({
                ...table.getPageState(),
                pageIndex: table.getPageIndex() + 1,
              })
            }
          >
            Вперед ▶
          </button>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', color: '#999', fontSize: 14 }}>
          <span>Всего: {documents.length}</span>
        </div>
      </div>
    </div>
  )
}

// ------------------------------------------------------------------- детали документа
/** Drawer справа с деталями документа: показать вместо раскрытия строки. */
function DocumentDetailDrawer({
  opened,
  document,
  onClose,
}: {
  opened: boolean
  document: DocumentOut | null
  onClose: () => void
}) {
  if (!document || !opened) return null

  return (
    <Drawer
      opened={opened}
      onClose={onClose}
      title={`Документ: ${document.title || document.docname}`}
      size="500px"
      withCloseButton
    >
      <Stack gap="sm">
        <Group>
          <Text size="sm" fw={500}>Название:</Text>
          <Text size="sm">{document.title || document.docname}</Text>
        </Group>
        <Group>
          <Text size="sm" fw={500}>Категория:</Text>
          <Badge size="xs">{categoryLabel(document.category ?? '—')}</Badge>
        </Group>
        <Group>
          <Text size="sm" fw={500}>Статус:</Text>
          <Badge size="xs">{document.status ?? '—'}</Badge>
        </Group>
        <Group>
          <Text size="sm" fw={500}>Чанков:</Text>
          <Text size="sm">{document.chunk_count ?? 0}</Text>
        </Group>
        <Group>
          <Text size="sm" fw={500}>Объём:</Text>
          <Text size="sm">
            {(() => {
              const bytes = document.size_bytes ?? 0
              if (bytes < 1024) return `${bytes} Б`
              if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} КБ`
              return `${(bytes / (1024 * 1024)).toFixed(1)} МБ`
            })()}
          </Text>
        </Group>
        {document.dockey && (
          <Group>
            <Text size="sm" fw={500}>Dockey:</Text>
            <Text size="xs" c="dimmed" ff="monospace">
              {document.dockey}
            </Text>
          </Group>
        )}
        {document.tags && document.tags.length > 0 && (
          <Group>
            <Text size="sm" fw={500}>Теги:</Text>
            <Text size="sm">{document.tags.join(', ')}</Text>
          </Group>
        )}
        {document.citation && (
          <Group>
            <Text size="sm" fw={500}>Цитата:</Text>
            <Text size="xs" c="dimmed">{document.citation}</Text>
          </Group>
        )}
      </Stack>
    </Drawer>
  )
}

interface DocumentsTabProps {
  sessionId: string
  readOnly: boolean
}

export function DocumentsTab({ sessionId, readOnly }: DocumentsTabProps) {
  const [category, setCategory] = useState<string>('all')
  const [path, setPath] = useState('')
  const [tags, setTags] = useState<string[]>([])
  const [files, setFiles] = useState<File[]>([])
  const [formError, setFormError] = useState<string | null>(null)
  const [uploadResult, setUploadResult] = useState<string | null>(null)
  /** % отправленных байтов при загрузке (XHR onprogress); null — не идёт. */
  const [uploadPercent, setUploadPercent] = useState<number | null>(null)
  /** Построчные ошибки при приёме файлов в dropzone: имя файла → причина. */
  const [rejectErrors, setRejectErrors] = useState<Record<string, string>>({})
  /** Документ, удаление которого подтверждаем. */
  const [deleteAsk, setDeleteAsk] = useState<DocumentOut | null>(null)
  const [deleteError, setDeleteError] = useState<string | null>(null)
  /** Документ, детали которого показываются в Drawer справа. */
  const [selectedDoc, setSelectedDoc] = useState<DocumentOut | null>(null)

  const documents = useSessionDocuments(sessionId)
  const tasks = useSessionIndexingTasks(sessionId)
  const addByPath = useAddDocumentByPath(sessionId)
  const upload = useUploadDocuments(sessionId)
  const remove = useDeleteDocument(sessionId)

  // ---------------------------------------------------------------- добавить по пути
  function handleAddPath() {
    setFormError(null)
    addByPath.mutate(
      { path: path.trim(), category: category === 'all' ? undefined : category, tags },
      {
        onSuccess: () => {
          setPath('')
          setTags([])
        },
        onError: (cause) =>
          setFormError(cause instanceof Error ? cause.message : 'Не удалось добавить'),
      },
    )
  }

  // ---------------------------------------------------------------- загрузка файлов
  function handleUpload() {
    if (files.length === 0) return
    setFormError(null)
    setUploadResult(null)
    setUploadPercent(0)
    upload.mutate(
      {
        files,
        category: category === 'all' ? undefined : category,
        tags: tags.join(', '),
        onProgress: setUploadPercent,
      },
      {
        onSuccess: (result) => {
          setUploadResult(
            `Добавлено: ${result.added?.length ?? 0}, ошибок: ${result.failed?.length ?? 0}`,
          )
          setFiles([])
          setRejectErrors({})
        },
        onError: (cause) =>
          setFormError(cause instanceof Error ? cause.message : 'Загрузка не удалась'),
        onSettled: () => setUploadPercent(null),
      },
    )
  }

  /** Удалить файл из выбранных перед загрузкой. */
  function removeFile(file: File) {
    setFiles((current) => current.filter((f) => f !== file))
    setRejectErrors((prev) => {
      const next = { ...prev }
      delete next[file.name]
      return next
    })
  }

  /** Валидация файла перед добавлением в список. */
  function validateFile(file: File): string | null {
    const ext = '.' + file.name.split('.').pop()?.toLowerCase()
    if (!ext || !ALLOWED_EXTENSIONS.includes(ext as (typeof ALLOWED_EXTENSIONS)[number])) {
      return `Неподдерживаемый тип файла: ${ext || '(без расширения)'}`
    }
    if (file.size > MAX_FILE_SIZE) {
      return `Превышен размер ${MAX_FILE_SIZE_MB} МБ`
    }
    return null
  }

  // ---------------------------------------------------------------- dropzone
  const getAccept = (): DropzoneProps['accept'] => {
    const map: Record<string, string[]> = {}
    for (const ext of ALLOWED_EXTENSIONS) {
      const mime = ACCEPT_MAP[ext]
      if (!map[mime]) map[mime] = []
      map[mime].push(ext)
    }
    return map
  }

  const onReject = (event: React.DragEvent, rejectedFiles: File[]) => {
    const next: Record<string, string> = {}
    for (const file of rejectedFiles) {
      const reason = validateFile(file)
      if (reason) next[file.name] = reason
    }
    setRejectErrors((prev) => ({ ...prev, ...next }))
  }

  /** Фильтруем документы по выбранной категории. */
  const filteredDocs = useMemo(() => {
    const docs = documents.data ?? []
    if (category === 'all') return docs
    return docs.filter((d) => d.category === category)
  }, [documents.data, category])

  /** Группировка по категориям для аккордеона. */
  const grouped = useMemo(() => {
    const groups = new Map<string, DocumentOut[]>()
    for (const document of filteredDocs) {
      const key = document.category || 'notes'
      const bucket = groups.get(key)
      if (bucket) bucket.push(document)
      else groups.set(key, [document])
    }
    return [...groups.entries()]
  }, [filteredDocs])

  const liveTasks = (tasks.data ?? []).filter(
    (task) => task.status === 'running' || task.status === 'queued',
  )

  const showEmpty = filteredDocs.length === 0 && documents.isSuccess
  const showAccordion = filteredDocs.length > 0 && filteredDocs.length <= 20
  const showTable = filteredDocs.length > 20

  return (
    <Stack gap="sm">
      <Text fw={600}>Документы</Text>

      {formError && (
        <Alert color="error" role="alert">
          {formError}
        </Alert>
      )}
      {showEmpty && (
        <Text size="sm" c="dimmed">
          Документов пока нет.
        </Text>
      )}
      {uploadResult && <Alert color="success">{uploadResult}</Alert>}

      {Object.values(rejectErrors).length > 0 && (
        <Alert color="yellow" role="alert">
          <Stack gap="xs">
            {Object.entries(rejectErrors).map(([name, reason]) => (
              <Text key={name} size="sm" c="dimmed">
                {name}: {reason}
              </Text>
            ))}
          </Stack>
        </Alert>
      )}

      {/* прогресс индексации: пока задачи живы — панель с этапами */}
      {liveTasks.map((task) => (
        <TaskPanel key={task.id} task={task} />
      ))}

      <Group align="flex-end" gap="sm">
        <Select
          label="Категория"
          data={[
            { value: 'all', label: 'Все категории' },
            ...CATEGORY_OPTIONS,
          ]}
          value={category}
          onChange={(value) => setCategory(value ?? 'temp_literature')}
          disabled={readOnly}
          allowDeselect={false}
          w={220}
        />
        <TextInput
          label="Путь к файлу на диске"
          value={path}
          onChange={(event) => setPath(event.currentTarget.value)}
          disabled={readOnly}
          style={{ flex: 1 }}
        />
        <TagsInput
          label="Теги"
          placeholder="Теги через запятую"
          data={tags}
          onChange={(values) => setTags(values)}
          disabled={readOnly}
          style={{ flex: 1 }}
          maxWidth={320}
        />
        <Button
          onClick={handleAddPath}
          disabled={readOnly || !path.trim()}
          loading={addByPath.isPending}
        >
          Добавить
        </Button>
      </Group>

      <Dropzone
        accept={getAccept()}
        maxSize={MAX_FILE_SIZE}
        onReject={onReject}
        onDrop={(event, acceptedFiles) => {
          if (readOnly) return
          const newFiles: File[] = []
          for (const file of acceptedFiles) {
            const reason = validateFile(file)
            if (reason) {
              setRejectErrors((prev) => ({ ...prev, [file.name]: reason }))
            } else {
              newFiles.push(file)
              setRejectErrors((prev) => {
                const next = { ...prev }
                delete next[file.name]
                return next
              })
            }
          }
          if (newFiles.length > 0) setFiles((current) => [...current, ...newFiles])
        }}
        disabled={readOnly}
        style={{
          minHeight: 120,
          borderRadius: 'var(--mantine-radius-md)',
        }}
      >
        {({ dropzoneProps, dropzoneState, getRootProps, getInputProps }) => (
          <>
            <div
              {...getRootProps({
                ...dropzoneProps,
                onClick: () => !readOnly && getInputProps().onClick(),
              })}
              data-testid="doc-dropzone"
              aria-disabled={readOnly}
              style={{
                border: `2px dashed ${
                  dropzoneState.dragOver
                    ? 'var(--mantine-color-blue-filled)'
                    : 'var(--mantine-color-default-border)'
                }`,
                borderRadius: 'var(--mantine-radius-md)',
                padding: 'var(--mantine-spacing-md)',
                textAlign: 'center',
                cursor: readOnly ? 'not-allowed' : 'pointer',
                background: dropzoneState.dragOver
                  ? 'var(--mantine-color-blue-light)'
                  : undefined,
                opacity: readOnly ? 0.6 : 1,
              }}
            >
              <Text size="sm" c="dimmed">
                Перетащите файлы сюда или нажмите, чтобы выбрать
              </Text>
              <input {...getInputProps()} data-testid="doc-file-input" />
            </div>
            {dropzoneState.dragOver && (
              <Text size="xs" c="blue" mt="xs">
                Отпустите, чтобы добавить файлы
              </Text>
            )}
          </>
        )}
      </Dropzone>

      {files.length > 0 && (
        <Group justify="space-between" wrap="wrap">
          <Stack gap="xs">
            <Text size="sm">
              Выбрано файлов: {files.length}
            </Text>
            <Text component="span" c="dimmed" size="xs">
              ({files.map((file) => file.name).join(', ')})
            </Text>
          </Stack>
          <Group gap="xs">
            {files.map((file) => (
              <Group key={file.name} gap="xs" style={{ alignItems: 'center' }}>
                <Text size="xs" c="dimmed" style={{ whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', maxWidth: 180 }}>
                  {file.name} — {(file.size / 1024).toFixed(0)} КБ
                </Text>
                <Button
                  size="xs"
                  variant="subtle"
                  color="error"
                  disabled={upload.isPending}
                  onClick={() => removeFile(file)}
                  aria-label={`Удалить ${file.name} из 선택ки`}
                >
                  ×
                </Button>
              </Group>
            ))}
            <Button
              variant="subtle"
              size="xs"
              onClick={() => setFiles([])}
              disabled={upload.isPending}
            >
              Очистить всё
            </Button>
            <Button
              onClick={handleUpload}
              loading={upload.isPending}
              disabled={readOnly || files.length === 0}
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
            data-testid="upload-progress"
          />
          <Text size="sm" c="dimmed">
            {uploadPercent !== null && uploadPercent < 100
              ? `Отправляю файлы: ${uploadPercent}%…`
              : 'Файлы отправлены. Индексирую — это может занять минуты…'}
          </Text>
        </Stack>
      )}

      {documents.isError && (
        <Alert color="error" role="alert">
          {documents.error instanceof Error
            ? documents.error.message
            : 'Не удалось загрузить список документов'}
        </Alert>
      )}

      {filteredDocs.length === 0 && !documents.isPending && (
        <Text size="sm" c="dimmed">
          Документов пока нет.
        </Text>
      )}

      {showAccordion ? (
        <>
          {/* Аккордеон — для небольших списков, группировка по категориям */}
          <Accordion
            key={grouped.map(([key]) => key).join('|')}
            defaultValue={grouped.map(([key]) => key)}
            multiple
          >
            {grouped.map(([group, items]) => {
              const filteredItems = category === 'all'
                ? items
                : items.filter((d) => d.category === category)
              if (filteredItems.length === 0) return null
              return (
                <Accordion.Item key={group} value={group}>
                  <Accordion.Control>
                    <Text size="sm">
                      {categoryLabel(group)} ({filteredItems.length})
                    </Text>
                  </Accordion.Control>
                  <Accordion.Panel>
                    <Stack gap="xs">
                      {filteredItems.map((document) => (
                        <Group
                          key={document.id ?? document.dockey}
                          justify="space-between"
                        >
                          <Stack gap={2}>
                            <Text size="sm">
                              {document.title || document.docname} —{' '}
                              {((document.size_bytes ?? 0) / 1024).toFixed(0)} КБ,{' '}
                              {document.chunk_count ?? 0} чанков
                              {document.status === 'error' && (
                                <Text component="span" c="error" size="xs">
                                  {' '}
                                  · ошибка индексации
                                </Text>
                              )}
                            </Text>
                            {document.tags && document.tags.length > 0 && (
                              <Text size="xs" c="dimmed">
                                теги: {document.tags.join(', ')}
                              </Text>
                            )}
                          </Stack>
                          <Group gap="xs">
                            {document.dockey && (
                              <Text size="xs" c="dimmed" ff="monospace">
                                {document.dockey.slice(0, 8)}
                              </Text>
                            )}
                            <Button
                              size="compact-xs"
                              variant="subtle"
                              disabled={readOnly}
                              onClick={() => setSelectedDoc(document)}
                              aria-label={`Подробнее: ${document.title || document.docname}`}
                            >
                              Подробнее
                            </Button>
                            <Button
                              size="compact-xs"
                              color="error"
                              variant="subtle"
                              disabled={readOnly}
                              loading={remove.isPending && remove.variables === document.id}
                              onClick={() => {
                                setDeleteError(null)
                                setDeleteAsk(document)
                              }}
                            >
                              Удалить
                            </Button>
                          </Group>
                        </Group>
                      ))}
                    </Stack>
                  </Accordion.Panel>
                </Accordion.Item>
              )
            })}
          </Accordion>
        </>
      ) : null}

      {showTable ? (
        <DocumentsTable
          documents={filteredDocs}
          readOnly={readOnly}
          onDelete={(document) => {
            setDeleteError(null)
            setDeleteAsk(document)
          }}
          setSelectedDoc={setSelectedDoc}
        />
      ) : null}

      <DocumentDetailDrawer
        opened={selectedDoc !== null}
        document={selectedDoc!}
        onClose={() => setSelectedDoc(null)}
      />

      <ConfirmDeleteModal
        opened={deleteAsk !== null}
        title="Удалить документ?"
        subject={
          <>
            Документ <b>«{deleteAsk?.title || deleteAsk?.docname}»</b> будет удалён из
            сессии вместе с чанками.
          </>
        }
        error={deleteError}
        loading={remove.isPending && remove.variables === deleteAsk?.id}
        onCancel={() => {
          if (!remove.isPending) setDeleteAsk(null)
        }}
        onConfirm={() => {
          if (!deleteAsk?.id) return
          remove.mutate(deleteAsk.id, {
            onSuccess: () => setDeleteAsk(null),
            onError: (cause) =>
              setDeleteError(
                cause instanceof Error ? cause.message : 'Не удалось удалить документ',
              ),
          })
        }}
      />
    </Stack>
  )
}
