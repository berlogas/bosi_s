/**
 * История версий раздела: дерево, текст версии, сравнение и перевод.
 *
 * Перевод — на язык, заданный в языковой политике проекта: он делает
 * отдельную версию с пометкой source_language, поэтому исходник остаётся.
 */

import { useEffect, useMemo, useState } from 'react'
import { Stack, Paper, Text, Group, Button, Select, Alert } from '@mantine/core'
import { IconLanguage } from '@tabler/icons-react'
import { notifications } from '@mantine/notifications'

import {
  useSectionHistory,
  useRollbackSection,
  useApproveSection,
  useDiffSectionVersions,
  useTranslateSectionV2,
  useStyleCompliance,
} from '../hooks'
import { VersionTreeView } from './VersionTreeView'
import { SemanticDiffView } from './SemanticDiffView'
import { MarkdownText } from '../../../components/MarkdownText'

const LANGUAGES = [
  { value: 'ru', label: 'Русский (ru)' },
  { value: 'en', label: 'English (en)' },
  { value: 'de', label: 'Deutsch (de)' },
  { value: 'zh', label: '中文 (zh)' },
  { value: 'es', label: 'Español (es)' },
  { value: 'fr', label: 'Français (fr)' },
  { value: 'pt', label: 'Português (pt)' },
  { value: 'ja', label: '日本語 (ja)' },
]

interface SectionHistoryViewProps {
  sessionId: string
  projectId: string
  planId: string
}

