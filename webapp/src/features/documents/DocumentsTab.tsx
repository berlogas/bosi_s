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
  Progress,
  Select,
  Stack,
  Text,
  TextInput,
} from '@mantine/core'
import { Dropzone, DropzoneProps } from '@mantine/dropzone'
import { TagsInput } from '@mantine/core'
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

interface DocumentsTabProps {
  sessionId: string
  readOnly: boolean
}

export function DocumentsTab({ sessionId, readOnly }: DocumentsTabProps) {
  const [category, setCategory] = useState<string>('temp_literature')
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

  const documents = useSessionDocuments(sessionId)
  const tasks = useSessionIndexingTasks(sessionId)
  const addByPath = useAddDocumentByPath(sessionId)
  const upload = useUploadDocuments(sessionId)
  const remove = useDeleteDocument(sessionId)

  // ---------------------------------------------------------------- добавить по пути
  function handleAddPath() {
    setFormError(null)
    addByPath.mutate(
      { path: path.trim(), category, tags },
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
        category,
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

  // ---------------------------------------------------------------- список
  const grouped = useMemo(() => {
    const groups = new Map<string, DocumentOut[]>()
    for (const document of documents.data ?? []) {
      const key = document.category || 'notes'
      const bucket = groups.get(key)
      if (bucket) bucket.push(document)
      else groups.set(key, [document])
    }
    return [...groups.entries()]
  }, [documents.data])

  const liveTasks = (tasks.data ?? []).filter(
    (task) => task.status === 'running' || task.status === 'queued',
  )

  return (
    <Stack gap="sm">
      <Text fw={600}>Документы</Text>

      {formError && (
        <Alert color="error" role="alert">
          {formError}
        </Alert>
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
          data={CATEGORY_OPTIONS}
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

      {grouped.length === 0 && !documents.isPending && (
        <Text size="sm" c="dimmed">
          Документов пока нет.
        </Text>
      )}

      {/* key: defaultValue читается при монтировании — без него панели
          остаются закрытыми, когда список приходит асинхронно */}
      <Accordion
        key={grouped.map(([key]) => key).join('|')}
        defaultValue={grouped.map(([key]) => key)}
        multiple
      >
        {grouped.map(([group, items]) => (
          <Accordion.Item key={group} value={group}>
            <Accordion.Control>
              {categoryLabel(group)} ({items.length})
            </Accordion.Control>
            <Accordion.Panel>
              <Stack gap="xs">
                {items.map((document) => (
                  <Group key={document.id ?? document.dockey} justify="space-between">
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
                    <Group gap="md">
                      {document.dockey && (
                        <Text size="xs" c="dimmed" ff="monospace">
                          {document.dockey.slice(0, 8)}
                        </Text>
                      )}
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
        ))}
      </Accordion>

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
