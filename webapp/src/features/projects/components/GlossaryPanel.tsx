/**
 * Глоссарий терминов проекта.
 *
 * Термины и их переводы попадают в промпт генерации: модель пишет
 * «биомасса» одинаково во всех разделах и переводит её одинаково.
 */

import { useState } from 'react'
import {
  Alert,
  Badge,
  Button,
  Group,
  Paper,
  Stack,
  Table,
  Text,
  TextInput,
  Textarea,
} from '@mantine/core'
import { IconPlus, IconTrash } from '@tabler/icons-react'

import {
  useGlossary,
  useAddGlossaryEntry,
  useDeleteGlossaryEntry,
  useTerminologyCheck,
} from '../hooks'

export function GlossaryPanel({
  sessionId,
  projectId,
}: {
  sessionId: string
  projectId: string
}) {
  const { data: entries, isLoading } = useGlossary(sessionId, projectId)
  const addEntry = useAddGlossaryEntry(sessionId, projectId)
  const deleteEntry = useDeleteGlossaryEntry(sessionId, projectId)
  const [checkOn, setCheckOn] = useState(false)
  const terminology = useTerminologyCheck(
    checkOn ? sessionId : null,
    checkOn ? projectId : null,
  )

  const [term, setTerm] = useState('')
  const [definition, setDefinition] = useState('')
  const [translations, setTranslations] = useState('')

  const handleAdd = () => {
    const clean = term.trim()
    if (!clean) return
    const map: Record<string, string> = {}
    for (const pair of translations.split(',')) {
      const [lang, value] = pair.split(':').map((part) => part.trim())
      if (lang && value) map[lang] = value
    }
    addEntry.mutate(
      {
        term: clean,
        translations: Object.keys(map).length ? map : undefined,
        definition: definition.trim() || undefined,
      },
      {
        onSuccess: () => {
          setTerm('')
          setDefinition('')
          setTranslations('')
        },
      },
    )
  }

  return (
    <Stack gap="sm">
      <Text size="sm" c="dimmed">
        Термины проекта: генератор придерживается указанных переводов и определений во
        всех разделах.
      </Text>

      {addEntry.isError && (
        <Alert color="red" role="alert">
          {addEntry.error instanceof Error
            ? addEntry.error.message
            : 'Не удалось добавить термин'}
        </Alert>
      )}

      {isLoading ? (
        <Text size="sm" c="dimmed">
          Загрузка глоссария…
        </Text>
      ) : (entries ?? []).length === 0 ? (
        <Text size="sm" c="dimmed">
          Терминов пока нет — добавьте те, которые должны звучать одинаково.
        </Text>
      ) : (
        <Table highlightOnHover>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Термин</Table.Th>
              <Table.Th>Переводы</Table.Th>
              <Table.Th>Определение</Table.Th>
              <Table.Th style={{ width: 60 }} />
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {(entries ?? []).map((entry) => (
              <Table.Tr key={entry.id}>
                <Table.Td>
                  <Text size="sm" fw={500}>
                    {entry.term}
                  </Text>
                </Table.Td>
                <Table.Td>
                  <Group gap={4}>
                    {Object.entries(entry.translations ?? {}).map(([lang, value]) => (
                      <Badge key={lang} size="xs" variant="light">
                        {`${lang}: ${value}`}
                      </Badge>
                    ))}
                  </Group>
                </Table.Td>
                <Table.Td>
                  <Text size="xs" c="dimmed">
                    {entry.definition ?? '—'}
                  </Text>
                </Table.Td>
                <Table.Td>
                  <Button
                    size="compact-xs"
                    variant="subtle"
                    color="red"
                    leftSection={<IconTrash size={12} />}
                    onClick={() => deleteEntry.mutate(entry.id)}
                    aria-label={`Удалить термин ${entry.term}`}
                  >
                    Удалить
                  </Button>
                </Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      )}

      <Group justify="space-between">
        <Button
          size="xs"
          variant="light"
          onClick={() => setCheckOn(true)}
          loading={terminology.isFetching}
        >
          Проверить терминологию в разделах
        </Button>
      </Group>

      {terminology.data && (
        <Alert
          color={terminology.data.consistent ? 'green' : 'yellow'}
          role="status"
          title={
            terminology.data.consistent ? 'Термины согласованы' : 'Термины расходятся'
          }
        >
          {terminology.data.section_terminology.length === 0 ? (
            <Text size="xs">Расхождений не найдено.</Text>
          ) : (
            <Stack gap={2}>
              {terminology.data.section_terminology.map((item) => (
                <Text key={`${item.section}-${item.term}`} size="xs">
                  {`${item.section}: «${item.term}» вместо «${item.expected}»`}
                </Text>
              ))}
            </Stack>
          )}
        </Alert>
      )}

      <Paper withBorder p="xs">
        <Stack gap="xs">
          <Text size="sm" fw={500}>
            Добавить термин
          </Text>{' '}
          <Group align="flex-end" gap="xs">
            <TextInput
              label="Термин"
              value={term}
              onChange={(event) => setTerm(event.currentTarget.value)}
              style={{ flex: 1 }}
            />
            <TextInput
              label="Переводы"
              placeholder="en: biomass, de: Biomasse"
              value={translations}
              onChange={(event) => setTranslations(event.currentTarget.value)}
              style={{ flex: 1 }}
            />
          </Group>
          <Textarea
            label="Определение"
            value={definition}
            onChange={(event) => setDefinition(event.currentTarget.value)}
            autosize
            minRows={1}
          />
          <Group justify="flex-end">
            <Button
              size="xs"
              leftSection={<IconPlus size={14} />}
              onClick={handleAdd}
              disabled={!term.trim()}
              loading={addEntry.isPending}
            >
              Добавить
            </Button>
          </Group>
        </Stack>
      </Paper>
    </Stack>
  )
}
