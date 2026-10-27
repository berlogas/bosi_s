/**
 * Вкладка «Проекты» — паритет `project_editor.py` (Streamlit).
 *
 * Секции 1-в-1: создание → выбор проекта → прогресс/статус/удаление →
 * генерация и анализ → разделы (черновик + сохранить/сгенерировать) →
 * привязка документов → экспорт. Генерация синхронная (Streamlit тоже
 * ждал со спиннером), тяжёлые задачи — панель TaskPanel.
 */

import {
  Accordion,
  Alert,
  Badge,
  Button,
  Drawer,
  Divider,
  Group,
  List,
  Paper,
  Select,
  Stack,
  Table,
  Text,
  TextInput,
  UnstyledButton,
} from '@mantine/core'
import { useMutation } from '@tanstack/react-query'
import { useEffect, useMemo, useRef, useState } from 'react'
import { notifications } from '@mantine/notifications'
import { SkeletonList } from '../../components/SkeletonList'
import CodeMirror from '@uiw/react-codemirror'
import { markdown } from '@codemirror/lang-markdown'
import { EditorView, keymap } from '@codemirror/view'
import { indentWithTab } from '@codemirror/commands'

import { client } from '../../api/client'
import type { ExportFormat } from '../../api/client'
import type { GenerateResult, ProjectOut } from '../../api/types'
import { MarkdownText } from '../../components/MarkdownText'
import { TaskPanel } from '../../components/TaskPanel'
import { loadDrafts, saveDraft } from './drafts'
import { sectionTitle } from '../../lib/sections'
import { kindOptions } from '../../lib/kinds'
import {
  docRoleLabel,
  docRoleOptions,
  projectStatusOptions,
} from '../../lib/projectOptions'
import {
  useBindDocument,
  useCreateProject,
  useDeleteProject,
  useExportProject,
  useGenerate,
  usePatchProject,
  useJournalStyles,
  useProjectDocuments,
  useProjectProgress,
  useProjects,
  useSaveSection,
  useSections,
  useUnbindDocument,
} from './queries'
import { useSessionDocuments } from '../documents/queries'
import { useSessionIndexingTasks } from '../documents/queries'

const STATUSES = ['planning', 'drafting', 'reviewing', 'done'] as const

// Полный набор GenerationKind из backend. `discussion` отдельной ветки
// промпта не имеет и собирается как `section`, но для раздела Discussion
// отрабатывает надёжнее: на прогонах `section` возвращал пустой текст.
const KINDS = [
  'section',
  'discussion',
  'literature_review',
  'data_comparison',
  'gap_analysis',
  'draft_analysis',
  'report',
] as const

const ROLES = ['reference', 'data', 'draft'] as const

interface ProjectsTabProps {
  sessionId: string
  readOnly: boolean
}

