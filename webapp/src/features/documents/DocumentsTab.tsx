/**
 * Вкладка «Документы» — паритет `documents_tab` из workspace.py.
 *
 * Верх: добавление по пути (категория, путь, теги) и drag&drop-зона
 * (в Streamlit это file_uploader + кнопка «Загрузить файлы»). Низ: список,
 * сгруппированный по категориям в expander'ах — размер, чанки, теги,
 * dockey, удаление. Пока идёт индексация — панели активных задач сессии
 * (план: «список с прогрессом индексации»).
 */

import {
  Accordion,
  Alert,
  Button,
  Group,
  Progress,
  Select,
  Stack,
  Text,
  TextInput,
  UnstyledButton,
} from '@mantine/core'
import { useMemo, useRef, useState } from 'react'

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
}))

interface DocumentsTabProps {
  sessionId: string
  readOnly: boolean
}

export function DocumentsTab({ sessionId, readOnly }: DocumentsTabProps) {
  const [category, setCategory] = useState<string>('temp_literature')
  const [path, setPath] = useState('')
  const [tags, setTags] = useState('')
  const [files, setFiles] = useState<File[]>([])
  const [dragOver, setDragOver] = useState(false)
  const [formError, setFormError] = useState<string | null>(null)
  const [uploadResult, setUploadResult] = useState<string | null>(null)
  /** % отправленных байтов при загрузке (XHR onprogress); null — не идёт. */
  const [uploadPercent, setUploadPercent] = useState<number | null>(null)
  const fileInput = useRef<HTMLInputElement>(null)

  const documents = useSessionDocuments(sessionId)
  const tasks = useSessionIndexingTasks(sessionId)
  const addByPath = useAddDocumentByPath(sessionId)
  const upload = useUploadDocuments(sessionId)
  const remove = useDeleteDocument(sessionId)

  const tagList = useMemo(
    () =>
      tags
        .split(',')
        .map((tag) => tag.trim())
        .filter(Boolean),
    [tags],
  )

  // ---------------------------------------------------------------- добавить по пути
  function handleAddPath() {
    setFormError(null)
    addByPath.mutate(
      { path: path.trim(), category, tags: tagList },
      {
        onSuccess: () => {
          setPath('')
          setTags('')
        },
        onError: (cause) =>
          setFormError(cause instanceof Error ? cause.message : 'Не удалось добавить'),
      },
    )
  }

  // ---------------------------------------------------------------- загрузка файлов
  function handleUpload(accepted: File[]) {
    if (accepted.length === 0) return
    setFormError(null)
    setUploadResult(null)
    setUploadPercent(0)
    upload.mutate(
      { files: accepted, category, tags, onProgress: setUploadPercent },
      {
        onSuccess: (result) => {
          setUploadResult(
            `Добавлено: ${result.added?.length ?? 0}, ошибок: ${result.failed?.length ?? 0}`,
          )
          setFiles([])
        },
        onError: (cause) =>
          setFormError(cause instanceof Error ? cause.message : 'Загрузка не удалась'),
        onSettled: () => setUploadPercent(null),
      },
    )
  }

  // паритет st.file_uploader: показываем выбранные файлы до нажатия кнопки
  function onDrop(event: React.DragEvent) {
    event.preventDefault()
    setDragOver(false)
    if (readOnly) return
    const dropped = Array.from(event.dataTransfer.files)
    if (dropped.length > 0) setFiles((current) => [...current, ...dropped])
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
        <Alert color="red" role="alert">
          {formError}
        </Alert>
      )}
      {uploadResult && <Alert color="green">{uploadResult}</Alert>}

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
        <TextInput
          label="Теги через запятую"
          value={tags}
          onChange={(event) => setTags(event.currentTarget.value)}
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

      {/* dropzone вместо file_uploader: файлы копятся, грузятся кнопкой */}
      <UnstyledButton
        component="div"
        onClick={() => !readOnly && fileInput.current?.click()}
        onDragOver={(event) => {
          event.preventDefault()
          if (!readOnly) setDragOver(true)
        }}
        onDragLeave={() => setDragOver(false)}
        onDrop={onDrop}
        data-testid="doc-dropzone"
        aria-disabled={readOnly}
        style={{
          border: `2px dashed ${dragOver ? 'var(--mantine-color-blue-4)' : 'var(--mantine-color-default-border)'}`,
          borderRadius: 'var(--mantine-radius-md)',
          padding: 'var(--mantine-spacing-md)',
          textAlign: 'center',
          cursor: readOnly ? 'not-allowed' : 'pointer',
          background: dragOver ? 'var(--mantine-color-blue-light)' : undefined,
          opacity: readOnly ? 0.6 : 1,
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
        onChange={(event) => {
          const selected = Array.from(event.target.files ?? [])
          if (selected.length > 0) setFiles((current) => [...current, ...selected])
          event.target.value = ''
        }}
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
              onClick={() => handleUpload(files)}
              loading={upload.isPending}
              disabled={readOnly}
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
        <Alert color="red" role="alert">
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
                          <Text component="span" c="red" size="xs">
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
                        color="red"
                        variant="subtle"
                        disabled={readOnly}
                        loading={remove.isPending && remove.variables === document.id}
                        onClick={() => remove.mutate(document.id as string)}
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
    </Stack>
  )
}
