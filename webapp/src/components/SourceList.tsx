/**
 * Источники ответа — паритет `ui.source_list`:
 * 📚 (глобальная база) / 📁 (сессия), категория, score.
 *
 * `highlight` подсвечивает источник по индексу (клик по цитате `[n]` в
 * ответе) и доскролливает к нему.
 */

import { Stack, Text } from '@mantine/core'
import { useEffect, useRef } from 'react'

import type { AnswerSource } from '../api/types'
import { categoryLabel } from '../lib/format'

const SCOPE_LABELS = {
  global: 'глобальная база',
  session: 'сессия',
} as const

/** Категории, которые просто повторяют область хранения — не показываем. */
const REDUNDANT_CATEGORIES = new Set(['global_knowledge'])

/** «релевантность 87%» из 0..1; без значения — ничего не показываем. */
function relevanceLabel(value: number | undefined): string {
  if (typeof value !== 'number' || Number.isNaN(value)) return ''
  return `релевантность ${Math.round(value * 100)}%`
}

export function SourceList({
  sources,
  highlight = null,
  onHighlight,
}: {
  sources: AnswerSource[]
  /** Индекс подсвеченного источника (клик по цитате) или null. */
  highlight?: number | null
  onHighlight?: (index: number | null) => void
}) {
  const rootRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (highlight === null) return
    const target = rootRef.current?.querySelector(`[data-src="${highlight}"]`)
    if (target instanceof HTMLElement) {
      target.scrollIntoView({ block: 'nearest' })
    }
  }, [highlight])

  if (sources.length === 0) return null

  return (
    <Stack gap={4} ref={rootRef}>
      <Text size="xs" c="dimmed">
        Источники:
      </Text>
      {sources.map((source) => {
        const label = source.title || source.docname || source.dockey || 'без названия'
        const scope = SCOPE_LABELS[source.source_scope] ?? 'сессия'
        const category = REDUNDANT_CATEGORIES.has(source.category ?? '')
          ? null
          : categoryLabel(source.category)
        const relevance = relevanceLabel(source.relevance)
        const active = highlight === source.index
        return (
          <Text
            size="xs"
            key={`${source.index}-${source.dockey ?? label}`}
            data-src={source.index}
            bg={active ? 'yellow.2' : undefined}
            px={active ? 4 : undefined}
            style={{ cursor: onHighlight ? 'pointer' : undefined, borderRadius: 4 }}
            onClick={
              onHighlight ? () => onHighlight(active ? null : source.index) : undefined
            }
          >
            {source.marker} <code>[{source.index}]</code> <b>{label}</b> — {scope}
            {category ? `, ${category}` : ''}
            {relevance ? `, ${relevance}` : ''}
          </Text>
        )
      })}
    </Stack>
  )
}
