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
  Checkbox,
  Group,
  Modal,
  Progress,
  Select,
  Stack,
  Table,
  Text,
  TextInput,
} from '@mantine/core'
import { Dropzone, type FileRejection, type FileWithPath } from '@mantine/dropzone'
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
  useUploadDocumentsAsync,
} from './queries'

/** CATEGORIES workspace.py (без глобальной — та только у админа). */
export const CATEGORIES = [
  'temp_literature',
  'project_data',
  'project_draft',
  'notes',
  'supplementary',
  'style_guide',
] as const

const CATEGORY_OPTIONS = CATEGORIES.map((value) => ({
  value,
  label: categoryLabel(value),
}))

/**
 * Итог фоновой индексации — то, что сервер кладёт в `result` задачи.
 * Заполняется по мере готовности: на frontend приходит вместе с задачей.
 */
interface IndexingResult {
  added?: Array<{ id: string; docname: string; chunks: number }>
  duplicates?: string[]
  failed?: Array<{ name: string; error: string }>
  total?: number
}

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
    // sortId приходит из шапки таблицы — ключ поля объекта документа.
    const aVal = (a as unknown as Record<string, unknown>)[sortId] ?? ''
    const bVal = (b as unknown as Record<string, unknown>)[sortId] ?? ''
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
                    ? () =>
                        onSortChange({
                          id: h.key,
                          desc: sortId === h.key ? !sortDesc : false,
                        })
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
                <td
                  style={{
                    padding: 'var(--mantine-spacing-xs) var(--mantine-spacing-sm)',
                    borderBottom: '1px solid var(--mantine-color-default-border)',
                  }}
                >
                  {document.title || document.docname}
                </td>
                <td
                  style={{
                    padding: 'var(--mantine-spacing-xs) var(--mantine-spacing-sm)',
                    borderBottom: '1px solid var(--mantine-color-default-border)',
                  }}
                >
                  {categoryLabel(document.category)}
                </td>
                <td
                  style={{
                    padding: 'var(--mantine-spacing-xs) var(--mantine-spacing-sm)',
                    borderBottom: '1px solid var(--mantine-color-default-border)',
                  }}
                >
                  <Badge size="xs">{document.status ?? '—'}</Badge>
                </td>
                <td
                  style={{
                    padding: 'var(--mantine-spacing-xs) var(--mantine-spacing-sm)',
                    borderBottom: '1px solid var(--mantine-color-default-border)',
                  }}
                >
                  {document.chunk_count ?? 0}
                </td>
                <td
                  style={{
                    padding: 'var(--mantine-spacing-xs) var(--mantine-spacing-sm)',
                    borderBottom: '1px solid var(--mantine-color-default-border)',
                  }}
                >
                  {(() => {
                    const bytes = document.size_bytes ?? 0
                    if (bytes < 1024) return `${bytes} Б`
                    if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} КБ`
                    return `${(bytes / (1024 * 1024)).toFixed(1)} МБ`
                  })()}
                </td>
                <td
                  style={{
                    padding: 'var(--mantine-spacing-xs) var(--mantine-spacing-sm)',
                    borderBottom: '1px solid var(--mantine-color-default-border)',
                  }}
                >
                  {document.tags?.join(', ') || '—'}
                </td>
                <td
                  style={{
                    padding: 'var(--mantine-spacing-xs) var(--mantine-spacing-sm)',
                    borderBottom: '1px solid var(--mantine-color-default-border)',
                  }}
                >
                  {document.dockey?.slice(0, 8) || '—'}
                </td>
                <td
                  style={{
                    padding: 'var(--mantine-spacing-xs) var(--mantine-spacing-sm)',
                    borderBottom: '1px solid var(--mantine-color-default-border)',
                    textAlign: 'right',
                  }}
                >
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
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 'var(--mantine-spacing-xs)',
          }}
        >
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
          <Text size="sm" fw={500}>
            Название:
          </Text>
          <Text size="sm">{document.title || document.docname}</Text>
        </Group>
        <Group>
          <Text size="sm" fw={500}>
            Категория:
          </Text>
          <Badge size="xs">{categoryLabel(document.category ?? '—')}</Badge>
        </Group>
        <Group>
          <Text size="sm" fw={500}>
            Статус:
          </Text>
          <Badge size="xs">{document.status ?? '—'}</Badge>
        </Group>
        <Group>
          <Text size="sm" fw={500}>
            Чанков:
          </Text>
          <Text size="sm">{document.chunk_count ?? 0}</Text>
        </Group>
        <Group>
          <Text size="sm" fw={500}>
            Объём:
          </Text>
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
            <Text size="sm" fw={500}>
              Dockey:
            </Text>
            <Text size="xs" c="dimmed" ff="monospace">
              {document.dockey}
            </Text>
          </Group>
        )}
        {document.tags && document.tags.length > 0 && (
          <Group>
            <Text size="sm" fw={500}>
              Теги:
            </Text>
            <Text size="sm">{document.tags.join(', ')}</Text>
          </Group>
        )}
        {document.citation && (
          <Group>
            <Text size="sm" fw={500}>
              Цитата:
            </Text>
            <Text size="xs" c="dimmed">
              {document.citation}
            </Text>
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
  /** Окно подтверждения замены прежних версий документов с теми же именами. */
  const [replaceOpen, setReplaceOpen] = useState(false)
  /** Переиндексировать документ по пути, даже если он уже в индексе. */
  const [forceReindex, setForceReindex] = useState(false)

  const documents = useSessionDocuments(sessionId)
  const tasks = useSessionIndexingTasks(sessionId)
  const addByPath = useAddDocumentByPath(sessionId)
  const upload = useUploadDocumentsAsync(sessionId)
  const remove = useDeleteDocument(sessionId)

  // ---------------------------------------------------------------- добавить по пути
  function handleAddPath() {
    setFormError(null)
    addByPath.mutate(
      {
        path: path.trim(),
        category: category === 'all' ? undefined : category,
        tags,
        forceReindex,
      },
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
  /** Имена выбранных файлов, которые уже есть в сессии. */
  const conflictingNames = files
    .map((file) => file.name)
    .filter((name) => (documents.data ?? []).some((doc) => doc.filename === name))

  const startUpload = (replace: boolean) => {
    setFormError(null)
    setUploadResult(null)
    setUploadPercent(0)
    upload.mutate(
      {
        files,
        category: category === 'all' ? undefined : category,
        tags: tags.join(', '),
        onProgress: setUploadPercent,
        replace,
      },
      {
        onSuccess: (result) => {
          // Индексация идёт в фоне: итог придёт вместе с задачей.
          setUploadResult(
            `Файлов сохранено: ${result.total}. Индексация идёт в фоне — прогресс ниже.`,
          )
          setFiles([])
          setRejectErrors({})
          setReplaceOpen(false)
        },
        onError: (cause) =>
          setFormError(cause instanceof Error ? cause.message : 'Загрузка не удалась'),
        onSettled: () => setUploadPercent(null),
      },
    )
  }

  function handleUpload() {
    if (files.length === 0) return
    // Файл с тем же именем уже есть: без вопроса он лёг бы вторым
    // документом (дедуп PaperQA идёт по содержимому, а не по имени).
    if (conflictingNames.length > 0) {
      setReplaceOpen(true)
      return
    }
    startUpload(false)
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

  const onReject = (fileRejections: FileRejection[]) => {
    const next: Record<string, string> = {}
    for (const { file, errors } of fileRejections) {
      // react-dropzone отдаёт массив ошибок, а Mantine — одну строку.
      next[file.name] = errors.map((error) => error.message).join('; ')
    }
    setRejectErrors((prev) => ({ ...prev, ...next }))
  }

  /** Фильтруем документы по выбранной категории, исключая удалённые (в ожидании undo). */
  const filteredDocs = useMemo(() => {
    const docs = (documents.data ?? []).filter((d) => deletedDocument?.id !== d.id)
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

  /**
   * Итог фоновой индексации: сервер кладёт счётчики в `result` задачи.
   *
   * Показываем, что именно произошло с каждым файлом: сколько проиндексировано,
   * сколько было дубликатов и какие файлы не удалось разобрать.
   */
  const indexingSummary = useMemo(() => {
    for (const task of tasks.data ?? []) {
      if (task.kind !== 'indexing') continue
      if (task.status !== 'done' && task.status !== 'error') continue
      const result = task.result as IndexingResult | null
      if (!result) continue
      return result
    }
    return null
  }, [tasks.data])

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

      {indexingSummary && (
        <Alert
          color={indexingSummary.failed?.length ? 'yellow' : 'success'}
          title="Итог индексации"
          role="status"
        >
          <Stack gap={2}>
            <Text size="sm">
              {`Проиндексировано: ${indexingSummary.added?.length ?? 0}`}
              {indexingSummary.duplicates?.length
                ? `, дубликатов: ${indexingSummary.duplicates.length}`
                : ''}
              {indexingSummary.failed?.length
                ? `, с ошибкой: ${indexingSummary.failed.length}`
                : ''}
            </Text>
            {(indexingSummary.failed ?? []).map((item) => (
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
            В сессии уже есть файлы с теми же именами. Загрузка заменит их: прежние
            версии исчезнут из индекса, новые займут их место.
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
            <Button onClick={() => startUpload(true)}>Заменить и загрузить</Button>
          </Group>
        </Stack>
      </Modal>

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
          data={[{ value: 'all', label: 'Все категории' }, ...CATEGORY_OPTIONS]}
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
          data={tags}
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

      <Checkbox
        label="Переиндексировать, если документ уже есть в индексе"
        description="Нужно после смены настроек индексации: старые чанки устарели."
        checked={forceReindex}
        onChange={(event) => setForceReindex(event.currentTarget.checked)}
        disabled={readOnly}
      />

      <Dropzone
        accept={getAccept()}
        maxSize={MAX_FILE_SIZE}
        onReject={(fileRejections: FileRejection[]) => onReject(fileRejections)}
        onDrop={(acceptedFiles: FileWithPath[]) => {
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
              const input = document.querySelector(
                '[data-testid="doc-file-input"]',
              ) as HTMLInputElement | null
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
                if (newFiles.length > 0)
                  setFiles((current) => [...current, ...newFiles])
              }
            }}
          />
        </div>
      </Dropzone>

      {files.length > 0 && (
        <Group justify="space-between" wrap="wrap">
          <Stack gap="xs">
            <Text size="sm">Выбрано файлов: {files.length}</Text>
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
              : 'Файлы отправлены, индексация идёт в фоне…'}
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
              const filteredItems =
                category === 'all'
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
