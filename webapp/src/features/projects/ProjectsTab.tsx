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
  Button,
  Divider,
  Group,
  Loader,
  Select,
  Stack,
  Text,
  TextInput,
  UnstyledButton,
} from '@mantine/core'
import { useMutation } from '@tanstack/react-query'
import { useEffect, useMemo, useState } from 'react'

import { client } from '../../api/client'
import type { GenerateResult, ProjectOut } from '../../api/types'
import { MarkdownText } from '../../components/MarkdownText'
import { TaskPanel } from '../../components/TaskPanel'
import { loadDrafts, saveDraft } from './drafts'
import {
  useBindDocument,
  useCreateProject,
  useDeleteProject,
  useGenerate,
  usePatchProject,
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

const KINDS = [
  'section',
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
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [title, setTitle] = useState('')
  const [journal, setJournal] = useState('')
  const [createError, setCreateError] = useState<string | null>(null)
  const create = useCreateProject(sessionId)
  const patch = usePatchProject(sessionId)
  const remove = useDeleteProject(sessionId)
  const [statusValue, setStatusValue] = useState<string | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)

  const list = useMemo(() => projects.data ?? [], [projects.data])

  // первый проект выбран по умолчанию (в Streamlit — current_project_id)
  useEffect(() => {
    if (selectedId === null && list.length > 0) setSelectedId(list[0]?.id ?? null)
    if (selectedId !== null && !list.some((project) => project.id === selectedId)) {
      setSelectedId(list[0]?.id ?? null)
    }
  }, [list, selectedId])

  const selected = list.find((project) => project.id === selectedId) ?? null

  useEffect(() => {
    setStatusValue(selected?.status ?? null)
  }, [selected?.status])

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

  return (
    <Stack gap="sm">
      <Text fw={600}>Проекты статей</Text>

      {actionError && (
        <Alert color="red" role="alert">
          {actionError}
        </Alert>
      )}

      {/* ---------------------------------------------------- создание */}
      <Group align="flex-end" gap="sm">
        <TextInput
          label="Название"
          value={title}
          onChange={(event) => setTitle(event.currentTarget.value)}
          disabled={readOnly}
          style={{ flex: 2 }}
        />
        <TextInput
          label="Целевой журнал"
          value={journal}
          onChange={(event) => setJournal(event.currentTarget.value)}
          disabled={readOnly}
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
      {createError && (
        <Alert color="red" role="alert">
          {createError}
        </Alert>
      )}

      {projects.isError && (
        <Alert color="red" role="alert">
          {projects.error instanceof Error
            ? projects.error.message
            : 'Не удалось загрузить проекты'}
        </Alert>
      )}

      {list.length === 0 && !projects.isPending && (
        <Text size="sm" c="dimmed">
          Проектов нет — создайте первый.
        </Text>
      )}

      {selected && (
        <ProjectEditor
          sessionId={sessionId}
          project={selected}
          readOnly={readOnly}
          statusValue={statusValue}
          onStatusChange={setStatusValue}
          onSaveStatus={() => {
            setActionError(null)
            patch.mutate(
              { projectId: selected.id, fields: { status: statusValue ?? undefined } },
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
          onSelect={setSelectedId}
          projectOptions={list}
        />
      )}
    </Stack>
  )
}

// --------------------------------------------------------------------------- редактор
interface ProjectEditorProps {
  sessionId: string
  project: ProjectOut
  readOnly: boolean
  statusValue: string | null
  onStatusChange: (value: string) => void
  onSaveStatus: () => void
  onDelete: () => void
  deleting: boolean
  onSelect: (id: string) => void
  projectOptions: ProjectOut[]
}

function ProjectEditor({
  sessionId,
  project,
  readOnly,
  statusValue,
  onStatusChange,
  onSaveStatus,
  onDelete,
  deleting,
  onSelect,
  projectOptions,
}: ProjectEditorProps) {
  const progress = useProjectProgress(sessionId, project.id)

  return (
    <Stack gap="sm">
      <Group align="flex-end" gap="sm">
        <Select
          label="Проект"
          data={projectOptions.map((item) => ({
            value: item.id,
            label: `${item.title} (${item.status})`,
          }))}
          value={project.id}
          onChange={(value) => value && onSelect(value)}
          allowDeselect={false}
          style={{ flex: 2 }}
        />
        <Select
          label="Статус"
          data={[...STATUSES]}
          value={statusValue}
          onChange={(value) => value && onStatusChange(value)}
          disabled={readOnly}
          allowDeselect={false}
          w={160}
        />
        <Button
          variant="default"
          onClick={onSaveStatus}
          disabled={readOnly || statusValue === project.status}
        >
          Обновить
        </Button>
        <Button
          color="red"
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
              height: 8,
              borderRadius: 4,
              background: 'var(--mantine-color-default-border)',
              overflow: 'hidden',
              marginTop: 4,
            }}
          >
            <div
              style={{
                width: `${Math.min(100, progress.data.percent)}%`,
                height: '100%',
                background: 'var(--mantine-color-blue-6)',
                transition: 'width 0.3s',
              }}
            />
          </div>
        </div>
      )}

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
          data={[...KINDS]}
          value={kind}
          onChange={(value) => value && setKind(value)}
          disabled={readOnly}
          allowDeselect={false}
          w={200}
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
                            `- **${gap.severity}** · ${gap.where}: ${gap.hint}` +
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
        <Alert color="red" role="alert">
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
      <MarkdownText text={result.content_md} />
      {!result.citations_ok && (
        <Text size="sm" c="orange">
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
  const [sectionError, setSectionError] = useState<string | null>(null)
  /** Результат генерации — под своим разделом (как в _generate). */
  const [genResult, setGenResult] = useState<{
    name: string
    data: GenerateResult
  } | null>(null)

  function valueOf(name: string, serverValue: string): string {
    return drafts[name] ?? serverValue
  }

  function handleChange(name: string, value: string) {
    setDrafts((current) => ({ ...current, [name]: value }))
    saveDraft(sessionId, name, value)
    setSavedName(null)
  }

  function handleSave(name: string, value: string) {
    setSectionError(null)
    save.mutate(
      { name, contentMd: value },
      {
        onSuccess: () => setSavedName(name),
        onError: (cause) =>
          setSectionError(
            cause instanceof Error ? cause.message : 'Не удалось сохранить раздел',
          ),
      },
    )
  }

  if (sections.isError) {
    return (
      <Alert color="red" role="alert">
        {sections.error instanceof Error
          ? sections.error.message
          : 'Не удалось загрузить разделы'}
      </Alert>
    )
  }

  return (
    <Stack gap="xs">
      <Text size="sm" fw={600}>
        Разделы
      </Text>
      {sectionError && (
        <Alert color="red" role="alert">
          {sectionError}
        </Alert>
      )}
      {generate.isPending && (
        <Text size="sm" c="dimmed">
          Генерирую раздел — это может занять минуты…
        </Text>
      )}
      {sections.isPending && <Loader size="sm" />}
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
          return (
            <Accordion.Item key={section.name} value={section.name}>
              <Accordion.Control>
                {section.name} — {section.word_target} слов
              </Accordion.Control>
              <Accordion.Panel>
                <Stack gap="xs">
                  <textarea
                    aria-label={`Текст раздела: ${section.name}`}
                    value={value}
                    onChange={(event) => handleChange(section.name, event.target.value)}
                    disabled={readOnly}
                    rows={7}
                    style={{
                      width: '100%',
                      resize: 'vertical',
                      font: 'inherit',
                      padding: 'var(--mantine-spacing-sm)',
                      borderRadius: 'var(--mantine-radius-sm)',
                      border: '1px solid var(--mantine-color-default-border)',
                      background: 'var(--mantine-color-body)',
                      color: 'var(--mantine-color-text)',
                    }}
                  />
                  <Group justify="space-between">
                    <Text size="xs" c="dimmed">
                      написано слов: {section.words}
                    </Text>
                    <Group gap="xs">
                      <Button
                        size="xs"
                        onClick={() => handleSave(section.name, value)}
                        disabled={readOnly}
                        loading={
                          save.isPending && save.variables?.name === section.name
                        }
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
                    <Text size="sm" c="green">
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
    </Stack>
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
        <Alert color="red" role="alert">
          {docError}
        </Alert>
      )}
      {(bound.data ?? []).map((item) => (
        <Group key={item.document.id} justify="space-between">
          <Text size="sm">
            {item.document.title} — роль: {item.role}
          </Text>
          <Button
            size="compact-xs"
            color="red"
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
            onChange={setChosen}
            disabled={readOnly}
            allowDeselect={false}
            style={{ flex: 1 }}
          />
          <Select
            label="Роль"
            data={[...ROLES]}
            value={role}
            onChange={(value) => value && setRole(value)}
            disabled={readOnly}
            allowDeselect={false}
            w={140}
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