export function ProjectsTab({ sessionId, readOnly }: ProjectsTabProps) {
  const projects = useProjects(sessionId)
  const styles = useJournalStyles()
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [title, setTitle] = useState('')
  const [journal, setJournal] = useState('')
  const [createError, setCreateError] = useState<string | null>(null)
  const create = useCreateProject(sessionId)
  const patch = usePatchProject(sessionId)
  const remove = useDeleteProject(sessionId)
  const [_actionError, setActionError] = useState<string | null>(null)

  const journalChoices = (styles.data ?? []).map((item) => ({
    value: item.key,
    label: item.title,
  }))

  // Описание выбранного стиля: читатель и тон.
  const chosenStyle = (styles.data ?? []).find((item) => item.key === journal)

  const list = useMemo(() => projects.data ?? [], [projects.data])

  // первый проект выбран по умолчанию (как в Streamlit — current_project_id)
  useEffect(() => {
    const data = projects.data ?? []
    if (selectedId === null && data && data.length > 0) {
      setSelectedId(data[0].id ?? null)
    }
    if (selectedId !== null && (!data || !data.some((p) => p.id === selectedId))) {
      setSelectedId(data?.[0]?.id ?? null)
    }
  }, [projects.data, selectedId])

  const selected = projects.data?.find((project) => project.id === selectedId) ?? null

  function handleCreate() {
    setCreateError(null)
    create.mutate(
      { title: title.trim(), journal: journal.trim() },
      {
        onSuccess: (project) => {
          setTitle('')
          setJournal('')
          setSelectedId(project.id)
        },
        onError: (cause) =>
          setCreateError(cause instanceof Error ? cause.message : 'Не удалось создать'),
      },
    )
  }

  // -------------------------------------------------------------------- мастер-дейл:
  // левая колонка — список проектов (sticky), правая — редактор выбранного проекта
  return (
    <Stack gap="sm">
      <Text fw={600}>Проекты статей</Text>

      {/* форма создания */}
      <Group align="flex-end" gap="sm">
        <TextInput
          label="Название"
          value={title}
          onChange={(event) => setTitle(event.currentTarget.value)}
          disabled={readOnly}
          style={{ flex: 2 }}
        />
        <Select
          label="Стиль журнала"
          placeholder="Выберите стиль"
          data={journalChoices}
          value={journal || null}
          onChange={(value) => setJournal(value ?? '')}
          disabled={readOnly}
          searchable
          allowDeselect={false}
          style={{ flex: 2 }}
        />
        <Button
          onClick={handleCreate}
          disabled={readOnly || !title.trim()}
          loading={create.isPending}
        >
          Создать
        </Button>
      </Group>

      {chosenStyle && (
        <Alert color="info" variant="light" p="xs">
          <Text size="sm">
            Стиль «{chosenStyle.title}»: {chosenStyle.summary}
          </Text>
          <Text size="xs" c="dimmed" mt="xs">
            Журналы: {chosenStyle.journals.join(', ')}
          </Text>
        </Alert>
      )}
      {createError && (
        <Alert color="error" role="alert">
          {createError}
        </Alert>
      )}

      {projects.isError && (
        <Alert color="error" role="alert">
          {projects.error instanceof Error
            ? projects.error.message
            : 'Не удалось загрузить проекты'}
        </Alert>
      )}

      <HowToPanel hasProjects={list.length > 0} />

      {/* список проектов слева (sticky через CSS в реальном браузере) */}
      <Stack gap="xs">
        {list.length === 0 && !projects.isPending && (
          <Paper withBorder p="md" style={{ minHeight: 200 }}>
            <Stack align="center" justify="center" gap="xs">
              <Text size="sm" c="dimmed">
                Проектов нет — создайте первый.
              </Text>
            </Stack>
          </Paper>
        )}
        {list.map((project) => {
          const isActive = project.id === selectedId
          return (
            <Button
              key={project.id}
              onClick={() => setSelectedId(project.id)}
              variant={isActive ? 'default' : 'subtle'}
              fullWidth
              size="xs"
              style={{
                justifyContent: 'space-between',
                textAlign: 'left',
                borderLeft: isActive
                  ? '3px solid var(--mantine-color-primary-filled)'
                  : '3px solid transparent',
              }}
            >
              <Stack gap="0">
                <Text size="sm" fw={500}>
                  {project.title}
                </Text>
                <Text size="sm" c="dimmed">
                  {project.status}
                </Text>
              </Stack>
              <Badge size="xs">
                {project.status}
              </Badge>
            </Button>
          )
        })}
      </Stack>

      {selected ? (
        <ProjectEditor
          sessionId={sessionId}
          project={selected}
          readOnly={readOnly}
          onStatusChange={(value) => {
            // Статус сохраняется автоматически при изменении — без кнопки «Обновить»
            setActionError(null)
            patch.mutate(
              {
                projectId: selected.id,
                fields: { status: value },
              },
              {
                onError: (cause) =>
                  setActionError(
                    cause instanceof Error
                      ? cause.message
                      : 'Не удалось обновить статус',
                  ),
              },
            )
          }}
          onDelete={() => {
            setActionError(null)
            remove.mutate(selected.id, {
              onSuccess: () => setSelectedId(null),
              onError: (cause) =>
                setActionError(
                  cause instanceof Error ? cause.message : 'Не удалось удалить',
                ),
            })
          }}
          deleting={remove.isPending && remove.variables === selected.id}
        />
      ) : null}
    </Stack>
  )
}

// --------------------------------------------------------------------------- экспорт
const EXPORT_FORMATS: { value: ExportFormat; label: string; hint: string }[] = [
  { value: 'docx', label: 'Word (.docx)', hint: 'готовый файл для журнала' },
  { value: 'markdown', label: 'Markdown (.md)', hint: 'для репозитория или вики' },
  { value: 'zip', label: 'ZIP', hint: 'статья + библиография + исходники' },
]

function ExportPanel({
  sessionId,
  project,
}: {
  sessionId: string
  project: ProjectOut
}) {
  const exportProject = useExportProject(sessionId)
  const [format, setFormat] = useState<ExportFormat>('docx')
  const [message, setMessage] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  return (
    <Paper withBorder p="sm">
      <Group align="flex-end" gap="sm">
        <Select
          label="Выгрузка статьи"
          data={EXPORT_FORMATS.map((item) => ({
            value: item.value,
            label: item.label,
          }))}
          value={format}
          onChange={(value) => value && setFormat(value as ExportFormat)}
          allowDeselect={false}
          w={200}
        />
        <Button
          variant="light"
          loading={exportProject.isPending}
          onClick={() => {
            setMessage(null)
            setError(null)
            exportProject.mutate(
              { projectId: project.id, format },
              {
                // Сервер отдаёт файл потоком, на диск его кладёт браузер.
                onSuccess: ({ filename }) => setMessage(`Файл скачан: ${filename}`),
                onError: (cause) =>
                  setError(
                    cause instanceof Error
                      ? cause.message
                      : 'Не удалось выгрузить файл',
                  ),
              },
            )
          }}
        >
          Выгрузить
        </Button>
        <Text size="xs" c="dimmed">
          {EXPORT_FORMATS.find((item) => item.value === format)?.hint}
        </Text>
      </Group>
      {message && (
        <Text size="sm" c="success" role="status" mt={6}>
          {message}
        </Text>
      )}
      {error && (
        <Text size="sm" c="error" role="alert" mt={6}>
          {error}
        </Text>
      )}
    </Paper>
  )
}

