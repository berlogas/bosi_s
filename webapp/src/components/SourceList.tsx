/**
 * Источники ответа — паритет `ui.source_list`:
 * 📚 (глобальная база) / 📁 (сессия), категория, score.
 */

import { Stack, Text } from '@mantine/core'

import type { AnswerSource } from '../api/types'
import { categoryLabel } from '../lib/format'

const SCOPE_LABELS = {
  global: 'глобальная база',
  session: 'сессия',
} as const

export function SourceList({ sources }: { sources: AnswerSource[] }) {
  if (sources.length === 0) return null
  return (
    <Stack gap={4}>
      <Text size="xs" c="dimmed">
        Источники:
      </Text>
      {sources.map((source) => {
        const label = source.title || source.docname || source.dockey || 'без названия'
        const scope = SCOPE_LABELS[source.source_scope] ?? 'сессия'
        return (
          <Text size="xs" key={`${source.index}-${source.dockey ?? label}`}>
            {source.marker} <code>[{source.index}]</code> <b>{label}</b> — {scope},{' '}
            {categoryLabel(source.category)}, score{' '}
            {Number(source.score ?? 0).toFixed(2)}
          </Text>
        )
      })}
    </Stack>
  )
}
