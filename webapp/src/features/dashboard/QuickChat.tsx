/**
 * Быстрый чат по глобальной базе — паритет `_quick_chat` (dashboard.py).
 *
 * Вопрос уходит в `POST /chat/quick-query` и возвращает `task_id`: считает
 * LLM в фоне, UI опрашивает `/api/tasks/{id}` и рисует `TaskPanel` с
 * этапами, секундомером и отменой — тот же путь, что у вопроса по сессии.
 * Маршрут был синхронным, и на CPU-инференсе (минуты на ответ) это
 * выглядело как зависший спиннер: ни прогресса, ни отмены.
 *
 * Переписка берётся с сервера (`/chat/quick-history`): ответ задачи сам
 * дописывается в историю, поэтому F7 или закрытие вкладки её не стирают.
 * Живой обмен (`live`) рисуется поверх истории, пока не приедет обновление.
 */

import {
  Alert,
  Avatar,
  Button,
  Card,
  Group,
  Loader,
  Modal,
  Stack,
  Text,
  Textarea,
} from '@mantine/core'
import { useQueryClient } from '@tanstack/react-query'
import { useEffect, useMemo, useRef, useState } from 'react'
import type { Ref } from 'react'

import { client } from '../../api/client'
import { AnswerView } from '../../components/AnswerView'
import { TaskPanel } from '../../components/TaskPanel'
import type { AnswerSource, MessageOut, QuickQueryResult } from '../../api/types'
import { useTask } from '../chat/queries'
import { queryKeys, useClearQuickHistory, useQuickHistory } from './queries'

/** Ровно то, что умеет рисовать AnswerView. */
type RenderableAnswer = {
  answer: string
  sources?: AnswerSource[]
  references?: string[]
  from_cache?: boolean
  base_empty?: boolean
  checks?: Record<string, unknown>
}

interface ChatEntry {
  /** id сообщения из истории — ключ React; у живого обмена ключ отрицательный */
  key: string
  role: 'user' | 'assistant'
  content: string
  /** ответ LLM; undefined — сообщение ещё без ответа */
  answer?: RenderableAnswer
  /** текст ошибки вместо ответа */
  error?: string
}

/** Обмен, который сейчас в полёте: ответ приедет из фоновой задачи. */
interface Live {
  question: string
  answer?: QuickQueryResult
  error?: string
}

/** История с сервера → пузыри: у сообщения есть текст, источники и проверки. */
function toEntry(message: MessageOut): ChatEntry {
  if (message.role === 'user') {
    return { key: message.id, role: 'user', content: message.content }
  }
  return {
    key: message.id,
    role: 'assistant',
    content: message.content,
    answer: {
      answer: message.content,
      sources: (message.sources ?? []) as AnswerSource[],
      checks: message.checks,
    },
  }
}