// ------------------------------------------------------------------ как работать
/**
 * Короткая инструкция прямо на странице: порядок работы с проектом статьи
 * нигде в интерфейсе не был описан, и без него первый заход упирается в
 * вопрос «что нажимать первым».
 */
function HowToPanel({ hasProjects }: { hasProjects: boolean }) {
  return (
    <Accordion defaultValue="howto" multiple={false}>
      <Accordion.Item value="howto">
        <Accordion.Control>
          <Text size="sm" fw={600}>
            Как работать с проектом статьи
          </Text>
        </Accordion.Control>
        <Accordion.Panel>
          <List size="sm" spacing={2} mt={4}>
            <List.Item>
              Создайте проект и выберите стиль журнала — план разделов создастся сам:
              Введение, Методы исследования, Результаты, Обсуждение, Заключение. Промпт
              выбранной группы (роль, аудитория, структура раздела) подставляется в
              генерацию — его текст показан сразу под выбором стиля.
            </List.Item>
            <List.Item>
              Привяжите документы с ролью: <b>Литература</b> — для цитирования,{' '}
              <b>Данные</b> — ваши CSV (участвуют в сверке), <b>Черновик</b> — попадёт в
              контекст как есть.
            </List.Item>
            <List.Item>
              Раздел можно дописать руками или сгенерировать: модель использует контекст
              сессии и обязана ставить ссылки на источники. Каждая генерация сохраняется как
              версия — прошлый текст не пропадает.
            </List.Item>
            <List.Item>
              «Разбор черновика» покажет проблемы: число без ссылки, не написан обязательный
              раздел, есть результаты, но нет методики. Работает мгновенно, без обращения к
              модели.
            </List.Item>
            <List.Item>
              Готовую статью выгрузите внизу экрана: Word, Markdown или ZIP с библиографией
              и исходниками.
            </List.Item>
          </List>
          {!hasProjects && (
            <Text size="xs" c="dimmed" mt={4}>
              Начните с первого шага — поля «Название» и «Стиль журнала» слева.
            </Text>
          )}
        </Accordion.Panel>
      </Accordion.Item>
    </Accordion>
  )
}

// --------------------------------------------------------------------------- редактор
interface ProjectEditorProps {
  sessionId: string
  project: ProjectOut
  readOnly: boolean
  onStatusChange: (value: string) => void
  onDelete: () => void
  deleting: boolean
}

function ProjectEditor({
  sessionId,
  project,
  readOnly,
  onStatusChange,
  onDelete,
  deleting,
}: ProjectEditorProps) {
  const progress = useProjectProgress(sessionId, project.id)
  return (
    <Stack gap="sm">
      <Group align="flex-end" gap="sm">
        <Select
          label="Статус"
          data={projectStatusOptions(STATUSES)}
          value={project.status}
          onChange={(value) => value && onStatusChange(value)}
          disabled={readOnly}
          allowDeselect={false}
          w={200}
          size="xs"
        />
        <Button
          color="error"
          variant="light"
          onClick={onDelete}
          disabled={readOnly}
          loading={deleting}
        >
          Удалить
        </Button>
      </Group>

      {progress.data && (
        <div>
          <Text size="sm">
            {progress.data.written}/{progress.data.sections} разделов ·{' '}
            {progress.data.words} слов
          </Text>
          <div
            role="progressbar"
            aria-valuenow={progress.data.percent}
            aria-valuemin={0}
            aria-valuemax={100}
            style={{
              height: 'var(--mantine-spacing-sm)',
              borderRadius: 'var(--mantine-radius-xs)',
              background: 'var(--mantine-color-default-border)',
              overflow: 'hidden',
              marginTop: 'var(--mantine-spacing-xs)',
            }}
          >
            <div
              style={{
                width: `${Math.min(100, progress.data.percent)}%`,
                height: '100%',
                background: 'var(--mantine-color-blue-filled)',
                transition: 'width 0.3s',
              }}
            />
          </div>
        </div>
      )}

      <ExportPanel sessionId={sessionId} project={project} />

      <GeneratePanel sessionId={sessionId} project={project} readOnly={readOnly} />
      <SectionsList sessionId={sessionId} project={project} readOnly={readOnly} />
      <ProjectDocumentsPanel
        sessionId={sessionId}
        project={project}
        readOnly={readOnly}
      />
    </Stack>
  )
}

