import { Stack, Accordion, Group, Text, Progress, TextInput, Select } from '@mantine/core'
import { IconSettings, IconFileText, IconDownload, IconFiles, IconHistory } from '@tabler/icons-react'
import React from 'react'
import { useProjectProgress, useJournalStyles, usePatchProject } from '../queries'
import { useSectionPlans } from '../hooks'
import { StyleGuideSelector } from './StyleGuideSelector'
import { ExportPanel } from './ExportPanel'
import { GeneratePanel } from './GeneratePanel'
import { SectionsList } from './SectionsList'
import { SectionPlanEditor } from './SectionPlanEditor'
import { SectionHistoryView } from './SectionHistoryView'
import { ManuscriptPanel } from './ManuscriptPanel'
import { GlossaryPanel } from './GlossaryPanel'
import { ProjectDocumentsPanel } from '../ProjectDocumentsPanel'
import { projectStatusOptions, STATUSES } from '../../../lib/projectOptions'
import type { ProjectOut } from '../../../api/types'

interface ProjectEditorProps {
  sessionId: string
  project: ProjectOut
  readOnly?: boolean
}

export function ProjectEditor({ sessionId, project, readOnly = false }: ProjectEditorProps) {
  const progress = useProjectProgress(sessionId, project.id)
  const patch = usePatchProject(sessionId)
  const styles = useJournalStyles()
  const { data: sectionPlans } = useSectionPlans(sessionId, project.id)

  const journalChoices = (styles.data ?? []).map((item) => ({
    value: item.key,
    label: item.title,
  }))

  // Основные мировые языки (ISO 639-1 коды)
  const languageChoices = [
    { value: 'ru', label: 'Русский (Russian)' },
    { value: 'en', label: 'English (Английский)' },
    { value: 'zh', label: '中文 (Chinese)' },
    { value: 'es', label: 'Español (Spanish)' },
    { value: 'hi', label: 'हिन्दी (Hindi)' },
    { value: 'ar', label: 'العربية (Arabic)' },
    { value: 'pt', label: 'Português (Portuguese)' },
    { value: 'bn', label: 'বাংলা (Bengali)' },
    { value: 'fr', label: 'Français (French)' },
    { value: 'de', label: 'Deutsch (German)' },
    { value: 'ja', label: '日本語 (Japanese)' },
    { value: 'ko', label: '한국어 (Korean)' },
    { value: 'tr', label: 'Türkçe (Turkish)' },
    { value: 'vi', label: 'Tiếng Việt (Vietnamese)' },
    { value: 'it', label: 'Italiano (Italian)' },
    { value: 'pl', label: 'Polski (Polish)' },
    { value: 'uk', label: 'Українська (Ukrainian)' },
    { value: 'nl', label: 'Nederlands (Dutch)' },
    { value: 'cs', label: 'Čeština (Czech)' },
    { value: 'he', label: 'עברית (Hebrew)' },
    { value: 'id', label: 'Bahasa Indonesia (Indonesian)' },
    { value: 'fa', label: 'فارسی (Persian)' },
    { value: 'th', label: 'ไทย (Thai)' },
    { value: 'ro', label: 'Română (Romanian)' },
    { value: 'hu', label: 'Magyar (Hungarian)' },
    { value: 'el', label: 'Ελληνικά (Greek)' },
    { value: 'sv', label: 'Svenska (Swedish)' },
    { value: 'da', label: 'Dansk (Danish)' },
    { value: 'no', label: 'Norsk (Norwegian)' },
    { value: 'fi', label: 'Suomi (Finnish)' },
  ]

  return (
    <Stack gap="sm">
      {progress.data && (
        <div>
          <Group justify="space-between">
            <Text size="sm">
              {progress.data.written}/{progress.data.sections} разделов · {progress.data.words} слов
            </Text>
            <Text size="sm" c="dimmed">
              {progress.data.percent}%
            </Text>
          </Group>
          <Progress value={progress.data.percent} size="sm" color="blue" striped />
        </div>
      )}

      <Accordion multiple>
        <Accordion.Item value="settings">
          <Accordion.Control>
            <Group>
              <IconSettings size={16} />
              <Text fw={500}>Настройки проекта</Text>
            </Group>
          </Accordion.Control>
          <Accordion.Panel>
            <Stack gap="sm" mt="xs">
              <Group gap="sm">
                <TextInput
                  label="Название проекта"
                  value={project.title}
                  onChange={(e) =>
                    patch.mutate({
                      projectId: project.id,
                      fields: { title: e.currentTarget.value },
                    })
                  }
                  disabled={readOnly}
                  style={{ flex: 2 }}
                />
                <Select
                  label="Стиль журнала"
                  placeholder="Выберите стиль"
                  data={journalChoices}
                  value={project.target_journal || null}
                  onChange={(value) =>
                    value &&
                    patch.mutate({
                      projectId: project.id,
                      fields: { target_journal: value },
                    })
                  }
                  disabled={readOnly}
                  searchable
                  allowDeselect
                  style={{ flex: 2 }}
                />
              </Group>
              <Group gap="sm">
                <Select
                  label="Статус"
                  data={projectStatusOptions(STATUSES)}
                  value={project.status}
                  onChange={(value) =>
                    value &&
                    patch.mutate({
                      projectId: project.id,
                      fields: { status: value },
                    })
                  }
                  disabled={readOnly}
                  allowDeselect={false}
                  w={260}
                  size="sm"
                />
                <Select
                  label="Язык"
                  placeholder="Выберите язык"
                  data={languageChoices}
                  value={project.language || 'ru'}
                  onChange={(value) =>
                    value &&
                    patch.mutate({
                      projectId: project.id,
                      fields: { language: value },
                    })
                  }
                  disabled={readOnly}
                  allowDeselect={false}
                  w={260}
                  size="sm"
                  searchable
                />
              </Group>
            </Stack>
          </Accordion.Panel>
        </Accordion.Item>

        <Accordion.Item value="documents">
          <Accordion.Control>
            <Group>
              <IconFiles size={16} />
              <Text fw={500}>Документы проекта</Text>
            </Group>
          </Accordion.Control>
          <Accordion.Panel>
            <ProjectDocumentsPanel sessionId={sessionId} projectId={project.id} readOnly={readOnly} />
          </Accordion.Panel>
        </Accordion.Item>

        <Accordion.Item value="style-guide">
          <Accordion.Control>
            <Group>
              <IconFileText size={16} />
              <Text fw={500}>Правила оформления журнала</Text>
            </Group>
          </Accordion.Control>
          <Accordion.Panel>
            <Stack gap="sm" mt="xs">
              <Text size="sm" c="dimmed">
                Привяжите документ с ролью "Правила оформления журнала" в панели документов ниже.
                Он будет использоваться при генерации и экспорте.
              </Text>
              <StyleGuideSelector sessionId={sessionId} project={project} readOnly={readOnly} />
            </Stack>
          </Accordion.Panel>
        </Accordion.Item>

        <Accordion.Item value="export">
          <Accordion.Control>
            <Group>
              <IconDownload size={16} />
              <Text fw={500}>Экспорт</Text>
            </Group>
          </Accordion.Control>
          <Accordion.Panel>
            <ExportPanel sessionId={sessionId} project={project} />
          </Accordion.Panel>
        </Accordion.Item>
      </Accordion>

      <Accordion multiple>
        <Accordion.Item value="plan">
          <Accordion.Control>
            <Group>
              <IconFiles size={16} />
              <Text fw={500}>План разделов</Text>
            </Group>
          </Accordion.Control>
          <Accordion.Panel>
            <SectionPlanEditor sessionId={sessionId} projectId={project.id} readOnly={readOnly} projectTargetJournal={project.target_journal} />
          </Accordion.Panel>
        </Accordion.Item>

        <Accordion.Item value="history">
          <Accordion.Control>
            <Group>
              <IconHistory size={16} />
              <Text fw={500}>История версий</Text>
            </Group>
          </Accordion.Control>
          <Accordion.Panel>
            {(sectionPlans ?? []).map((plan) => (
              <div key={plan.id} style={{ marginBottom: 16 }}>
                <Text fw={500} style={{ marginBottom: 8 }}>{plan.name}</Text>
                <SectionHistoryView
                  sessionId={sessionId}
                  projectId={project.id}
                  planId={plan.id}
                />
              </div>
            ))}
          </Accordion.Panel>
        </Accordion.Item>
        <Accordion.Item value="glossary">
          <Accordion.Control>
            <Group gap="xs">
              <IconFileText size={16} />
              <Text fw={500}>Глоссарий терминов</Text>
            </Group>
          </Accordion.Control>
          <Accordion.Panel>
            <GlossaryPanel sessionId={sessionId} projectId={project.id} />
          </Accordion.Panel>
        </Accordion.Item>

        <Accordion.Item value="manuscript">
          <Accordion.Control>
            <Group gap="xs">
              <IconFileText size={16} />
              <Text fw={500}>Сборка статьи</Text>
            </Group>
          </Accordion.Control>
          <Accordion.Panel>
            <ManuscriptPanel
              sessionId={sessionId}
              projectId={project.id}
              language={project.language || 'ru'}
            />
          </Accordion.Panel>
        </Accordion.Item>
      </Accordion>

      <GeneratePanel sessionId={sessionId} project={project} readOnly={readOnly} />
      <SectionsList sessionId={sessionId} project={project} readOnly={readOnly} />
    </Stack>
  )
}