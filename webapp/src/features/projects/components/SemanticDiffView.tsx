/**
 * Компонент для отображения семантического diff'а между версиями.
 */

import { useState } from 'react'
import { Stack, Text, Box, Badge, Group, Tabs, TabsList, TabsTab, TabsPanel } from '@mantine/core'
import { IconPlus, IconMinus, IconEdit, IconArrowRight, IconQuote } from '@tabler/icons-react'

import type { SemanticDiff } from '../../../api/types'

function ClaimItem({ claim, type }: { claim: { index: number; text: string; citations: number[] }; type: 'added' | 'removed' | 'modified' }) {
  const colors = {
    added: { bg: 'green', border: 'green', icon: IconPlus, label: 'Добавлено' },
    removed: { bg: 'red', border: 'red', icon: IconMinus, label: 'Удалено' },
    modified: { bg: 'blue', border: 'blue', icon: IconEdit, label: 'Изменено' },
  }

  const config = colors[type]

  return (
    <Box
      style={{
        borderLeft: `3px solid var(--mantine-color-${config.border}-6)`,
        backgroundColor: `var(--mantine-color-${config.bg}-light)`,
        borderRadius: 4,
        padding: '8px 12px',
        marginBottom: 8,
      }}
    >
      <Group gap="xs" style={{ marginBottom: 4 }}>
        <config.icon size={14} color={config.border} />
        <Badge variant="light" color={config.border} size="xs">
          {config.label}
        </Badge>
        <Text size="xs" c="dimmed">
          Утверждение #{claim.index}
        </Text>
      </Group>
      <Text size="sm" style={{ fontFamily: 'monospace', whiteSpace: 'pre-wrap' }}>
        {claim.text}
      </Text>
      {claim.citations.length > 0 && (
        <Group gap="xs" style={{ marginTop: 4 }}>
          <Text size="xs" c="dimmed">Цитаты:</Text>
          {claim.citations.map((c) => (
            <Badge key={c} variant="light" color="gray" size="xs">
              [{c}]
            </Badge>
          ))}
        </Group>
      )}
    </Box>
  )
}

function ModifiedClaimItem({ claim }: { claim: { from: { index: number; text: string; citations: number[] }; to: { index: number; text: string; citations: number[] }; type: string } }) {
  return (
    <Box
      style={{
        borderLeft: '3px solid var(--mantine-color-blue-6)',
        backgroundColor: 'var(--mantine-color-blue-light)',
        borderRadius: 4,
        padding: '8px 12px',
        marginBottom: 8,
      }}
    >
      <Group gap="xs" style={{ marginBottom: 4 }}>
        <IconEdit size={14} color="blue" />
        <Badge variant="light" color="blue" size="xs">
          Изменено
        </Badge>
        <Text size="xs" c="dimmed">
          Утверждение #{claim.from.index} → #{claim.to.index}
        </Text>
      </Group>
      <Stack gap={4}>
        <Box style={{ backgroundColor: 'var(--mantine-color-red-light)', borderRadius: 4, padding: '4px 8px' }}>
          <Group gap="xs" style={{ marginBottom: 2 }}>
            <IconMinus size={12} color="red" />
            <Text size="xs" c="red" fw={500}>Было:</Text>
          </Group>
          <Text size="sm" style={{ fontFamily: 'monospace', whiteSpace: 'pre-wrap', color: 'var(--mantine-color-red-9)' }}>
            {claim.from.text}
          </Text>
          {claim.from.citations.length > 0 && (
            <Group gap="xs" style={{ marginTop: 4, marginLeft: 8 }}>
              <Text size="xs" c="dimmed">Цитаты:</Text>
              {claim.from.citations.map((c) => (
                <Badge key={c} variant="light" color="red" size="xs">[{c}]</Badge>
              ))}
            </Group>
          )}
        </Box>
        <Box style={{ backgroundColor: 'var(--mantine-color-green-light)', borderRadius: 4, padding: '4px 8px' }}>
          <Group gap="xs" style={{ marginBottom: 2 }}>
            <IconPlus size={12} color="green" />
            <Text size="xs" c="green" fw={500}>Стало:</Text>
          </Group>
          <Text size="sm" style={{ fontFamily: 'monospace', whiteSpace: 'pre-wrap', color: 'var(--mantine-color-green-9)' }}>
            {claim.to.text}
          </Text>
          {claim.to.citations.length > 0 && (
            <Group gap="xs" style={{ marginTop: 4, marginLeft: 8 }}>
              <Text size="xs" c="dimmed">Цитаты:</Text>
              {claim.to.citations.map((c) => (
                <Badge key={c} variant="light" color="green" size="xs">[{c}]</Badge>
              ))}
            </Group>
          )}
        </Box>
      </Stack>
    </Box>
  )
}