// ----------------------------------------------------------------------- генерация
function GeneratePanel({
  sessionId,
  project,
  readOnly,
}: {
  sessionId: string
  project: ProjectOut
  readOnly: boolean
}) {
  const [kind, setKind] = useState<string>('section')
  const [question, setQuestion] = useState('')
  const [result, setResult] = useState<GenerateResult | null>(null)
  const [analysis, setAnalysis] = useState<string | null>(null)
  const [panelError, setPanelError] = useState<string | null>(null)
  const generate = useGenerate(sessionId, project.id)
  const draftAnalysis = useMutation({
    mutationFn: () => client.draftAnalysis(sessionId, project.id),
  })
  const tasks = useSessionIndexingTasks(sessionId)
  const runningTasks = (tasks.data ?? []).filter(
    (task) => task.status === 'running' || task.status === 'queued',
  )

  function run(payload: Record<string, unknown>) {
    setPanelError(null)
    setResult(null)
    generate.mutate(payload as Parameters<typeof generate.mutate>[0], {
      onSuccess: (data) => setResult(data),
      onError: (cause) =>
        setPanelError(cause instanceof Error ? cause.message : 'Генерация не удалась'),
    })
  }

  return (
    <Stack gap="xs">
      <Text size="sm" fw={600}>
        Генерация и анализ
      </Text>

      {runningTasks.map((task) => (
        <TaskPanel key={task.id} task={task} />
      ))}

      <Group align="flex-end" gap="sm">
        <Select
          label="Вид"
          data={kindOptions(KINDS)}
          value={kind}
          onChange={(value) => value && setKind(value)}
          disabled={readOnly}
          allowDeselect={false}
          w={260}
        />
        <TextInput
          label="Вопрос или тема"
          value={question}
          onChange={(event) => setQuestion(event.currentTarget.value)}
          disabled={readOnly}
          style={{ flex: 1 }}
        />
        <Button
          onClick={() =>
            run({
              kind,
              section: '',
              question: question.trim(),
              no_cache: false,
            })
          }
          disabled={readOnly || !question.trim()}
          loading={generate.isPending}
        >
          Запустить
        </Button>
      </Group>

      <Group>
        <Button
          variant="light"
          disabled={readOnly}
          loading={draftAnalysis.isPending}
          onClick={() => {
            setPanelError(null)
            setAnalysis(null)
            draftAnalysis.mutate(undefined, {
              onSuccess: (data) => {
                if (!data.has_gaps) {
                  setAnalysis('Пробелов не найдено.')
                } else {
                  const high = data.by_severity.high ?? 0
                  setAnalysis(
                    `Найдено пробелов: ${data.gaps.length} (критичных ${high})\n` +
                      data.gaps
                        .map(
                          (gap) =>
                            `- **${gap.severity}** · ${sectionTitle(gap.where)}: ${gap.hint}` +
                            (gap.excerpt ? ` — «${gap.excerpt}»` : ''),
                        )
                        .join('\n'),
                  )
                }
              },
              onError: (cause) =>
                setPanelError(
                  cause instanceof Error ? cause.message : 'Разбор не удался',
                ),
            })
          }}
        >
          Разбор черновика
        </Button>
      </Group>

      {panelError && (
        <Alert color="error" role="alert">
          {panelError}
        </Alert>
      )}

      {generate.isPending && (
        <Text size="sm" c="dimmed">
          Генерирую раздел — это может занять минуты…
        </Text>
      )}

      {analysis && (
        <Alert color={analysis === 'Пробелов не найдено.' ? 'green' : 'yellow'}>
          <Text component="div" size="sm" style={{ whiteSpace: 'pre-wrap' }}>
            {analysis}
          </Text>
        </Alert>
      )}

      {result && <GenerateResultView result={result} />}
    </Stack>
  )
}

function GenerateResultView({ result }: { result: GenerateResult }) {
  const [refsOpened, setRefsOpened] = useState(false)
  return (
    <Stack gap={4}>
      {/* content_md может не прийти (старый ответ в кэше, обрезанный ответ):
          без заглушки падает весь рендер вкладки, а не один блок */}
      <MarkdownText text={result.content_md ?? ''} />
      {!result.citations_ok && (
        <Text size="sm" c="warning">
          Проверьте ссылки: часть из них не разрешается в источники.
        </Text>
      )}
      {(result.warnings ?? []).map((warning) => (
        <Text key={warning} size="xs" c="dimmed">
          ⚠ {warning}
        </Text>
      ))}
      {(result.references ?? []).length > 0 && (
        <>
          <UnstyledButton
            onClick={() => setRefsOpened((value) => !value)}
            style={{ textAlign: 'left' }}
          >
            <Text size="sm" style={{ textDecoration: 'underline' }}>
              Источники
            </Text>
          </UnstyledButton>
          {refsOpened && (
            <Stack gap={2}>
              {(result.references ?? []).map((line) => (
                <MarkdownText key={line} text={`- ${line}`} />
              ))}
            </Stack>
          )}
        </>
      )}
    </Stack>
  )
}

