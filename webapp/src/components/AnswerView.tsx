/**
 * Ответ LLM целиком — паритет `ui.answer_view` (Streamlit).
 *
 * Порядок блоков 1-в-1: текст → «Ответ пуст» → base_empty → источники →
 * проверки → кэш → expander «Список источников». Markdown рендерится с
 * санитизацией (текст приходит от модели).
 */

import { Alert, Collapse, Stack, Text } from '@mantine/core'
import { useState } from 'react'

import type { AnswerChecks, AnswerSource } from '../api/types'
import { ChecksView } from './ChecksView'
import { MarkdownText } from './MarkdownText'
import { SourceList } from './SourceList'

interface AnswerViewProps {
  answer: {
    answer?: string | null
    sources?: unknown
    references?: string[] | null
    from_cache?: boolean
    base_empty?: boolean
    stats?: AnswerChecks | null
    checks?: AnswerChecks | null
  }
}

export function AnswerView({ answer }: AnswerViewProps) {
  const [referencesOpened, setReferencesOpened] = useState(false)
  const text = (answer.answer ?? '').trim()
  const sources = (answer.sources ?? []) as AnswerSource[]
  const references = answer.references ?? []

  return (
    <Stack gap="sm">
      {text ? (
        <MarkdownText text={text} />
      ) : !answer.base_empty ? (
        <Text fs="italic" c="dimmed">
          Ответ пуст
        </Text>
      ) : null}

      {answer.base_empty && (
        <Alert color="blue">
          Ответ без ссылок на источники: в базе знаний нет документов или по запросу
          ничего не нашлось. Загрузите документы в разделе «Администрирование».
        </Alert>
      )}

      <SourceList sources={sources} />
      <ChecksView stats={answer.stats} checks={answer.checks} />

      {answer.from_cache && (
        <Text size="xs" c="dimmed">
          Ответ взят из кэша
        </Text>
      )}

      {references.length > 0 && (
        <>
          <Text
            size="sm"
            style={{ cursor: 'pointer', textDecoration: 'underline' }}
            role="button"
            onClick={() => setReferencesOpened((value) => !value)}
          >
            Список источников
          </Text>
          <Collapse expanded={referencesOpened}>
            <Stack gap={2} mt={4}>
              {references.map((line) => (
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
