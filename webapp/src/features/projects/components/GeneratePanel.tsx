import { Stack, Group, Select, TextInput, Button, Alert, Text, Tabs } from '@mantine/core'
import { IconSparkles, IconSearch, IconHistory } from '@tabler/icons-react'
import React, { useState } from 'react'
import { useGenerateSectionV2, useSectionPlans, usePreGenerationCheck } from '../hooks'
import { TaskPanel } from '../../../components/TaskPanel'
import { useSessionIndexingTasks } from '../../../features/documents/queries'
import { GenerateResultView } from './GenerateResultView'
import { GenerationHistoryPanel } from './GenerationHistoryPanel'
import { kindOptions } from '../../../lib/kinds'
import type { SectionVersion } from '../../../api/types'

interface GeneratePanelProps {
  sessionId: string
  project: { id: string }
  readOnly?: boolean
}

export function GeneratePanel({ sessionId, project, readOnly = false }: GeneratePanelProps) {
  const [activeTab, setActiveTab] = useState<'generate' | 'analyze' | 'history'>('generate')
  const [kind, setKind] = useState<string>('section')
  const [question, setQuestion] = useState('')
  const [section, setSection] = useState('')
  const [result, setResult] = useState<SectionVersion | null>(null)
  const [analysis, setAnalysis] = useState<string | null>(null)
  const [panelError, setPanelError] = useState<string | null>(null)
  const [checkEnabled, setCheckEnabled] = useState(false)
  const preCheck = usePreGenerationCheck(
    sessionId,
    project.id,
    section || null,
    question.trim() || null,
    3,
    checkEnabled,
  )

  const generateV2 = useGenerateSectionV2(sessionId, project.id)
  const { data: sectionPlans, isLoading: plansLoading } = useSectionPlans(sessionId, project.id)
  const draftAnalysis = React.useRef(
     
    () => import('../../../api/client').then((m) => m.client.draftAnalysis(sessionId, project.id))
  ).current

  const [draftAnalysisLoading, setDraftAnalysisLoading] = useState(false)
  const tasks = useSessionIndexingTasks(sessionId)
  const runningTasks = (tasks.data ?? []).filter(
    (task) => task.status === 'running' || task.status === 'queued',
  )

  const KINDS = [
    'section',
    'discussion',
    'literature_review',
    'data_comparison',
    'gap_analysis',
    'draft_analysis',
    'report',
  ] as const

  /**
   * Раздел, в который пишется результат вида, отличного от обычного.
   *
   * Для вида «раздел» раздел выбирает пользователь; остальные виды дают
   * свой материал (обзор литературы, сверка, обсуждение) — он попадает
   * в отдельный раздел с понятным именем.
   */
  const SECTION_FOR_KIND: Record<string, string> = {
    discussion: 'Discussion',
    literature_review: 'Literature Review',
    data_comparison: 'Data Comparison',
    gap_analysis: 'Gap Analysis',
    draft_analysis: 'Draft Analysis',
    report: 'Report',
  }

  function run() {
    setPanelError(null)
    setResult(null)
    const plan = (sectionPlans ?? []).find((p) => p.name === section)
    const target = kind === 'section' ? section : SECTION_FOR_KIND[kind] ?? kind
    generateV2.mutate({
      section: target,
      question: question.trim(),
      word_target: kind === 'section' ? plan?.word_target : undefined,
      // Вид из выпадающего списка едет в запрос: у каждого вида своя
      // постановка задачи (обзор литературы, сверка, обсуждение…).
      kind,
    }, {
      onSuccess: (data) => setResult(data),
      onError: (cause) =>
        setPanelError(cause instanceof Error ? cause.message : 'Генерация не удалась'),
    })
  }

  const sectionChoices = (sectionPlans ?? []).map((p) => ({
    value: p.name,
    label: p.name,
  }))

  const handleAnalyze = async () => {
    setPanelError(null)
    setAnalysis(null)
    setDraftAnalysisLoading(true)
    try {
      const data = await draftAnalysis()
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
                  (gap.excerpt ? ` — "${gap.excerpt}"` : ''),
              )
              .join('\n'),
        )
      }
    } catch (cause) {
      setPanelError(cause instanceof Error ? cause.message : 'Разбор не удался')
    } finally {
      setDraftAnalysisLoading(false)
    }
  }

  if (plansLoading) {
    return <Text size="sm" c="dimmed">Загрузка разделов…</Text>
  }

  return (
    <Stack gap="xs">
      <Tabs value={activeTab} onChange={(value) => setActiveTab(value as "generate" | "analyze" | "history")} variant="default">
        <Tabs.List>
          <Tabs.Tab value="generate">
            <Group gap="xs">
              <IconSparkles size={14} />
              <Text>Генерация</Text>
            </Group>
          </Tabs.Tab>
          <Tabs.Tab value="analyze">
            <Group gap="xs">
              <IconSearch size={14} />
              <Text>Анализ</Text>
            </Group>
          </Tabs.Tab>
          <Tabs.Tab value="history">
            <Group gap="xs">
              <IconHistory size={14} />
              <Text>История</Text>
            </Group>
          </Tabs.Tab>
        </Tabs.List>

        <Tabs.Panel value="generate">
          <Stack gap="xs">
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
              {kind === 'section' && sectionChoices.length > 0 && (
                <Select
                  label="Раздел"
                  data={sectionChoices}
                  value={section || null}
                  onChange={(value) => value && setSection(value)}
                  disabled={readOnly}
                  allowDeselect={false}
                  w={260}
                  placeholder="Выберите раздел"
                />
              )}
              {kind === 'section' && sectionChoices.length === 0 && (
                <Text size="sm" c="dimmed">Нет разделов для генерации. Создайте план в разделе «План разделов (новая система)» или нажмите «Предложить по стилю журнала».</Text>
              )}
              <TextInput
                label="Вопрос или тема"
                value={question}
                onChange={(event) => setQuestion(event.currentTarget.value)}
                disabled={readOnly}
                style={{ flex: 1 }}
              />
              <Button
                onClick={run}
                disabled={readOnly || !question.trim() || (kind === 'section' && !section)}
                loading={generateV2.isPending}
                leftSection={<IconSparkles size={14} />}
              >
                Запустить
              </Button>
              <Button
                variant="subtle"
                onClick={() => setCheckEnabled(true)}
                disabled={readOnly || !question.trim() || (kind === 'section' && !section)}
                loading={preCheck.isFetching}
              >
                Проверить готовность
              </Button>
            </Group>

            {preCheck.data && (
              <Alert
                color={preCheck.data.ready ? 'green' : 'yellow'}
                role="status"
                title={
                  preCheck.data.ready
                    ? 'К генерации всё готово'
                    : 'Проверьте перед генерацией'
                }
              >
                <Stack gap={2}>
                  {preCheck.data.warnings.map((warning) => (
                    <Text key={warning} size="xs">
                      {warning}
                    </Text>
                  ))}
                  <Text size="xs" c="dimmed">
                    {`Источников найдено: ${preCheck.data.checks.sources_found}`}
                  </Text>
                </Stack>
              </Alert>
            )}

            {panelError && <Alert color="error" role="alert">{panelError}</Alert>}

            {generateV2.isPending && (
              <Text size="sm" c="dimmed">
                Генерирую раздел — это может занять минуты…
              </Text>
            )}

            {result && (
              <Stack gap="xs">
                <Text fw={500}>Результат генерации</Text>
                <GenerateResultView
                  result={{
                    content_md: result.content_md,
                    citations_ok: result.quality_report.citations_ok,
                    warnings: result.quality_report.warnings,
                    references: result.citation_map.map((c: { docname?: string | null; title?: string | null; marker: string }) =>
                      `${c.docname || c.title || 'источник'} [${c.marker}]`,
                    ),
                  }}
                />
              </Stack>
            )}
          </Stack>
        </Tabs.Panel>

        <Tabs.Panel value="analyze">
          <Stack gap="xs">
            <Group>
              <Button
                variant="light"
                disabled={readOnly}
                loading={draftAnalysisLoading}
                leftSection={<IconSearch size={14} />}
                onClick={handleAnalyze}
              >
                Разбор черновика
              </Button>
            </Group>

            {panelError && <Alert color="error" role="alert">{panelError}</Alert>}

            {draftAnalysisLoading && (
              <Text size="sm" c="dimmed">Анализирую черновик…</Text>
            )}

            {analysis && (
              <Alert color={analysis === 'Пробелов не найдено.' ? 'green' : 'yellow'}>
                <Text component="div" size="sm" style={{ whiteSpace: 'pre-wrap' }}>
                  {analysis}
                </Text>
              </Alert>
            )}
          </Stack>
        </Tabs.Panel>

        <Tabs.Panel value="history">
          <GenerationHistoryPanel sessionId={sessionId} projectId={project.id} />
        </Tabs.Panel>
      </Tabs>
    </Stack>
  )
}