// ------------------------------------------------------------------------ разделы
function SectionsList({
  sessionId,
  project,
  readOnly,
}: {
  sessionId: string
  project: ProjectOut
  readOnly: boolean
}) {
  const sections = useSections(sessionId, project.id)
  const save = useSaveSection(sessionId, project.id)
  const generate = useGenerate(sessionId, project.id)

  const [drafts, setDrafts] = useState<Record<string, string>>(() =>
    loadDrafts(sessionId),
  )
  const [savedName, setSavedName] = useState<string | null>(null)
  const [savingSection, setSavingSection] = useState<string | null>(null)
  const [sectionError, setSectionError] = useState<string | null>(null)
  /** Разделы с несохранёнными на сервере изменениями. */
  const [dirtySections, setDirtySections] = useState<Set<string>>(new Set())
  const [genResult, setGenResult] = useState<{
    name: string
    data: GenerateResult
  } | null>(null)
  const saveTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  /** История версий раздела (моковые данные — работает без бэкенда). */
  const [versionHistoryOpen, setVersionHistoryOpen] = useState(false)
  const [versionHistorySection, setVersionHistorySection] = useState<string | null>(null)

  // beforeunload — предупреждение при обновлении страницы (F5) или закрытии вкладки
  useEffect(() => {
    const onBeforeUnload = (e: BeforeUnloadEvent) => {
      if (dirtySections.size > 0) {
        e.preventDefault()
        e.returnValue = ''
      }
    }
    window.addEventListener('beforeunload', onBeforeUnload)
    return () => window.removeEventListener('beforeunload', onBeforeUnload)
  }, [dirtySections])

  function valueOf(name: string, serverValue: string): string {
    return drafts[name] ?? serverValue
  }

  function sectionDirty(name: string, value: string): boolean {
    const section = sections.data?.find((s) => s.name === name)
    return value !== (section?.content_md ?? '')
  }

  function handleChange(name: string, value: string) {
    setDrafts((current) => ({ ...current, [name]: value }))
    saveDraft(sessionId, name, value)
    setSavedName(null)
    setDirtySections((prev) => {
      const next = new Set(prev)
      if (sectionDirty(name, value)) next.add(name)
      else next.delete(name)
      return next
    })

    // Автосейв с debounce 2 секунды
    if (saveTimer.current) clearTimeout(saveTimer.current)
    saveTimer.current = setTimeout(() => {
      handleAutoSave(name, value)
    }, 2000)
  }

  function handleAutoSave(name: string, value: string) {
    if (!sectionDirty(name, value)) return
    setSavingSection(name)
    save.mutate(
      { name, contentMd: value },
      {
        onSuccess: () => {
          setSavingSection(null)
          setDirtySections((prev) => {
            const next = new Set(prev)
            next.delete(name)
            return next
          })
          notifications.show({ title: 'Раздел сохранён', message: '', color: 'green' })
        },
        onError: (cause) => {
          setSavingSection(null)
          setSectionError(
            cause instanceof Error ? cause.message : 'Не удалось сохранить раздел',
          )
        },
      },
    )
  }

  function handleSave(name: string, value: string) {
    if (saveTimer.current) {
      clearTimeout(saveTimer.current)
      saveTimer.current = null
    }
    handleAutoSave(name, value)
  }

  if (sections.isError) {
    return (
      <Alert color="error" role="alert">
        {sections.error instanceof Error
          ? sections.error.message
          : 'Не удалось загрузить разделы'}
      </Alert>
    )
  }

  const hasUnsaved = dirtySections.size > 0

  return (
    <Stack gap="xs">
      <Group align="flex-end" gap="sm">
        <Text size="sm" fw={600}>
          Разделы
        </Text>
        {hasUnsaved && (
          <Badge color="yellow" size="xs">
            Есть несохранённые изменения
          </Badge>
        )}
      </Group>
      {sectionError && (
        <Alert color="error" role="alert">
          {sectionError}
        </Alert>
      )}
      {generate.isPending && (
        <Text size="sm" c="dimmed">
          Генерирую раздел — это может занять минуты…
        </Text>
      )}
      {sections.isPending && <SkeletonList count={3} />}
      {/* key: defaultValue читается при монтировании, а разделы грузятся
          асинхронно — без него панели останутся закрытыми */}
      <Accordion
        key={(sections.data ?? []).map((s) => s.name).join('|')}
        defaultValue={(sections.data ?? [])
          .filter((s) => !s.written)
          .map((s) => s.name)}
        multiple
      >
        {(sections.data ?? []).map((section) => {
          const value = valueOf(section.name, section.content_md)
          const isDirty = dirtySections.has(section.name)
          return (
            <Accordion.Item key={section.name} value={section.name}>
              <Accordion.Control>
                {sectionTitle(section.name)} — {section.word_target} слов
                {isDirty && <Badge size="xs">не сохранено</Badge>}
              </Accordion.Control>
              <Accordion.Panel>
                <Stack gap="xs">
                  <div
                    style={{
                      border: `1px solid ${
                        isDirty
                          ? 'var(--mantine-color-yellow-filled)'
                          : 'var(--mantine-color-default-border)'
                      }`,
                      borderRadius: 'var(--mantine-radius-sm)',
                      minHeight: 200,
                      background: 'var(--mantine-color-body)',
                    }}
                  >
                    <CodeMirrorSection
                      name={section.name}
                      value={value}
                      onChange={(next) => handleChange(section.name, next)}
                      readOnly={readOnly}
                      isDirty={isDirty}
                    />
                  </div>
                  <Group justify="space-between">
                    <Text size="xs" c="dimmed">
                      написано слов: {section.words}
                    </Text>
                    <Group gap="xs">
                      <Button
                        size="xs"
                        variant="subtle"
                        onClick={() => {
                          setVersionHistorySection(section.name)
                          setVersionHistoryOpen(true)
                        }}
                        aria-label={`История версий: ${sectionTitle(section.name)}`}
                      >
                        История
                      </Button>
                      <Button
                        size="xs"
                        onClick={() => handleSave(section.name, value)}
                        disabled={readOnly || !isDirty}
                        loading={savingSection === section.name}
                      >
                        Сохранить
                      </Button>
                      <Button
                        size="xs"
                        variant="light"
                        disabled={readOnly}
                        loading={
                          generate.isPending &&
                          generate.variables?.section === section.name
                        }
                        onClick={() => {
                          setSectionError(null)
                          setGenResult(null)
                          generate.mutate(
                            {
                              section: section.name,
                              question: '',
                              kind: 'section',
                              no_cache: false,
                            },
                            {
                              onSuccess: (data) =>
                                setGenResult({ name: section.name, data }),
                              onError: (cause) =>
                                setSectionError(
                                  cause instanceof Error
                                    ? cause.message
                                    : 'Генерация не удалась',
                                ),
                            },
                          )
                        }}
                      >
                        Сгенерировать
                      </Button>
                    </Group>
                  </Group>
                  {savedName === section.name && (
                    <Text size="sm" c="success">
                      Раздел сохранён.
                    </Text>
                  )}
                  {genResult?.name === section.name && (
                    <GenerateResultView result={genResult.data} />
                  )}
                </Stack>
              </Accordion.Panel>
            </Accordion.Item>
          )
        })}
      </Accordion>
      {versionHistorySection && versionHistoryOpen && (
        <VersionHistoryDrawer
          section={versionHistorySection}
          opened={versionHistoryOpen}
          onClose={() => {
            setVersionHistoryOpen(false)
            setVersionHistorySection(null)
          }}
        />
      )}
      {hasUnsaved && (
        <Text size="xs" c="dimmed">
          Изменения сохраняются автоматически через 2 с после правки. При уходе со
          страницы вы получите предупреждение.
        </Text>
      )}
    </Stack>
  )
}

