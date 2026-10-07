/**
 * Быстрый чат по глобальной базе — паритет `_quick_chat` (dashboard.py).
 *
 * Вопрос уходит в `POST /chat/quick-query` (долгий, LLM), ответ рисуется
 * упрощённым answer_view; при наличии источников подсказываем уточнения
 * через `suggest-queries`. История — в компоненте (Streamlit держал её в
 * session_state; у нас это переживает только жизнь вкладки).
 */

import {
  Alert,
  Avatar,
  Button,
  Card,
  Group,
  Loader,
  Stack,
  Text,
  Textarea,
} from '@mantine/core'
import { useRef, useState } from 'react'

import { client } from '../../api/client'
import { AnswerView } from '../../components/AnswerView'
import type { QuickQueryResponse } from '../../api/types'

interface ChatEntry {
  role: 'user' | 'assistant'
  content: string
  /** ответ LLM; undefined — сообщение ещё без ответа */
  answer?: QuickQueryResponse
  /** текст ошибки вместо ответа */
  error?: string
}

export function QuickChat() {
  const [history, setHistory] = useState<ChatEntry[]>([])
  const [suggestions, setSuggestions] = useState<string[]>([])
  const [prompt, setPrompt] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const bottomRef = useRef<HTMLDivElement>(null)

  async function submit(text: string) {
    const question = text.trim()
    if (!question || busy) return
    setBusy(true)
    setError(null)
    setPrompt('')
    setHistory((items) => [...items, { role: 'user', content: question }])

    try {
      const answer = await client.quickQuery(question)
      setHistory((items) => [
        ...items,
        { role: 'assistant', content: answer.answer ?? '', answer },
      ])

      // Уточняющие вопросы — только под осмысленным ответом, ошибку молча гасим
      // (как в api.py: suggest_queries не должен ломать чат).
      if (!answer.base_empty && answer.sources?.length) {
        try {
          setSuggestions((await client.suggestQueries(question)).slice(0, 4))
        } catch {
          setSuggestions([])
        }
      } else {
        setSuggestions([])
      }
    } catch (cause) {
      const message =
        cause instanceof Error ? cause.message : 'Не удалось получить ответ'
      setError(message)
      setHistory((items) => [
        ...items,
        { role: 'assistant', content: '', error: message },
      ])
      setSuggestions([])
    } finally {
      setBusy(false)
      // подскроллить к свежему сообщению
      requestAnimationFrame(() =>
        bottomRef.current?.scrollIntoView({ behavior: 'smooth' }),
      )
    }
  }

  return (
    <Card withBorder>
      <Stack gap="sm">
        {history.length === 0 && !busy && !error && (
          <Text size="sm" c="dimmed">
            Спросите что-нибудь по базе знаний — ответ появится здесь.
          </Text>
        )}

        {history.map((entry, index) => (
          <Group key={index} align="flex-start" wrap="nowrap" gap="xs">
            <Avatar
              size="sm"
              radius="xl"
              color={entry.role === 'user' ? 'green' : 'blue'}
            >
              {entry.role === 'user' ? '🔬' : '💻'}
            </Avatar>
            <Stack gap={4} style={{ flex: 1 }}>
              <Text size="xs" c="dimmed" fw={600}>
                {entry.role === 'user' ? 'Вы' : 'Бо'}
              </Text>
              {entry.role === 'user' ? (
                <Text size="sm" style={{ whiteSpace: 'pre-wrap' }}>
                  {entry.content}
                </Text>
              ) : entry.error ? (
                <Alert color="red" role="alert">
                  {entry.error}
                </Alert>
              ) : (
                <AnswerView answer={entry.answer ?? { answer: entry.content }} />
              )}
            </Stack>
          </Group>
        ))}

        {busy && (
          <Group gap="xs">
            <Loader size="xs" />
            <Text size="sm" c="dimmed">
              Ищу в глобальной базе…
            </Text>
          </Group>
        )}

        {suggestions.length > 0 && (
          <Stack gap={2}>
            <Text size="xs" c="dimmed">
              Можно уточнить:
            </Text>
            {suggestions.map((text) => (
              <Text
                size="xs"
                key={text}
                style={{ cursor: 'pointer', textDecoration: 'underline' }}
                role="button"
                onClick={() => void submit(text)}
              >
                — {text}
              </Text>
            ))}
          </Stack>
        )}

        <div ref={bottomRef} />

        <form
          onSubmit={(event) => {
            event.preventDefault()
            void submit(prompt)
          }}
        >
          <Group align="flex-end" wrap="nowrap" gap="xs">
            <Textarea
              placeholder="Спросите что-нибудь по базе знаний"
              value={prompt}
              onChange={(event) => setPrompt(event.currentTarget.value)}
              onKeyDown={(event) => {
                // Паритет st.chat_input: Enter отправляет, Shift+Enter — новая строка
                if (event.key === 'Enter' && !event.shiftKey) {
                  event.preventDefault()
                  if (prompt.trim() && !busy) void submit(prompt)
                }
              }}
              autosize
              minRows={1}
              maxRows={6}
              disabled={busy}
              style={{ flex: 1 }}
              label="Быстрый вопрос"
              aria-label="Быстрый вопрос"
            />
            <Button type="submit" loading={busy} disabled={!prompt.trim()}>
              Спросить
            </Button>
          </Group>
        </form>
      </Stack>
    </Card>
  )
}