function Bubble({
  entry,
  ref,
}: {
  entry: {
    role: 'user' | 'assistant'
    content: string
    answer?: RenderableAnswer
    error?: string
  }
  /** DOM-узел пузыря — якорь автоскролла к свежему ответу. */
  ref?: Ref<HTMLDivElement>
}) {
  const user = entry.role === 'user'
  return (
    <Group ref={ref} align="flex-start" wrap="nowrap" gap="xs">
      <Avatar size="sm" radius="xl" color={user ? 'green' : 'blue'}>
        {user ? '🔬' : '💻'}
      </Avatar>
      <Stack gap={4} style={{ flex: 1 }}>
        <Text size="xs" c="dimmed" fw={600}>
          {user ? 'Вы' : 'Бо'}
        </Text>
        {user ? (
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
  )
}

export function QuickChat() {
  const queryClient = useQueryClient()
  const past = useQuickHistory()
  const clearQuick = useClearQuickHistory()
  const [live, setLive] = useState<Live | null>(null)
  const [taskId, setTaskId] = useState<string | null>(null)
  const [suggestions, setSuggestions] = useState<string[]>([])
  const [prompt, setPrompt] = useState('')
  const [sending, setSending] = useState(false)
  const bottomRef = useRef<HTMLDivElement>(null)
  const answerRef = useRef<HTMLDivElement>(null)
  const [pinAnswer, setPinAnswer] = useState(false)
  const [clearAsk, setClearAsk] = useState(false)
  const [clearError, setClearError] = useState<string | null>(null)

  const task = useTask(taskId)
  const busy = sending || Boolean(taskId)

  const history = useMemo(() => (past.data?.messages ?? []).map(toEntry), [past.data])
  const lastAssistantIndex = useMemo(() => {
    for (let i = history.length - 1; i >= 0; i -= 1) {
      if (history[i].role === 'assistant') return i
    }
    return -1
  }, [history])

  async function submit(text: string) {
    const question = text.trim()
    if (!question || busy) return
    setPinAnswer(false)
    setSending(true)
    setPrompt('')
    setSuggestions([])
    setLive({ question })

    try {
      const { task_id } = await client.quickQuery(question)
      setTaskId(task_id)
    } catch (cause) {
      // отправка не дошла до сервера — вопрос можно повторить сразу
      setLive({
        question,
        error: cause instanceof Error ? cause.message : 'Не удалось отправить вопрос',
      })
    } finally {
      setSending(false)
    }
  }

  // ---------------------------------------------- жизнь фоновой задачи
  const status = task.data?.status
  useEffect(() => {
    if (!taskId || !status) return
    if (status === 'done') {
      const result = task.data?.result as QuickQueryResult | undefined
      setTaskId(null)
      setLive((cur) => (cur ? { ...cur, answer: result } : cur))
      // задача дописала обмен в историю — поднимаем её с сервера
      void queryClient.invalidateQueries({
        queryKey: queryKeys.quickHistory,
      })

      // Уточняющие вопросы — только под осмысленным ответом, ошибку молча гасим
      // (как в api.py: suggest_queries не должен ломать чат).
      if (result && !result.base_empty && result.sources?.length) {
        void client
          .suggestQueries(result.query)
          .then((items) => setSuggestions(items.slice(0, 4)))
          .catch(() => setSuggestions([]))
      }
    } else if (status === 'error' || status === 'cancelled') {
      // при падении задачи вопрос нельзя просто убрать: иначе только тишина
      const text =
        status === 'cancelled'
          ? 'Вопрос отменён'
          : (task.data?.error ?? 'Задача завершилась с ошибкой')
      setTaskId(null)
      setLive((cur) => (cur ? { ...cur, error: text } : cur))
    }
    // live обновляем через функцию: в зависимостях важен только переход статуса
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [status, taskId])

  // задача могла умереть на сервере (ретеншн) — ждать её вечно нельзя
  useEffect(() => {
    if (!task.isError || !taskId) return
    setTaskId(null)
    setLive((cur) =>
      cur ? { ...cur, error: 'Задача пропала на сервере — спросите заново' } : cur,
    )
  }, [task.isError, taskId])

  // «хвост» живого обмена: как только история его содержит, она — источник истины
  useEffect(() => {
    if (!live?.answer || past.isFetching) return
    if (history.some((entry) => entry.content === live.question)) setLive(null)
  }, [history, live, past.isFetching])

  // Ответ приходит длинным: доскроллить до «низа» — показать только хвост
  // у поля ввода, а начало спрятать. Поэтому свежий ответ «закрепляется»:
  // скроллим к его верху и держим позицию, пока не задан новый вопрос.
  useEffect(() => {
    if (live?.answer && !live.error && !pinAnswer) {
      setPinAnswer(true)
      return
    }
    requestAnimationFrame(() => {
      if (pinAnswer) {
        answerRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })
      } else {
        bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
      }
    })
  }, [history.length, live, status, suggestions, pinAnswer])

  function handleClearConfirm() {
    setClearError(null)
    clearQuick.mutate(undefined, {
      onSuccess: () => {
        setClearAsk(false)
        setLive(null)
        setSuggestions([])
        setPinAnswer(false)
      },
      onError: (cause) =>
        setClearError(
          cause instanceof Error ? cause.message : 'Не удалось очистить чат',
        ),
    })
  }

  return (
    <Card withBorder>
      <Stack gap="sm">
        <Group justify="space-between">
          <Text fw={600}>Быстрый чат</Text>
          {(history.length > 0 || live) && (
            <Button
              size="xs"
              variant="subtle"
              color="red"
              leftSection="🗑"
              onClick={() => setClearAsk(true)}
            >
              Очистить чат
            </Button>
          )}
        </Group>

        {past.isError && (
          <Alert color="yellow" role="alert">
            История быстрых вопросов не загрузилась:{' '}
            {past.error instanceof Error ? past.error.message : 'ошибка запроса'}
          </Alert>
        )}

        {history.length === 0 && !busy && !past.isError && (
          <Text size="sm" c="dimmed">
            Спросите что-нибудь по базе знаний — ответ появится здесь.
          </Text>
        )}

        {history.map((entry, index) => (
          <Bubble
            key={entry.key}
            ref={
              pinAnswer && index === lastAssistantIndex && entry.role === 'assistant'
                ? answerRef
                : undefined
            }
            entry={entry}
          />
        ))}

        {/* обмен в полёте: пока ответа нет, в истории его тоже нет */}
        {live && (
          <>
            <Bubble entry={{ role: 'user', content: live.question }} />
            {taskId && task.data && (
              <TaskPanel
                task={task.data}
                onCancel={(t) => {
                  void client.cancelTask(t.id).catch(() => {})
                }}
              />
            )}
            {sending && (
              <Group gap="xs">
                <Loader size="xs" />
                <Text size="sm" c="dimmed">
                  Отправляю вопрос…
                </Text>
              </Group>
            )}
            {live.error && (
              <Bubble entry={{ role: 'assistant', content: '', error: live.error }} />
            )}
            {live.answer && !live.error && (
              <Bubble
                ref={answerRef}
                entry={{ role: 'assistant', content: '', answer: live.answer }}
              />
            )}
          </>
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
            <Button type="submit" loading={sending} disabled={!prompt.trim()}>
              Спросить
            </Button>
          </Group>
        </form>

        <Modal
          opened={clearAsk}
          onClose={() => setClearAsk(false)}
          title="Очистить переписку?"
          centered
        >
          <Stack>
            <Text size="sm">
              Удалить всю историю быстрых вопросов? Отменить будет нельзя.
            </Text>
            {clearError && (
              <Alert color="red" role="alert">
                {clearError}
              </Alert>
            )}
            <Group justify="flex-end">
              <Button variant="default" onClick={() => setClearAsk(false)}>
                Отмена
              </Button>
              <Button
                color="red"
                loading={clearQuick.isPending}
                onClick={handleClearConfirm}
              >
                Да, очистить
              </Button>
            </Group>
          </Stack>
        </Modal>
      </Stack>
    </Card>
  )
}