// ------------------------------------------------------------------- история версий (моковая — работает без бэкенда)
/** Моковые версии раздела — демонстрация интерфейса без бэкенда API. */
const MOCK_VERSIONS: Record<string, Array<{
  version_id: string
  created_at: string
  author: string
  words: number
  change_summary: string
}>> = {
  Introduction: [
    { version_id: 'v-1', created_at: '2026-10-27T09:00:00+00:00', author: 'ivanov', words: 45, change_summary: 'Начальная версия' },
    { version_id: 'v-2', created_at: '2026-10-27T10:30:00+00:00', author: 'ivanov', words: 120, change_summary: 'Добавлена цель исследования' },
    { version_id: 'v-3', created_at: '2026-10-27T14:15:00+00:00', author: 'petrov', words: 155, change_summary: 'Правка стиля и сноски' },
  ],
  Methods: [
    { version_id: 'v-1', created_at: '2026-10-27T11:00:00+00:00', author: 'ivanov', words: 200, change_summary: 'Первый черновик методологии' },
  ],
  Results: [
    { version_id: 'v-1', created_at: '2026-10-27T12:00:00+00:00', author: 'ivanov', words: 80, change_summary: 'Черновик результатов' },
  ],
}

/** Моковый diff между двумя версиями. */
function mockDiff(section: string, from: string, to: string): string {
  const lines = [
    `--- a/${section}.md (${from})`,
    `+++ b/${section}.md (${to})`,
    `@@ -1,3 +1,4 @@`,
    ` Введение`,
    `-старая формулировка`,
    `+новая формулировка`,
    `+добавлен абзац`,
    ``,
    `Раздел подготовлен к отправке.`,
  ]
  return lines.join('\n')
}

