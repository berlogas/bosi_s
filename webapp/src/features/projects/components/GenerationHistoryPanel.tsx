import { Stack, Text, Badge, Table, Button, Group, Paper } from '@mantine/core'
import React, { useState } from 'react'
import { useProjectSectionVersions, useSectionPlans } from '../hooks'
import { MarkdownText } from '../../../components/MarkdownText'

interface GenerationHistoryPanelProps {
  sessionId: string
  projectId: string
}

const STATUS_COLORS: Record<string, string> = {
  draft: 'blue',
  review: 'yellow',
  approved: 'green',
  superseded: 'gray',
  archived: 'dark',
}

const STATUS_LABELS: Record<string, string> = {
  draft: 'Черновик',
  review: 'На ревью',
  approved: 'Одобрен',
  superseded: 'Заменён',
  archived: 'В архиве',
}

/**
 * История генераций раздела — по настоящим версиям из БД.
 *
 * Раньше здесь были моковые данные («демо-данные»), из-за чего панель
 * показывала несуществующие генерации.
 */
export function GenerationHistoryPanel({
  sessionId,
  projectId,
}: GenerationHistoryPanelProps) {
  const { data: versions, isLoading } = useProjectSectionVersions(sessionId, projectId)
  const { data: plans } = useSectionPlans(sessionId, projectId)
  const [openVersionId, setOpenVersionId] = useState<string | null>(null)

  const planName = (planId: string): string =>
    (plans ?? []).find((plan) => plan.id === planId)?.name ?? '—'

  const history = versions ?? []
  const open = history.find((version) => version.id === openVersionId) ?? null

  return (
    <Stack gap="xs">
      <Text size="sm" c="dimmed">
        История генераций проекта — по версиям, сохранённым в базе.
      </Text>
      {isLoading ? (
        <Text size="sm" c="dimmed">
          Загрузка истории…
        </Text>
      ) : (
        <div style={{ overflowX: 'auto' }}>
          <Table>
            <thead>
              <tr>
                <th style={{ width: 140 }}>Дата</th>
                <th style={{ width: 140 }}>Раздел</th>
                <th style={{ width: 120 }}>Статус</th>
                <th style={{ width: 80 }}>Токены</th>
                <th style={{ width: 80 }}>Время</th>
                <th>Действия</th>
              </tr>
            </thead>
            <tbody>
              {history.map((version) => (
                <tr key={version.id}>
                  <td style={{ fontSize: 'xs', color: 'dimmed' }}>
                    {new Date(version.created_at).toLocaleString('ru-RU')}
                  </td>
                  <td style={{ fontSize: 'xs' }}>
                    {planName(version.section_plan_id)}
                  </td>
                  <td style={{ fontSize: 'xs' }}>
                    <Badge
                      variant="light"
                      size="xs"
                      color={STATUS_COLORS[version.status] || 'gray'}
                    >
                      {STATUS_LABELS[version.status] || version.status}
                    </Badge>
                  </td>
                  <td style={{ fontSize: 'xs', fontFamily: 'monospace' }}>
                    {(
                      (version.token_counts?.prompt_tokens ?? 0) +
                      (version.token_counts?.completion_tokens ?? 0)
                    ).toLocaleString()}
                  </td>
                  <td style={{ fontSize: 'xs' }}>{version.seconds ?? 0}с</td>
                  <td>
                    <Group gap="xs">
                      <Button
                        variant="subtle"
                        size="xs"
                        onClick={() =>
                          setOpenVersionId(
                            openVersionId === version.id ? null : version.id,
                          )
                        }
                      >
                        {openVersionId === version.id ? 'Скрыть' : 'Результат'}
                      </Button>
                    </Group>
                  </td>
                </tr>
              ))}
            </tbody>
          </Table>
        </div>
      )}
      {history.length === 0 && !isLoading && (
        <Text size="sm" c="dimmed" ta="center" py="md">
          История генераций пуста
        </Text>
      )}
      {open && (
        <Paper withBorder p="sm">
          <Text size="sm" fw={500} mb={4}>
            {planName(open.section_plan_id)} ·{' '}
            {new Date(open.created_at).toLocaleString('ru-RU')}
          </Text>
          <MarkdownText text={open.content_md ?? ''} />
        </Paper>
      )}
    </Stack>
  )
}