export function SectionHistoryView({
  sessionId,
  projectId,
  planId,
}: SectionHistoryViewProps) {
  const {
    data: tree,
    isLoading,
    error,
  } = useSectionHistory(sessionId, projectId, planId)
  const rollback = useRollbackSection(sessionId, projectId)
  const approve = useApproveSection(sessionId, projectId)
  const translate = useTranslateSectionV2(sessionId, projectId)
  const [selectedVersionId, setSelectedVersionId] = useState<string | null>(null)
  const [diffFrom, setDiffFrom] = useState<string | null>(null)
  const [diffTo, setDiffTo] = useState<string | null>(null)
  const [targetLanguage, setTargetLanguage] = useState<string | null>(null)

  const versions = useMemo(() => tree?.all_versions ?? [], [tree])

  // Открыли историю — показываем последнюю версию сразу: иначе пользователь
  // видит только дерево и не понимает, какой текст у раздела сейчас.
  useEffect(() => {
    if (versions.length === 0) return
    setSelectedVersionId((current) =>
      current && versions.some((v) => v.id === current)
        ? current
        : versions[versions.length - 1].id,
    )
  }, [versions])

  const diff = useDiffSectionVersions(sessionId, projectId, diffFrom, diffTo)
  const [styleCheckOn, setStyleCheckOn] = useState(false)
  const style = useStyleCompliance(
    styleCheckOn ? sessionId : null,
    styleCheckOn ? projectId : null,
    planId,
    selectedVersionId,
  )

  if (isLoading) {
    return (
      <div style={{ padding: 16, color: 'var(--mantine-color-gray-5)' }}>
        Загрузка истории…
      </div>
    )
  }

  if (error) {
    return (
      <div style={{ padding: 16, color: 'var(--mantine-color-red-6)' }}>
        Ошибка загрузки истории
      </div>
    )
  }

  if (!tree || tree.roots.length === 0) {
    return (
      <div style={{ padding: 16, color: 'var(--mantine-color-gray-5)' }}>
        Нет версий для этого раздела
      </div>
    )
  }

  const selected = versions.find((v) => v.id === selectedVersionId) ?? null
  const versionOptions = versions.map((version) => ({
    value: version.id,
    label: `${new Date(version.created_at).toLocaleString('ru-RU')} · ${version.word_count} слов · ${version.status}`,
  }))

  const handleRollback = (versionId: string) => {
    rollback.mutate(
      { planId, versionId },
      {
        onSuccess: () =>
          notifications.show({ title: 'Раздел откатан', message: '', color: 'green' }),
        onError: (cause) =>
          notifications.show({
            title: 'Не удалось откатить',
            message: cause instanceof Error ? cause.message : '',
            color: 'red',
          }),
      },
    )
  }

  const handleApprove = (versionId: string) => {
    approve.mutate(
      { planId, versionId },
      {
        onSuccess: () =>
          notifications.show({ title: 'Версия одобрена', message: '', color: 'green' }),
        onError: (cause) =>
          notifications.show({
            title: 'Не удалось одобрить',
            message: cause instanceof Error ? cause.message : '',
            color: 'red',
          }),
      },
    )
  }

  const handleTranslate = () => {
    if (!targetLanguage || !selected) return
    translate.mutate(
      { planId, targetLanguage, versionId: selected.id },
      {
        onSuccess: () =>
          notifications.show({ title: 'Перевод готов', message: '', color: 'green' }),
        onError: (cause) =>
          notifications.show({
            title: 'Не удалось перевести',
            message: cause instanceof Error ? cause.message : '',
            color: 'red',
          }),
      },
    )
  }

  return (
    <Stack gap="md">
      <VersionTreeView
        tree={tree}
        onSelectVersion={setSelectedVersionId}
        selectedVersionId={selectedVersionId}
        canRollback
        onRollback={handleRollback}
        canApprove
        onApprove={handleApprove}
      />

      {selected && (
        <Paper withBorder p="sm">
          <Text size="sm" fw={500} mb={4}>
            Версия от {new Date(selected.created_at).toLocaleString('ru-RU')} ·{' '}
            {selected.word_count} слов
          </Text>
          <MarkdownText text={selected.content_md ?? ''} />
          <Group mt="sm" gap="xs" align="flex-end">
            <Select
              label="Перевести на язык"
              aria-label="Язык перевода раздела"
              data={LANGUAGES}
              value={targetLanguage}
              onChange={(value) => setTargetLanguage(value ? String(value) : null)}
              allowDeselect={false}
              w={220}
            />
            <Button
              size="xs"
              leftSection={<IconLanguage size={14} />}
              onClick={handleTranslate}
              disabled={!targetLanguage}
              loading={translate.isPending}
            >
              Перевести раздел
            </Button>
          </Group>
          {translate.isError && (
            <Alert color="red" role="alert" mt="xs">
              {translate.error instanceof Error
                ? translate.error.message
                : 'Не удалось перевести раздел'}
            </Alert>
          )}
          <Group mt="xs">
            <Button
              size="compact-xs"
              variant="subtle"
              onClick={() => setStyleCheckOn(true)}
              loading={style.isFetching}
            >
              Проверить соответствие стилю
            </Button>
          </Group>
          {style.data && (
            <Alert
              color={style.data.compliant ? 'green' : 'yellow'}
              role="status"
              mt="xs"
              title={
                style.data.compliant
                  ? 'Стилю журнала соответствует'
                  : 'Есть отступления от стиля'
              }
            >
              {style.data.violations.length === 0 ? (
                <Text size="xs">Замечаний нет.</Text>
              ) : (
                <Stack gap={2}>
                  {style.data.violations.map((violation) => (
                    <Text key={`${violation.rule}-${violation.location}`} size="xs">
                      {`${violation.location}: ${violation.rule} — ${violation.suggestion}`}
                    </Text>
                  ))}
                </Stack>
              )}
            </Alert>
          )}
        </Paper>
      )}

      {versions.length >= 2 && (
        <Paper withBorder p="sm">
          <Text size="sm" fw={500} mb={4}>
            Сравнение версий
          </Text>
          <Group align="flex-end" gap="xs" mb="xs">
            <Select
              label="Откуда"
              aria-label="Версия: откуда"
              data={versionOptions}
              value={diffFrom}
              onChange={(value) => setDiffFrom(value ? String(value) : null)}
              w={280}
            />
            <Select
              label="Куда"
              aria-label="Версия: куда"
              data={versionOptions}
              value={diffTo}
              onChange={(value) => setDiffTo(value ? String(value) : null)}
              w={280}
            />
          </Group>
          {diff.data && <SemanticDiffView diff={diff.data} />}
          {diff.isError && (
            <Alert color="red" role="alert">
              {diff.error instanceof Error
                ? diff.error.message
                : 'Не удалось сравнить версии'}
            </Alert>
          )}
        </Paper>
      )}
    </Stack>
  )
}