/** Drawer с историей версий раздела и diff между выбранными версиями. */
function VersionHistoryDrawer({
  section,
  opened,
  onClose,
}: {
  section: string
  opened: boolean
  onClose: () => void
}) {
  const versions = MOCK_VERSIONS[section] ?? []
  const [selectedFrom, setSelectedFrom] = useState<string | null>(null)
  const [selectedTo, setSelectedTo] = useState<string | null>(null)
  const [diffText, setDiffText] = useState<string | null>(null)

  const handleSelectFrom = (id: string) => {
    setSelectedFrom(id)
    if (selectedTo) {
      setDiffText(mockDiff(section, id, selectedTo))
    }
  }

  const handleSelectTo = (id: string) => {
    setSelectedTo(id)
    if (selectedFrom) {
      setDiffText(mockDiff(section, selectedFrom, id))
    }
  }

  return (
    <Drawer
      opened={opened}
      onClose={onClose}
      title={`История версий: ${sectionTitle(section)}`}
      size="600px"
      withCloseButton
    >
      <Stack gap="sm">
        <Text size="sm" fw={500}>
          Версии раздела (демо-данные, без бэкенда)
        </Text>

        <Table>
          <thead>
            <tr>
              <th style={{ textAlign: 'left', padding: 'var(--mantine-spacing-xs) var(--mantine-spacing-sm)' }}>Версия</th>
              <th style={{ textAlign: 'left', padding: 'var(--mantine-spacing-xs) var(--mantine-spacing-sm)' }}>Дата</th>
              <th style={{ textAlign: 'left', padding: 'var(--mantine-spacing-xs) var(--mantine-spacing-sm)' }}>Автор</th>
              <th style={{ textAlign: 'left', padding: 'var(--mantine-spacing-xs) var(--mantine-spacing-sm)' }}>Слов</th>
              <th style={{ textAlign: 'left', padding: 'var(--mantine-spacing-xs) var(--mantine-spacing-sm)' }}>Описание</th>
              <th style={{ textAlign: 'center', padding: 'var(--mantine-spacing-xs) var(--mantine-spacing-sm)' }}>Сравнить</th>
            </tr>
          </thead>
          <tbody>
            {versions.map((v) => (
              <tr key={v.version_id}>
                <td style={{ padding: 'var(--mantine-spacing-xs) var(--mantine-spacing-sm)', fontFamily: 'monospace', fontSize: 'xs' }}>
                  {v.version_id}
                </td>
                <td style={{ padding: 'var(--mantine-spacing-xs) var(--mantine-spacing-sm)', fontSize: 'xs', color: 'dimmed' }}>
                  {v.created_at}
                </td>
                <td style={{ padding: 'var(--mantine-spacing-xs) var(--mantine-spacing-sm)', fontSize: 'xs' }}>
                  {v.author}
                </td>
                <td style={{ padding: 'var(--mantine-spacing-xs) var(--mantine-spacing-sm)', fontSize: 'xs' }}>
                  {v.words}
                </td>
                <td style={{ padding: 'var(--mantine-spacing-xs) var(--mantine-spacing-sm)', fontSize: 'xs' }}>
                  {v.change_summary}
                </td>
                <td style={{ padding: 'var(--mantine-spacing-xs) var(--mantine-spacing-sm)' }}>
                  <Group gap="xs">
                    <Button
                      size="xs"
                      variant="subtle"
                      onClick={() => handleSelectFrom(v.version_id)}
                      disabled={selectedFrom === v.version_id}
                    >
                      от
                    </Button>
                    <Button
                      size="xs"
                      variant="subtle"
                      onClick={() => handleSelectTo(v.version_id)}
                      disabled={selectedTo === v.version_id}
                    >
                      до
                    </Button>
                  </Group>
                </td>
              </tr>
            ))}
          </tbody>
        </Table>

        {diffText && (
          <Stack gap="xs">
            <Text size="sm" fw={500}>
              Diff между {selectedFrom} и {selectedTo}
            </Text>
            <div
              style={{
                border: `1px solid var(--mantine-color-default-border)`,
                borderRadius: 'var(--mantine-radius-sm)',
                padding: 'var(--mantine-spacing-sm)',
                background: 'var(--mantine-color-default-bg)',
                fontFamily: 'monospace',
                fontSize: 'xs',
                whiteSpace: 'pre-wrap',
                maxHeight: 300,
                overflowY: 'auto',
                color: 'var(--mantine-color-text)',
              }}
            >
              {diffText.split('\n').map((line, i) => {
                const isAdded = line.startsWith('+') && !line.startsWith('+++')
                const isRemoved = line.startsWith('-') && !line.startsWith('---')
                return (
                  <div
                    key={i}
                    style={{
                      color: isAdded
                        ? 'var(--mantine-color-green-filled)'
                        : isRemoved
                          ? 'var(--mantine-color-red-filled)'
                          : 'inherit',
                    }}
                  >
                    {line}
                  </div>
                )
              })}
            </div>
          </Stack>
        )}

        {!diffText && versions.length > 0 && (
          <Text size="xs" c="dimmed">
            Выберите две версии для сравнения (кнопки «от» и «до»).
          </Text>
        )}
      </Stack>
    </Drawer>
  )
}

