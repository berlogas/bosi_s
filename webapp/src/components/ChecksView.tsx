/**
 * Предупреждения о качестве ответа — паритет `ui.checks_view`:
 * выдуманные факты (grounding), сломанные ссылки (citations).
 *
 * Живой ответ несёт их в `stats`, история — в `checks` (одни и те же
 * отчёты citation_guard/grounding, сохранённые в messages.checks).
 */

import { Alert, Collapse, Stack, Text } from '@mantine/core'
import { useState } from 'react'

import type { AnswerChecks } from '../api/types'

export function collectWarnings(payload: {
  stats?: AnswerChecks | null
  checks?: AnswerChecks | null
}): string[] {
  const container = payload.stats ?? payload.checks ?? {}
  const warnings: string[] = []
  for (const key of ['grounding', 'citations'] as const) {
    warnings.push(...(container[key]?.warnings ?? []))
  }
  return warnings
}

export function ChecksView(payload: {
  stats?: AnswerChecks | null
  checks?: AnswerChecks | null
}) {
  const warnings = collectWarnings(payload)
  const [opened, setOpened] = useState(false)
  if (warnings.length === 0) return null

  return (
    <Stack gap={4}>
      <Alert color="yellow">⚠️ {warnings[0]}</Alert>
      {warnings.length > 1 && (
        <>
          <Text
            size="sm"
            style={{ cursor: 'pointer', textDecoration: 'underline' }}
            onClick={() => setOpened((value) => !value)}
            role="button"
          >
            Все предупреждения проверки ({warnings.length})
          </Text>
          <Collapse expanded={opened}>
            <Stack gap={2} mt={4}>
              {warnings.slice(1).map((line) => (
                <Text size="xs" key={line}>
                  • {line}
                </Text>
              ))}
            </Stack>
          </Collapse>
        </>
      )}
    </Stack>
  )
}
