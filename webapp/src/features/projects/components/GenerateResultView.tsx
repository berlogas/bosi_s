import { Stack, Text, UnstyledButton } from '@mantine/core'
import React, { useState } from 'react'

import { MarkdownText } from '../../../components/MarkdownText'

interface GenerateResultViewProps {
  result: {
    content_md?: string
    citations_ok: boolean
    warnings?: string[]
    references?: string[]
  }
}

export function GenerateResultView({ result }: GenerateResultViewProps) {
  const [refsOpened, setRefsOpened] = useState(false)

  const refsContent = result.references?.length ? (
    <Stack gap={2}>
      {result.references!.map((line) => (
        <MarkdownText key={line} text={'- ' + line} />
      ))}
    </Stack>
  ) : null

  return (
    <Stack gap={4}>
      <MarkdownText text={result.content_md ?? ''} />
      {!result.citations_ok && (
        <Text size="sm" c="warning">
          Проверьте ссылки: часть из них не разрешается в источники.
        </Text>
      )}
      {(result.warnings ?? []).map((warning) => (
        <Text key={warning} size="xs" c="dimmed">
          ⚠ {warning}
        </Text>
      ))}
      {result.references?.length && (
        <React.Fragment>
          <UnstyledButton
            onClick={() => setRefsOpened((value) => !value)}
            style={{ textAlign: 'left' }}
          >
            <Text size="sm" style={{ textDecoration: 'underline' }}>
              Источники
            </Text>
          </UnstyledButton>
          {refsOpened && refsContent}
        </React.Fragment>
      )}
    </Stack>
  )
}