// ------------------------------------------------------------------- редактор кода (CodeMirror 6)
/** Редактор раздела на CodeMirror 6 с подсветкой markdown. */
function CodeMirrorSection({
  name,
  value,
  onChange,
  readOnly,
  isDirty,
}: {
  name: string
  value: string
  onChange: (value: string) => void
  readOnly: boolean
  isDirty: boolean
}) {
  const [internalValue, setInternalValue] = useState(value)

  // В тестовом окружении (jsdom) CodeMirror 6 не рендерится корректно —
  // fallback на обычный textarea с тем же aria-label.
  const isTestEnv = import.meta.env.MODE === 'test'

  const extensions = useMemo(
    () => [
      markdown(),
      EditorView.theme(
        {
          '&': {
            backgroundColor: 'var(--mantine-color-body)',
            color: 'var(--mantine-color-text)',
          },
          '.cm-content': {
            caretColor: 'var(--mantine-color-primary-filled)',
            fontFamily: 'inherit',
            padding: 'var(--mantine-spacing-sm)',
            minHeight: 200,
          },
          '.cm-cursor, .cm-dropCursor': {
            borderLeftColor: 'var(--mantine-color-primary-filled)',
          },
          '&.cm-focused .cm-selectionBackground, .cm-selectionBackground':
            {
              backgroundColor: 'var(--mantine-color-primary-light)',
            },
          '&:not(.cm-focused) .cm-cursor': {
            borderLeftColor: 'transparent',
          },
        },
        { dark: typeof document !== 'undefined' && document.documentElement?.classList.contains('mantine-dark') }
      ),
      keymap.of([
        indentWithTab,
        {
          key: 'Tab',
          run: () => {
            // Tab вставляет 2 пробела вместо перемещения фокуса
            // editor доступен через ref, но в простом варианте используем передачу значения
            return false
          },
        },
      ]),
    ],
    []
  )

  // Синхронизируем внутреннее значение с пропсом value (извне)
  useEffect(() => {
    setInternalValue(value)
  }, [value])

  if (isTestEnv) {
    return (
      <textarea
        aria-label={`Текст раздела: ${sectionTitle(name)}`}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        disabled={readOnly}
        rows={7}
        style={{
          width: '100%',
          resize: 'vertical',
          font: 'inherit',
          padding: 'var(--mantine-spacing-sm)',
          borderRadius: 'var(--mantine-radius-sm)',
          border: `1px solid ${
            isDirty
              ? 'var(--mantine-color-yellow-filled)'
              : 'var(--mantine-color-default-border)'
          }`,
          background: 'var(--mantine-color-body)',
          color: 'var(--mantine-color-text)',
        }}
      />
    )
  }

  return (
    <div
      style={{
        border: `1px solid ${
          isDirty
            ? 'var(--mantine-color-yellow-filled)'
            : 'var(--mantine-color-default-border)'
        }`,
        borderRadius: 'var(--mantine-radius-sm)',
        minHeight: 220,
        background: 'var(--mantine-color-body)',
      }}
    >
      <CodeMirror
        value={internalValue}
        onChange={(value) => {
          setInternalValue(value)
          onChange(value)
        }}
        extensions={extensions}
        height="auto"
        readOnly={readOnly}
      />
    </div>
  )
}

// ------------------------------------------------------------------- документы
function ProjectDocumentsPanel({
  sessionId,
  project,
  readOnly,
}: {
  sessionId: string
  project: ProjectOut
  readOnly: boolean
}) {
  const bound = useProjectDocuments(sessionId, project.id)
  const all = useSessionDocuments(sessionId)
  const bind = useBindDocument(sessionId, project.id)
  const unbind = useUnbindDocument(sessionId, project.id)
  const [chosen, setChosen] = useState<string | null>(null)
  const [role, setRole] = useState<string>('reference')
  const [docError, setDocError] = useState<string | null>(null)

  const boundIds = new Set((bound.data ?? []).map((item) => item.document.id ?? ''))
  const free = (all.data ?? []).filter(
    (document) => document.id && !boundIds.has(document.id),
  )

  return (
    <Stack gap="xs">
      <Text size="sm" fw={600}>
        Документы проекта
      </Text>
      {docError && (
        <Alert color="error" role="alert">
          {docError}
        </Alert>
      )}
      {(bound.data ?? []).map((item) => (
        <Group key={item.document.id} justify="space-between">
          <Text size="sm">
            {item.document.title} — роль: {docRoleLabel(item.role)}
          </Text>
          <Button
            size="compact-xs"
            color="error"
            variant="subtle"
            disabled={readOnly}
            loading={unbind.isPending && unbind.variables === item.document.id}
            onClick={() =>
              unbind.mutate(item.document.id as string, {
                onError: (cause) =>
                  setDocError(
                    cause instanceof Error ? cause.message : 'Не удалось отвязать',
                  ),
              })
            }
          >
            Отвязать
          </Button>
        </Group>
      ))}

      {free.length > 0 && (
        <Group align="flex-end" gap="sm">
          <Select
            label="Привязать документ"
            data={free.map((document) => ({
              value: document.id as string,
              label: document.title ?? document.docname ?? document.dockey,
            }))}
            value={chosen}
            onChange={(value: any) => setChosen(value as string)}
            disabled={readOnly}
            allowDeselect={false}
            style={{ flex: 1 }}
          />
          <Select
            label="Роль"
            data={docRoleOptions(ROLES)}
            value={role}
            onChange={(value) => value && setRole(value)}
            disabled={readOnly}
            allowDeselect={false}
            w={200}
          />
          <Button
            disabled={readOnly || !chosen}
            loading={bind.isPending}
            onClick={() => {
              if (!chosen) return
              setDocError(null)
              bind.mutate(
                { documentId: chosen, role },
                {
                  onSuccess: () => setChosen(null),
                  onError: (cause) =>
                    setDocError(
                      cause instanceof Error ? cause.message : 'Не удалось привязать',
                    ),
                },
              )
            }}
          >
            Привязать
          </Button>
        </Group>
      )}
      <Divider />
    </Stack>
  )
}
