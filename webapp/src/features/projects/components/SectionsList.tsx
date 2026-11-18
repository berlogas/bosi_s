import { Stack, Group, Button, Text, Alert, Badge, TextInput } from '@mantine/core'
import { Accordion } from '@mantine/core'
import { SkeletonList } from '../../../components/SkeletonList'
import { IconChevronDown, IconChevronUp, IconFilePencil, IconHistory, IconSparkles } from '@tabler/icons-react'
import React, { useState, useEffect, useRef } from 'react'
import { useSectionPlans, useGenerateSectionV2, useSaveSectionContent } from '../hooks'
import { SectionHistoryView } from './SectionHistoryView'
import { EmptySectionsState } from './EmptyState'
import { GenerateResultView } from './GenerateResultView'
import { CodeMirrorSection } from './CodeMirrorSection'
import type { AnswerSource, ProjectOut, SectionPlan, SectionVersion } from '../../../api/types'

const STATUS_LABELS: Record<string, string> = {
  pending: 'Ожидает',
  in_progress: 'В работе',
  review: 'На ревью',
  approved: 'Утверждён',
}

const STATUS_COLORS: Record<string, string> = {
  pending: 'gray',
  in_progress: 'blue',
  review: 'yellow',
  approved: 'green',
}

function formatReferences(citationMap: AnswerSource[]): string[] {
  return citationMap.map(function(c) {
    const name = c.docname || c.title || 'источник'
    return name + ' [' + c.marker + ']'
  })
}

/** Текст раздела, сохранённый на сервере (текущая версия плана). */
function serverText(plan: SectionPlan): string {
  return plan.current_version?.content_md ?? ''
}

/** Результат генерации вместе с планом, к которому он относится. */
interface GenResult {
  planId: string
  data: SectionVersion
}

interface SectionPlanItemProps {
  plan: SectionPlan
  readOnly: boolean
  generatingPlanId: string | null
  genResult: GenResult | null
  questions: Record<string, string>
  setQuestions: (next: Record<string, string>) => void
  handleGenerate: (plan: SectionPlan) => void
  setVersionHistoryPlanId: (id: string) => void
  setVersionHistoryOpen: (open: boolean) => void
  drafts: Record<string, string>
  setDrafts: (updater: (current: Record<string, string>) => Record<string, string>) => void
  saveSection: {
    isPending: boolean
    variables: { planId: string } | undefined
    mutate: (
      input: { planId: string; contentMd: string },
      options?: { onSuccess?: () => void },
    ) => void
  }
}

function SectionPlanItem(props: SectionPlanItemProps) {
  const plan = props.plan
  const readOnly = props.readOnly
  const generatingPlanId = props.generatingPlanId
  const genResult = props.genResult
  const questions = props.questions
  const setQuestions = props.setQuestions
  const handleGenerate = props.handleGenerate
  const setVersionHistoryPlanId = props.setVersionHistoryPlanId
  const setVersionHistoryOpen = props.setVersionHistoryOpen
  const drafts = props.drafts
  const setDrafts = props.setDrafts
  const saveSection = props.saveSection

  const placeholderText = 'Что написать в разделе "' + plan.name + '"?'

  // Редактор показывает серверный текст; несохранённая правка лежит в drafts.
  const saved = serverText(plan)
  const draft = drafts[plan.id]
  const value = draft !== undefined ? draft : saved
  const dirty = draft !== undefined && draft !== saved

  return (
    <Accordion.Item key={plan.id} value={plan.id}>
      <Accordion.Control>
        <Group gap="xs" style={{ alignItems: 'center', flexWrap: 'wrap' }}>
          <Text fw={500}>{plan.name}</Text>
          <Text size="sm" c="dimmed">
            порядок {plan.order} · {plan.word_target} слов
          </Text>
          <Badge
            size="xs"
            color={STATUS_COLORS[plan.status] || 'gray'}
          >
            {STATUS_LABELS[plan.status] || plan.status}
          </Badge>
        </Group>
      </Accordion.Control>
      <Accordion.Panel>
        <Stack gap="xs">
          <Text size="sm">{plan.notes}</Text>
          <TextInput
            label="Вопрос / тема раздела"
            placeholder={placeholderText}
            value={questions[plan.id] || ''}
            onChange={function(e) {
              setQuestions({ ...questions, [plan.id]: e.currentTarget.value })
            }}
            disabled={readOnly || generatingPlanId === plan.id}
          />
          <Group gap="xs">
            <Button
              size="xs"
              onClick={function() { handleGenerate(plan) }}
              disabled={readOnly || generatingPlanId === plan.id}
              loading={generatingPlanId === plan.id}
              leftSection={<IconSparkles size={12} />}
            >
              Сгенерировать
            </Button>
            <Button
              size="xs"
              onClick={function() {
                setVersionHistoryPlanId(plan.id)
                setVersionHistoryOpen(true)
              }}
              leftSection={<IconHistory size={12} />}
            >
              История версий
            </Button>
            <Button
              size="xs"
              variant="light"
              leftSection={<IconFilePencil size={12} />}
              disabled={readOnly || !dirty}
              loading={saveSection.isPending && saveSection.variables?.planId === plan.id}
              onClick={function() {
                saveSection.mutate(
                  { planId: plan.id, contentMd: value },
                  {
                    onSuccess: function() {
                      // Серверный текст стал равен черновику — правка больше не «грязная».
                      setDrafts(function(current) {
                        const next = { ...current }
                        delete next[plan.id]
                        return next
                      })
                    },
                  },
                )
              }}
            >
              Сохранить
            </Button>
          </Group>
          {/* Текст раздела: серверная версия или несохранённая правка. */}
          <CodeMirrorSection
            name={plan.name}
            value={value}
            readOnly={readOnly}
            isDirty={dirty}
            onChange={function(next: string) {
              setDrafts(function(current) {
                return { ...current, [plan.id]: next }
              })
            }}
          />
          {genResult && genResult.planId === plan.id && (
            <Stack gap="xs">
              <Text fw={500}>Результат генерации</Text>
              <GenerateResultView
                result={{
                  content_md: genResult.data.content_md,
                  citations_ok: genResult.data.quality_report?.citations_ok ?? true,
                  warnings: genResult.data.quality_report?.warnings ?? [],
                  references: formatReferences(genResult.data.citation_map),
                }}
              />
            </Stack>
          )}
        </Stack>
      </Accordion.Panel>
    </Accordion.Item>
  )
}

