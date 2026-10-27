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
  Group,
  Modal,
  Progress,
  Select,
  Stack,
  Table,
  Text,
  TextInput,
} from '@mantine/core'
import { Dropzone } from '@mantine/dropzone'
import { TagsInput } from '@mantine/core'
import { notifications } from '@mantine/notifications'
import { useMemo, useState, useRef } from 'react'
import { useSearchParams } from 'react-router-dom'

import type { DocumentOut } from '../../api/types'
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
/** Простая таблица документов с сортировкой и пагинацией — показывается при >20 документов. */
function DocumentsTable({
  documents,
  readOnly,
  onDelete,
  setSelectedDoc,
  pageIndex,
  pageSize,
  sortId,
  sortDesc,
  onPageChange,
  onSortChange,
}: {
  documents: DocumentOut[]
  readOnly: boolean
  onDelete: (document: DocumentOut) => void
  setSelectedDoc: (doc: DocumentOut) => void
  pageIndex: number
  pageSize: number
  sortId: string
  sortDesc: boolean
  onPageChange: (next: { pageIndex: number; pageSize: number }) => void
  onSortChange: (next: { id: string; desc: boolean }) => void
}) {
  // Сортировка
  const sorted = [...documents].sort((a, b) => {
    const aVal = (a as any)[sortId] ?? ''
    const bVal = (b as any)[sortId] ?? ''
    const comparison = String(aVal).localeCompare(String(bVal))
    return sortDesc ? -comparison : comparison
  })

  const pageCount = Math.max(1, Math.ceil(sorted.length / pageSize))
  const safePage = Math.min(Math.max(pageIndex, 0), pageCount - 1)
  const pageData = sorted.slice(safePage * pageSize, (safePage + 1) * pageSize)

  const headers: Array<{ key: string; label: string }> = [
    { key: 'title', label: 'Название' },
    { key: 'category', label: 'Категория' },
    { key: 'status', label: 'Статус' },
    { key: 'chunk_count', label: 'Чанков' },
    { key: 'size_bytes', label: 'Объём' },
    { key: 'tags', label: 'Метки' },
    { key: 'dockey', label: 'Dockey' },
    { key: 'actions', label: '' },
  ]

  return (
    <div style={{ overflowX: 'auto', minWidth: '100%' }}>
      <Table>
        <thead>
          <tr>
            {headers.map((h) => (
              <th
                key={h.key}
                onClick={
                  h.key !== 'actions'
                    ? () => onSortChange({ id: h.key, desc: sortId === h.key ? !sortDesc : false })
                    : undefined
                }
                style={{
                  cursor: h.key !== 'actions' ? 'pointer' : 'default',
                  userSelect: 'none',
                  padding: 'var(--mantine-spacing-xs) var(--mantine-spacing-sm)',
                  borderBottom: '2px solid var(--mantine-color-default-border)',
                  textAlign: 'left',
                  background: 'var(--mantine-color-gray-0)',
                }}
              >
                {h.label}
                {sortId === h.key && (
                  <span style={{ marginLeft: 'var(--mantine-spacing-xs)' }}>
                    {sortDesc ? '▼' : '▲'}
                  </span>
                )}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {pageData.length === 0 ? (
            <tr>
              <td
                colSpan={headers.length}
                style={{
                  textAlign: 'center',
                  padding: 'var(--mantine-spacing-xl)',
                  color: 'var(--mantine-color-dimmed)',
                }}
              >
                Документов не найдено.
              </td>
            </tr>
          ) : (
            pageData.map((document) => (
              <tr key={document.id ?? document.dockey}>
                <td style={{ padding: 'var(--mantine-spacing-xs) var(--mantine-spacing-sm)', borderBottom: '1px solid var(--mantine-color-default-border)' }}>
                  {document.title || document.docname}
                </td>
                <td style={{ padding: 'var(--mantine-spacing-xs) var(--mantine-spacing-sm)', borderBottom: '1px solid var(--mantine-color-default-border)' }}>
                  {categoryLabel(document.category)}
                </td>
                <td style={{ padding: 'var(--mantine-spacing-xs) var(--mantine-spacing-sm)', borderBottom: '1px solid var(--mantine-color-default-border)' }}>
                  <Badge size="xs">{document.status ?? '—'}</Badge>
                </td>
                <td style={{ padding: 'var(--mantine-spacing-xs) var(--mantine-spacing-sm)', borderBottom: '1px solid var(--mantine-color-default-border)' }}>
                  {document.chunk_count ?? 0}
                </td>
                <td style={{ padding: 'var(--mantine-spacing-xs) var(--mantine-spacing-sm)', borderBottom: '1px solid var(--mantine-color-default-border)' }}>
                  {(() => {
                    const bytes = document.size_bytes ?? 0
                    if (bytes < 1024) return `${bytes} Б`
                    if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} КБ`
                    return `${(bytes / (1024 * 1024)).toFixed(1)} МБ`
                  })()}
                </td>
                <td style={{ padding: 'var(--mantine-spacing-xs) var(--mantine-spacing-sm)', borderBottom: '1px solid var(--mantine-color-default-border)' }}>
                  {document.tags?.join(', ') || '—'}
                </td>
                <td style={{ padding: 'var(--mantine-spacing-xs) var(--mantine-spacing-sm)', borderBottom: '1px solid var(--mantine-color-default-border)' }}>
                  {document.dockey?.slice(0, 8) || '—'}
                </td>
                <td style={{ padding: 'var(--mantine-spacing-xs) var(--mantine-spacing-sm)', borderBottom: '1px solid var(--mantine-color-default-border)', textAlign: 'right' }}>
                  <Group gap="xs">
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
                      onClick={() => onDelete(document)}
                    >
                      Удалить
                    </Button>
                  </Group>
                </td>
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
          marginTop: 'var(--mantine-spacing-md)',
          flexWrap: 'wrap',
          gap: 'var(--mantine-spacing-xs)',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--mantine-spacing-xs)' }}>
          <button
            style={{
              padding: 'var(--mantine-spacing-xs) var(--mantine-spacing-sm)',
              border: '1px solid var(--mantine-color-default-border)',
              background: 'var(--mantine-color-white)',
              borderRadius: 'var(--mantine-radius-xs)',
              cursor: 'pointer',
            }}
            disabled={safePage === 0}
            onClick={() => onPageChange({ pageIndex: safePage - 1, pageSize })}
          >
            ◀ Назад
          </button>
          <span
            style={{ minWidth: '80px', textAlign: 'center', display: 'inline-block' }}
          >
            {safePage + 1} / {pageCount}
          </span>
          <button
            style={{
              padding: 'var(--mantine-spacing-xs) var(--mantine-spacing-sm)',
              border: '1px solid var(--mantine-color-default-border)',
              background: 'var(--mantine-color-white)',
              borderRadius: 'var(--mantine-radius-xs)',
              cursor: 'pointer',
            }}
            disabled={safePage >= pageCount - 1}
            onClick={() => onPageChange({ pageIndex: safePage + 1, pageSize })}
          >
            Вперед ▶
          </button>
        </div>
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 'var(--mantine-spacing-xs)',
            color: 'var(--mantine-color-dimmed)',
            fontSize: 'var(--mantine-font-size-sm)',
          }}
        >
          <span>Всего: {documents.length}</span>
        </div>
      </div>
    </div>
  )
}

// ------------------------------------------------------------------- детали документа
/** Модалка с деталями документа. */
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
    <Modal
      opened={opened}
      onClose={onClose}
      title={`Документ: ${document.title || document.docname}`}
      size="md"
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
    </Modal>
  )
}

interface DocumentsTabProps {
  sessionId: string
  readOnly: boolean
}

export function DocumentsTab({ sessionId, readOnly }: DocumentsTabProps) {
  // --- URL-состояние: категория, страница, сортировка живут в адресе ---
  const [searchParams, setSearchParams] = useSearchParams()
  const urlCategory = searchParams.get('category') || 'all'
  const urlPage = Math.max(0, Number(searchParams.get('page')) - 1 || 0)
  const urlSize = Number(searchParams.get('size')) || 25
  const urlSort = searchParams.get('sort') || 'title'
  const urlDesc = searchParams.get('desc') === 'true'

  const [category, setCategory] = useState<string>(urlCategory)
  const [path, setPath] = useState('')
  const [tags, setTags] = useState<string[]>([])
  const [files, setFiles] = useState<File[]>([])
  const [formError, setFormError] = useState<string | null>(null)
  const [uploadResult, setUploadResult] = useState<string | null>(null)
  /** % отправленных байтов при загрузке (XHR onprogress); null — не идёт. */
  const [uploadPercent, setUploadPercent] = useState<number | null>(null)
  /** Построчные ошибки при приёме файлов в dropzone: имя файла → причина. */
  const [rejectErrors, setRejectErrors] = useState<Record<string, string>>({})
  /** Документ, который был оптимистично удалён и ждёт undo-тост. */
  const [deletedDocument, setDeletedDocument] = useState<DocumentOut | null>(null)
  /** Таймер undo-тоста (5 секунд). */
  const undoTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
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
      {
        path: path.trim(),
        category: (category === 'all' ? undefined : category) as any,
        tags,
      },
      {
        onSuccess: () => {
          setPath('')
          setTags([])
        },
        onError: (cause) =>
          setFormError(
            cause instanceof Error ? cause.message : 'Не удалось добавить',
          ),
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
        category: (category === 'all' ? undefined : category) as any,
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
          setFormError(
            cause instanceof Error ? cause.message : 'Загрузка не удалась',
          ),
        onSettled: () => setUploadPercent(null),
      },
    )
  }

  // ---------------------------------------------------------------- удаление с undo-тостом
  /** Оптимистично удаляет документ из списка и показывает тост с кнопкой «Отменить». */
  function handleDeleteDocument(document: DocumentOut) {
    // Если есть предыдущий неотменённый undo — отменяем его таймер
    if (undoTimer.current) {
      clearTimeout(undoTimer.current)
      undoTimer.current = null
    }

    setDeletedDocument(document)

    notifications.show({
      title: `Документ «${document.title || document.docname}» удалён`,
      message: '',
      color: 'error',
      autoClose: 5000,
    })

    // Автоматически подтверждаем удаление через 5 секунд
    undoTimer.current = setTimeout(() => {
      setDeletedDocument(null)
      undoTimer.current = null
    }, 5000)

    // Реальный запрос на сервер
    if (!document.id) return
    remove.mutate(document.id, {
      onSuccess: () => {
        if (deletedDocument?.id === document.id) {
          setDeletedDocument(null)
        }
      },
      onError: (cause) => {
        // При ошибке сервера возвращаем документ в список
        setDeletedDocument(null)
        setFormError(
          cause instanceof Error ? cause.message : 'Не удалось удалить документ',
        )
      },
    })
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
    if (
      !ext ||
      !ALLOWED_EXTENSIONS.includes(ext as (typeof ALLOWED_EXTENSIONS)[number])
    ) {
      return `Неподдерживаемый тип файла: ${ext || '(без расширения)'}`
    }
    if (file.size > MAX_FILE_SIZE) {
      return `Превышен размер ${MAX_FILE_SIZE_MB} МБ`
    }
    return null
  }

  // ---------------------------------------------------------------- dropzone
  const getAccept = (): Record<string, string[]> => {
    const map: Record<string, string[]> = {}
    for (const ext of ALLOWED_EXTENSIONS) {
      const mime = ACCEPT_MAP[ext]
      if (!map[mime]) map[mime] = []
      map[mime].push(ext)
    }
    return map
  }

  const onReject = (fileRejections: any) => {
    const next: Record<string, string> = {}
    for (const { file, reason } of fileRejections) {
      next[file.name] = reason
    }
    setRejectErrors((prev) => ({ ...prev, ...next }))
  }

  /** Фильтруем документы по выбранной категории, исключая удалённые (в ожидании undo). */
  const filteredDocs = useMemo(() => {
    const docs = (documents.data ?? []).filter(
      (d) => deletedDocument?.id !== d.id,
    )
    if (category === 'all') return docs
    return docs.filter((d) => d.category === category)
  }, [documents.data, category, deletedDocument])

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
          onChange={(value) => {
            const next = value ?? 'all'
            setCategory(next)
            const params = new URLSearchParams(searchParams)
            if (next === 'all') params.delete('category')
            else params.set('category', next)
            params.delete('page')
            setSearchParams(params, { replace: true })
          }}
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
          data={tags as any}
          onChange={(values) => setTags(values as string[])}
          disabled={readOnly}
          style={{ flex: 1 }}
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
        onReject={(fileRejections: any) => onReject(fileRejections)}
        onDrop={(acceptedFiles: any) => {
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
        <div
          data-testid="doc-dropzone"
          aria-disabled={readOnly}
          style={{
            border: `2px dashed var(--mantine-color-default-border)`,
            borderRadius: 'var(--mantine-radius-md)',
            padding: 'var(--mantine-spacing-md)',
            textAlign: 'center',
            cursor: readOnly ? 'not-allowed' : 'pointer',
            opacity: readOnly ? 0.6 : 1,
          }}
          onClick={() => {
            if (!readOnly) {
              const input = document.querySelector('[data-testid="doc-file-input"]') as HTMLInputElement | null
              input?.click()
            }
          }}
        >
          <Text size="sm" c="dimmed">
            Перетащите файлы сюда или нажмите, чтобы выбрать
          </Text>
          <input
            type="file"
            multiple
            hidden
            data-testid="doc-file-input"
            onChange={(e) => {
              const selected = Array.from(e.target.files ?? [])
              if (selected.length > 0) {
                const newFiles: File[] = []
                for (const file of selected) {
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
              }
            }}
          />
        </div>
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
                <Text
                  size="xs"
                  c="dimmed"
                  style={{
                    whiteSpace: 'nowrap',
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                    maxWidth: 180,
                  }}
                >
                  {file.name} — {(file.size / 1024).toFixed(0)} КБ
                </Text>
                <Button
                  size="xs"
                  variant="subtle"
                  color="error"
                  disabled={upload.isPending}
                  onClick={() => removeFile(file)}
                  aria-label={`Удалить ${file.name} из выборки`}
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
            defaultValue={grouped.length > 0 ? grouped[0][0] : ''}
            multiple={false}
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
                              onClick={() => handleDeleteDocument(document)}
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
          onDelete={handleDeleteDocument}
          setSelectedDoc={setSelectedDoc}
          pageIndex={urlPage}
          pageSize={urlSize}
          sortId={urlSort}
          sortDesc={urlDesc}
          onPageChange={(next) => {
            const params = new URLSearchParams(searchParams)
            params.set('page', String(next.pageIndex + 1))
            params.set('size', String(next.pageSize))
            setSearchParams(params, { replace: true })
          }}
          onSortChange={(next) => {
            const params = new URLSearchParams(searchParams)
            if (next) {
              params.set('sort', next.id)
              params.set('desc', String(next.desc))
            } else {
              params.delete('sort')
              params.delete('desc')
            }
            params.delete('page')
            setSearchParams(params, { replace: true })
          }}
        />
      ) : null}

      <DocumentDetailDrawer
        opened={selectedDoc !== null}
        document={selectedDoc!}
        onClose={() => setSelectedDoc(null)}
      />

    </Stack>
  )
}