function CitationChangesView({ added, removed }: { added: number[]; removed: number[] }) {
  if (added.length === 0 && removed.length === 0) return null

  return (
    <Box style={{ backgroundColor: 'var(--mantine-color-yellow-light)', borderRadius: 4, padding: '12px' }}>
      <Text size="sm" fw={600} style={{ marginBottom: 8 }}>Изменения в цитатах</Text>
      <Stack gap={4}>
        {added.length > 0 && (
          <Group gap="xs">
            <IconPlus size={14} color="green" />
            <Text size="sm" c="green" fw={500}>Добавлены:</Text>
            {added.map((c) => (
              <Badge key={c} variant="filled" color="green" size="xs">[{c}]</Badge>
            ))}
          </Group>
        )}
        {removed.length > 0 && (
          <Group gap="xs">
            <IconMinus size={14} color="red" />
            <Text size="sm" c="red" fw={500}>Удалены:</Text>
            {removed.map((c) => (
              <Badge key={c} variant="filled" color="red" size="xs">[{c}]</Badge>
            ))}
          </Group>
        )}
      </Stack>
    </Box>
  )
}

function TerminologyChangesView({ changes }: { changes: Record<string, string> }) {
  if (Object.keys(changes).length === 0) return null

  return (
    <Box style={{ backgroundColor: 'var(--mantine-color-violet-light)', borderRadius: 4, padding: '12px' }}>
      <Text size="sm" fw={600} style={{ marginBottom: 8 }}>Изменения терминологии</Text>
      <Stack gap={4}>
        {Object.entries(changes).map(([term, translation]) => (
          <Group key={term} gap="xs">
            <IconQuote size={14} color="violet" />
            <Text size="sm" fw={500}>{term}</Text>
            <IconArrowRight size={14} color="dimmed" />
            <Text size="sm" c="violet">{translation}</Text>
            <IconQuote size={14} color="violet" />
          </Group>
        ))}
      </Stack>
    </Box>
  )
}

export function SemanticDiffView({ diff }: { diff: SemanticDiff }) {
  const [activeTab, setActiveTab] = useState('claims')
  return (
    <Box p="md">
      <Stack gap="md">
        <Group justify="space-between" align="center">
          <Text fw={600}>Семантический Diff</Text>
          <Badge variant="light" color="blue">{diff.summary}</Badge>
        </Group>

        <Tabs value={activeTab} onChange={setActiveTab}>
          <TabsList>
            <TabsTab value="claims">Утверждения ({diff.added_claims.length + diff.removed_claims.length + diff.modified_claims.length})</TabsTab>
            <TabsTab value="citations">Цитаты ({diff.citation_changes.added.length + diff.citation_changes.removed.length})</TabsTab>
            <TabsTab value="terminology">Терминология ({Object.keys(diff.terminology_changes).length})</TabsTab>
          </TabsList>

          <TabsPanel value="claims">
            <Stack gap="md">
              {diff.added_claims.length > 0 && (
                <Stack gap={4} style={{ marginTop: 8 }}>
                  <Text size="sm" fw={600} c="green">Добавленные утверждения ({diff.added_claims.length})</Text>
                  {diff.added_claims.map((claim) => (
                    <ClaimItem key={`added-${claim.index}`} claim={claim} type="added" />
                  ))}
                </Stack>
              )}
              {diff.removed_claims.length > 0 && (
                <Stack gap={4} style={{ marginTop: 8 }}>
                  <Text size="sm" fw={600} c="red">Удаленные утверждения ({diff.removed_claims.length})</Text>
                  {diff.removed_claims.map((claim) => (
                    <ClaimItem key={`removed-${claim.index}`} claim={claim} type="removed" />
                  ))}
                </Stack>
              )}
              {diff.modified_claims.length > 0 && (
                <Stack gap={4} style={{ marginTop: 8 }}>
                  <Text size="sm" fw={600} c="blue">Измененные утверждения ({diff.modified_claims.length})</Text>
                  {diff.modified_claims.map((claim, i) => (
                    <ModifiedClaimItem key={`modified-${i}`} claim={claim} />
                  ))}
                </Stack>
              )}
              {diff.added_claims.length === 0 && diff.removed_claims.length === 0 && diff.modified_claims.length === 0 && (
                <Text size="sm" c="dimmed" ta="center" style={{ paddingTop: 32, paddingBottom: 32 }}>
                  Изменений в утверждениях не обнаружено
                </Text>
              )}
            </Stack>
          </TabsPanel>

          <TabsPanel value="citations">
            {diff.citation_changes.added.length === 0 && diff.citation_changes.removed.length === 0 ? (
              <Text size="sm" c="dimmed" ta="center" style={{ paddingTop: 32, paddingBottom: 32 }}>
                Изменений в цитатах не обнаружено
              </Text>
            ) : (
              <CitationChangesView
                added={diff.citation_changes.added}
                removed={diff.citation_changes.removed}
              />
            )}
          </TabsPanel>

          <TabsPanel value="terminology">
            {Object.keys(diff.terminology_changes).length > 0 ? (
              <TerminologyChangesView changes={diff.terminology_changes} />
            ) : (
              <Text size="sm" c="dimmed" ta="center" style={{ paddingTop: 32, paddingBottom: 32 }}>
                Изменений в терминологии не обнаружено
              </Text>
            )}
          </TabsPanel>
        </Tabs>
      </Stack>
    </Box>
  )
}