interface SectionsListProps {
  sessionId: string
  project: ProjectOut
  readOnly: boolean
}

export function SectionsList(props: SectionsListProps) {
  const sessionId = props.sessionId
  const project = props.project
  const readOnly = props.readOnly

  const { data: sectionPlans, isLoading: plansLoading, isError, error } = useSectionPlans(sessionId, project.id)

  const [expandedPlans, setExpandedPlans] = useState<string[]>([])
  const [versionHistoryOpen, setVersionHistoryOpen] = useState(false)
  const [versionHistoryPlanId, setVersionHistoryPlanId] = useState<string | null>(null)
  const [generatingPlanId, setGeneratingPlanId] = useState<string | null>(null)
  const [genResult, setGenResult] = useState<GenResult | null>(null)
  const [questions, setQuestions] = useState<Record<string, string>>({})
  const [drafts, setDrafts] = useState<Record<string, string>>({})
  const expandedOnce = useRef(false)

  const generateV2 = useGenerateSectionV2(sessionId, project.id)
  const saveSection = useSaveSectionContent(sessionId, project.id)

  useEffect(function() {
    if (sectionPlans && sectionPlans.length > 0) {
      // Разворачиваем разделы, которые ждут генерации, и те, где текст уже есть:
      // иначе сохранённый текст не виден, пока пользователь не откроет панель руками.
      // Только при первой загрузке — иначе обновление списка (после правки или
      // генерации) схлопнуло бы разделы, которые пользователь открыл сам.
      if (!expandedOnce.current) {
        expandedOnce.current = true
        setExpandedPlans(
          sectionPlans
            .filter(function(p) { return p.status === 'pending' || serverText(p).trim() })
            .map(function(p) { return p.id }),
        )
      }
      setQuestions(function(current: Record<string, string>) {
        const next = { ...current }
        for (let _i = 0; _i < sectionPlans.length; _i++) {
          const p = sectionPlans[_i]
          // Введённый вопрос не затираем обновлением списка планов.
          if (!next[p.id]) {
            next[p.id] = 'Напиши раздел "' + p.name + '"'
          }
        }
        return next
      })
    }
  }, [sectionPlans])

  if (isError) {
    return (
      <Alert color="error" role="alert">
        {error instanceof Error ? error.message : 'Не удалось загрузить разделы'}
      </Alert>
    )
  }

  if (plansLoading) {
    return <SkeletonList count={3} />
  }

  if ((sectionPlans || []).length === 0) {
    return <EmptySectionsState />
  }

  function handleGenerate(plan: SectionPlan) {
    setGeneratingPlanId(plan.id)
    const question = questions[plan.id] || plan.name
    setGenResult(null)
    generateV2.mutate({
      section: plan.name,
      question: question,
      word_target: plan.word_target,
    }, {
      onSuccess: function(data) {
        setGenResult({ planId: plan.id, data: data })
        setGeneratingPlanId(null)
        // Сгенерированный текст стал серверным — черновик больше не нужен.
        setDrafts(function(current) {
          const next = { ...current }
          delete next[plan.id]
          return next
        })
      },
      onError: function(cause) {
        setGeneratingPlanId(null)
        alert(cause instanceof Error ? cause.message : 'Генерация не удалась')
      },
    })
  }

  return (
    <Stack gap="xs">
      <Group align="flex-end" gap="sm">
        <Text size="sm" fw={600}>Разделы (SectionPlan)</Text>
        <Group gap="xs">
          <Button
            variant="subtle"
            size="sm"
            leftSection={<IconChevronDown size={12} />}
            onClick={function() { setExpandedPlans((sectionPlans || []).map(function(p) { return p.id })) }}
          >
            Развернуть все
          </Button>
          <Button
            variant="subtle"
            size="sm"
            leftSection={<IconChevronUp size={12} />}
            onClick={function() { setExpandedPlans([]) }}
          >
            Свернуть все
          </Button>
        </Group>
      </Group>

      <Accordion
        key={(sectionPlans || []).map(function(p) { return p.id }).join('|')}
        value={expandedPlans}
        onChange={function(values) { setExpandedPlans(values as string[]) }}
        multiple
      >
        {(sectionPlans || []).map(function(plan) {
          return (
            <SectionPlanItem
              key={plan.id}
              plan={plan}
              readOnly={readOnly}
              generatingPlanId={generatingPlanId}
              genResult={genResult}
              questions={questions}
              setQuestions={setQuestions}
              handleGenerate={handleGenerate}
              setVersionHistoryPlanId={setVersionHistoryPlanId}
              setVersionHistoryOpen={setVersionHistoryOpen}
              drafts={drafts}
              setDrafts={setDrafts}
              saveSection={saveSection}
            />
          )
        })}
      </Accordion>

      {versionHistoryPlanId && versionHistoryOpen && (
        <SectionHistoryView
          sessionId={sessionId}
          projectId={project.id}
          planId={versionHistoryPlanId}
        />
      )}
    </Stack>
  )
}
