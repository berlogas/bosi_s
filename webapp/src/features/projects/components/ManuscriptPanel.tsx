/**
 * Сборка статьи целиком: манускрипт из одобренных версий разделов.
 *
 * Отдельный раздел статьи пишется по одному, а читать его приходится
 * целиком — здесь показываем собранный текст, объём, список литературы
 * и предупреждения (раздел без текста, не одобренная версия).
 */

import { useState } from 'react'
import { Alert, Badge, Button, Group, Paper, Stack, Text } from '@mantine/core'
import { IconRefresh } from '@tabler/icons-react'

import { useCompileManuscript } from '../hooks'
import { MarkdownText } from '../../../components/MarkdownText'

export function ManuscriptPanel({
  sessionId,
  projectId,
  language,
}: {
  sessionId: string
  projectId: string
  language?: string
}) {
  const [includeUnapproved, setIncludeUnapproved] = useState(false)
  const [enabled, setEnabled] = useState(false)
  const { data, isFetching, error } = useCompileManuscript(
    sessionId,
    projectId,
    language,
    includeUnapproved,
    enabled,
  )

  return (
    <Stack gap="sm">
      {/* Заголовок панели совпадает с заголовком аккордеона, поэтому здесь
          только действие — без повторного названия. */}
      <Group justify="flex-end">
        <Button
          size="xs"
          variant="light"
          leftSection={<IconRefresh size={14} />}
          onClick={() => setEnabled(true)}
          loading={isFetching}
        >
          {data ? 'Пересобрать' : 'Собрать статью'}
        </Button>
      </Group>

      {error && (
        <Alert color="red" role="alert">
          {error instanceof Error ? error.message : 'Не удалось собрать статью'}
        </Alert>
      )}

      {data && (
        <>
          <Group gap="xs">
            <Badge size="sm" variant="light">
              разделов: {data.stats.sections_count}
            </Badge>
            <Badge size="sm" variant="light">
              слов: {data.stats.total_words}
            </Badge>
            <Badge size="sm" variant="light">
              источников: {data.stats.sources_count}
            </Badge>
            <Badge size="sm" variant="light">
              язык: {data.stats.language}
            </Badge>
          </Group>

          {data.warnings.length > 0 && (
            <Alert color="yellow" title="Замечания" role="status">
              <Stack gap={2}>
                {data.warnings.map((warning) => (
                  <Text key={warning} size="xs">
                    {warning}
                  </Text>
                ))}
              </Stack>
            </Alert>
          )}

          {data.sections.length === 0 ? (
            <Text size="sm" c="dimmed">
              Собирать нечего: нет одобренных версий разделов.
            </Text>
          ) : (
            <Paper withBorder p="sm">
              <MarkdownText text={data.full_text} />
            </Paper>
          )}

          {data.bibliography.length > 0 && (
            <Paper withBorder p="sm">
              <Text fw={500} size="sm" mb={4}>
                Список литературы
              </Text>
              <Stack gap={2}>
                {data.bibliography.map((entry) => (
                  <Text key={entry.index} size="xs">
                    {`[${entry.index}] ${entry.title ?? entry.dockey ?? entry.citation ?? ''}`}
                  </Text>
                ))}
              </Stack>
            </Paper>
          )}

          <Text size="xs" c="dimmed">
            Собраны одобренные версии разделов. Неодобренные можно включить кнопкой
            обновления — она пересобирает с include_unapproved.
          </Text>
          <Button
            size="compact-xs"
            variant="subtle"
            onClick={() => setIncludeUnapproved((value) => !value)}
          >
            {includeUnapproved
              ? 'Собрать только одобренные'
              : 'Включить неодобренные разделы'}
          </Button>
        </>
      )}
    </Stack>
  )
}
