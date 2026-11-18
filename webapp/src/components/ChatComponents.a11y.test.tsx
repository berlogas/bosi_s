/**
 * A11y-тесты чата (Волна 6, п.1).
 *
 * Проверяем отсутствие нарушений доступности (axe-core) для:
 *  - ChatTab (основной компонент чата)
 *  - ChatBubble (пузырь сообщения)
 *  - AnswerView (отображение ответа с источниками)
 */

import React from 'react'
import { render } from '@testing-library/react'
import { axe } from 'vitest-axe'
import { describe, expect, it } from 'vitest'
import { MantineProvider } from '@mantine/core'

import { ChatBubble } from '../features/chat/ChatBubble'
import { AnswerView } from '../components/AnswerView'

const renderWithProviders = (ui: React.ReactNode) =>
  render(<MantineProvider>{ui}</MantineProvider>)

describe('ChatBubble a11y', () => {
  it('user bubble is accessible', async () => {
    const { container } = renderWithProviders(
      <ChatBubble role="user">
        <p>Привет, как дела?</p>
      </ChatBubble>,
    )
    const result = await axe(container)
    expect(result.violations).toHaveLength(0)
  })

  it('assistant bubble is accessible', async () => {
    const { container } = renderWithProviders(
      <ChatBubble role="assistant">
        <p>Здравствуйте! Чем могу помочь?</p>
      </ChatBubble>,
    )
    const result = await axe(container)
    expect(result.violations).toHaveLength(0)
  })
})

describe('AnswerView a11y', () => {
  it('answer view with sources is accessible', async () => {
    const { container } = renderWithProviders(
      <AnswerView
        answer={{
          answer: 'Это ответ на вопрос.',
          sources: [
            {
              docname: 'док.txt',
              dockey: 'abc123',
              text: 'Текст источника',
              citation: 'abc123',
              score: 95,
              name: 'док.txt',
              context: 'Контекст источника',
            },
          ],
          references: ['(pqac-abc123)'],
        }}
      />,
    )
    const result = await axe(container)
    expect(result.violations).toHaveLength(0)
  })
})
