/**
 * Чат сессии — паритет `chat_tab` из workspace.py (Фаза 2).
 *
 * Порядок блоков 1-в-1: история пузырями (удаление пары «вопрос+ответ»
 * кнопкой на вопросе) → pending-вопрос фоновой задачи → упавший обмен →
 * несохранённый (кэш/синхронный) ответ → «Очистить чат» в два шага →
 * ввод с режимом поиска и фоновым режимом.
 *
 * Жизнь фоновой задачи: `task_id` лежит в sessionStorage — панель этапов
 * восстанавливается после F5 (у Streamlit это было в session_state и
 * обрывалось закрытием вкладки). Завершение задачи гасит панель:
 * done → ответ в истории, error/cancelled → вопрос с ошибкой в чате
 * (иначе «долго думала, а ответа нет» без объяснения).
 */

import {
  Alert,
  Button,
  Group,
  Modal,
  Select,
  Stack,
  Switch,
  Text,
  TextInput,
} from '@mantine/core'
import { useQueryClient } from '@tanstack/react-query'
import { useEffect, useMemo, useState } from 'react'

import { client } from '../../api/client'
import { AnswerView } from '../../components/AnswerView'
import { TaskPanel } from '../../components/TaskPanel'
import type { AnswerSource, MessageOut, SearchMode } from '../../api/types'
import {
  chatKeys,
  useClearMessages,
  useDeleteMessage,
  useMessages,
  useTask,
} from './queries'
import { ChatBubble } from './ChatBubble'
import { clearChatTask, loadChatTask, saveChatTask } from './taskStorage'

const MODE_OPTIONS = [
  { value: 'hybrid', label: 'Гибридный' },
  { value: 'project_focus', label: 'Фокус на проекте' },
  { value: 'session_only', label: 'Только сессия' },
  { value: 'global_only', label: 'Только глобальная база' },
] as const satisfies { value: SearchMode; label: string }[]

type FailedExchange = { q: string; kind: 'error' | 'cancelled'; text: string }
type LastExchange = { q: string; answer: NonNullable<AnswerViewPropsAnswer> }

interface AnswerViewPropsAnswer {
  answer?: string
  sources?: AnswerSource[]
  references?: string[]
  from_cache?: boolean
  base_empty?: boolean
  stats?: Record<string, unknown>
}

/** Есть ли такой вопрос уже в истории — чтобы не рисовать его дважды. */
function asked(history: MessageOut[], question: string | null | undefined): boolean {
  const target = (question ?? '').trim()
  if (!target) return false
  return history.some((m) => (m.content ?? '').trim() === target && m.role === 'user')
}

/** Вопрос из пары удалённого сообщения — чтобы забыть и локальный кэш. */
function pairQuestion(history: MessageOut[], index: number): string | null {
  const message = history[index]
  if (!message) return null
  if (message.role !== 'assistant') return message.content
  for (let i = index - 1; i >= 0; i -= 1) {
    if (history[i]?.role === 'user') return history[i]?.content ?? null
  }
  return null
}

export function ChatTab({
  sessionId,
  readOnly,
}: {
  sessionId: string
  readOnly: boolean
}) {
  const queryClient = useQueryClient()
  const [limit, setLimit] = useState(100)

  const restored = useMemo(() => loadChatTask(sessionId), [sessionId])
  const [taskId, setTaskId] = useState<string | null>(restored?.taskId ?? null)
  const [pending, setPending] = useState<string | null>(restored?.question ?? null)
  const [failed, setFailed] = useState<FailedExchange | null>(null)
  const [last, setLast] = useState<LastExchange | null>(null)

  const [query, setQuery] = useState('')
  const [mode, setMode] = useState<SearchMode>('hybrid')
  const [useAsync, setUseAsync] = useState(true)
  const [sendError, setSendError] = useState<string | null>(null)
  const [sending, setSending] = useState(false)
  const [clearAsk, setClearAsk] = useState(false)
  const [clearError, setClearError] = useState<string | null>(null)

  const deleteMessage = useDeleteMessage(sessionId)
  const clearMessages = useClearMessages(sessionId)
  const task = useTask(taskId)

  // ---------------------------------------------------------------- история
  const messages = useMessages(sessionId, limit)
  // useMemo: иначе новый массив на каждый рендер гонит эффекты-«хвосты»
  const items = useMemo(() => messages.data?.messages ?? [], [messages.data])
  const total = messages.data?.total ?? 0
  const historyError = messages.isError
    ? messages.error instanceof Error
      ? messages.error.message
      : 'Не удалось загрузить историю'
    : null

  // ----------------------------------------------- жизнь фоновой задачи
  const status = task.data?.status
  useEffect(() => {
    if (!taskId || !status) return
    if (status === 'done') {
      // задача дописала обмен в историю — вопрос больше не pending
      clearChatTask()
      setTaskId(null)
      setPending(null)
      void queryClient.invalidateQueries({
        queryKey: chatKeys.messages(sessionId),
      })
    } else if (status === 'error' || status === 'cancelled') {
      // при падении задачи вопрос нельзя просто убрать: иначе только тишина
      const question = pending
      clearChatTask()
      setTaskId(null)
      setPending(null)
      if (question) {
        setFailed({
          q: question,
          kind: status,
          text: task.data?.error ?? 'Задача отменена',
        })
      }
    }
    // pending намеренно не в зависимостях: важен только переход статуса
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [status, taskId])

  // задача могла умереть на сервере (ретеншн) — панель не должна висеть вечно
  useEffect(() => {
    if (task.isError && taskId) {
      clearChatTask()
      setTaskId(null)
      setPending(null)
    }
  }, [task.isError, taskId])

  // завершаем «хвосты»: обмен уже попал в историю — локально его не держим
  useEffect(() => {
    if (!messages.data) return
    if (failed && asked(items, failed.q)) setFailed(null)
    if (last && asked(items, last.q)) setLast(null)
    if (pending && asked(items, pending)) setPending(null)
  }, [items, messages.data, failed, last, pending])

  // ---------------------------------------------------------------- отправка
  async function send(text: string) {
    const question = text.trim()
    if (!question || sending || readOnly) return
    setSendError(null)
    setSending(true)
    setQuery('')

    try {
      if (useAsync) {
        const { task_id } = await client.chatQueryAsync(sessionId, question, mode)
        saveChatTask({ sessionId, taskId: task_id, question })
        setTaskId(task_id)
        setPending(question)
      } else {
        const answer = await client.chatQuery(sessionId, question, mode)
        setLast({ q: question, answer })
        // не из кэша — обмен уже на сервере: подтянуть историю
        if (!answer.from_cache) {
          void queryClient.invalidateQueries({
            queryKey: chatKeys.messages(sessionId),
          })
        }
      }
    } catch (cause) {
      setSendError(
        cause instanceof Error ? cause.message : 'Не удалось отправить вопрос',
      )
      setQuery(question) // вернуть текст, чтобы не перепечатывать
    } finally {
      setSending(false)
    }
  }

  // ---------------------------------------------------------------- действия
  function forgetExchange(question: string | null | undefined) {
    const target = (question ?? '').trim()
    if (!target) return
    if ((pending ?? '').trim() === target) {
      clearChatTask()
      setTaskId(null)
      setPending(null)
    }
    if (last?.q.trim() === target) setLast(null)
    if (failed?.q.trim() === target) setFailed(null)
  }

  function handleDelete(message: MessageOut, index: number) {
    if (readOnly || !message.id) return
    forgetExchange(pairQuestion(items, index))
    deleteMessage.mutate(message.id)
  }

  function handleCancelTask() {
    if (!taskId) return
    client.cancelTask(taskId).catch(() => {
      // задача могла уже завершиться — статус догонит поллинг
    })
  }

  function handleClearConfirm() {
    setClearError(null)
    clearMessages.mutate(undefined, {
      onSuccess: () => {
        setClearAsk(false)
        setLast(null)
        setFailed(null)
      },
      onError: (cause) =>
        setClearError(
          cause instanceof Error ? cause.message : 'Не удалось очистить историю',
        ),
    })
  }

  // ---------------------------------------------------------------- рендер
  return (
    <Stack gap="sm">
      <Group justify="space-between">
        <Text fw={600}>Чат</Text>
        {!readOnly && (
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

      {task.data && taskId && (
        <TaskPanel task={task.data} onCancel={handleCancelTask} cancelPending={false} />
      )}

      {historyError && <Alert color="red">{historyError}</Alert>}

      {items.length === 0 && !pending && !failed && !last && (
        <Text size="sm" c="dimmed">
          Переписки пока нет — задайте первый вопрос.
        </Text>
      )}

      {total > items.length && (
        <Button
          size="xs"
          variant="subtle"
          onClick={() => setLimit((value) => value + 100)}
        >
          Показать более ранние ({total - items.length})
        </Button>
      )}

      {items.map((message, index) => {
        const role = message.role === 'user' ? 'user' : 'assistant'
        // кнопка одна на пару и стоит на вопросе: нажатие убирает оба пузыря;
        // исключение — ответ без вопроса (старая запись): иначе нечем удалить
        const orphanAnswer =
          role === 'assistant' && !items.slice(0, index).some((m) => m.role === 'user')
        const deletable = !readOnly && !!message.id && (role === 'user' || orphanAnswer)
        return (
          <ChatBubble
            key={message.id ?? `${index}-${message.created_at}`}
            role={role}
            action={
              deletable ? (
                <Button
                  size="compact-xs"
                  variant="subtle"
                  color="red"
                  aria-label="Удалить вопрос вместе с ответом"
                  loading={deleteMessage.isPending}
                  onClick={() => handleDelete(message, index)}
                >
                  🗑
                </Button>
              ) : undefined
            }
          >
            {role === 'user' ? (
              <Text size="sm" style={{ whiteSpace: 'pre-wrap' }}>
                {message.content}
              </Text>
            ) : (
              <Stack gap={4}>
                <AnswerView
                  answer={{
                    answer: message.content,
                    sources: (message.sources ?? []) as AnswerSource[],
                    checks: message.checks as Record<string, unknown> | undefined,
                  }}
                />
                {message.duration_seconds !== null &&
                  message.duration_seconds !== undefined && (
                    <Text size="xs" c="dimmed">
                      {message.duration_seconds} с
                    </Text>
                  )}
              </Stack>
            )}
          </ChatBubble>
        )
      })}

      {/* Вопрос, ушедший в фоновую задачу: пузырь сразу, ответ допишет история */}
      {pending && !asked(items, pending) && (
        <ChatBubble
          role="user"
          action={
            !readOnly && (
              <Button
                size="compact-xs"
                variant="subtle"
                color="red"
                aria-label="Отменить вопрос и убрать его из переписки"
                onClick={() => {
                  if (taskId) handleCancelTask()
                  clearChatTask()
                  setTaskId(null)
                  setPending(null)
                }}
              >
                🗑
              </Button>
            )
          }
        >
          <Text size="sm" style={{ whiteSpace: 'pre-wrap' }}>
            {pending}
          </Text>
        </ChatBubble>
      )}
      {pending && !asked(items, pending) && (
        <ChatBubble role="assistant">
          <Text size="sm" c="dimmed">
            Вопрос обрабатывается…
          </Text>
        </ChatBubble>
      )}

      {/* Вопрос, на который задача упала или была отменена */}
      {failed && !asked(items, failed.q) && (
        <>
          <ChatBubble
            role="user"
            action={
              !readOnly && (
                <Button
                  size="compact-xs"
                  variant="subtle"
                  color="red"
                  aria-label="Убрать вопрос и ошибку из переписки"
                  onClick={() => setFailed(null)}
                >
                  🗑
                </Button>
              )
            }
          >
            <Text size="sm" style={{ whiteSpace: 'pre-wrap' }}>
              {failed.q}
            </Text>
          </ChatBubble>
          <ChatBubble role="assistant">
            {failed.kind === 'cancelled' ? (
              <Text size="sm" c="dimmed">
                {failed.text}
              </Text>
            ) : (
              <Alert color="red" role="alert">
                Не получилось ответить: {failed.text}
              </Alert>
            )}
          </ChatBubble>
        </>
      )}

      {/* Синхронный/кэшированный ответ, которого ещё нет в истории */}
      {last && !asked(items, last.q) && (
        <>
          <ChatBubble
            role="user"
            action={
              !readOnly && (
                <Button
                  size="compact-xs"
                  variant="subtle"
                  color="red"
                  aria-label="Убрать вопрос и ответ из переписки"
                  onClick={() => setLast(null)}
                >
                  🗑
                </Button>
              )
            }
          >
            <Text size="sm" style={{ whiteSpace: 'pre-wrap' }}>
              {last.q}
            </Text>
          </ChatBubble>
          <ChatBubble role="assistant">
            <AnswerView answer={last.answer} />
          </ChatBubble>
        </>
      )}

      {sendError && (
        <Alert color="red" role="alert">
          {sendError}
        </Alert>
      )}

      <form
        onSubmit={(event) => {
          event.preventDefault()
          void send(query)
        }}
      >
        <Stack gap="xs">
          <Group align="flex-end" wrap="nowrap" gap="xs">
            <TextInput
              label="Ваш вопрос"
              placeholder="Спросите что-нибудь…"
              value={query}
              onChange={(event) => setQuery(event.currentTarget.value)}
              disabled={readOnly || sending}
              style={{ flex: 1 }}
            />
            <Select
              label="Режим поиска"
              data={MODE_OPTIONS as unknown as { value: string; label: string }[]}
              value={mode}
              onChange={(value) => setMode((value as SearchMode) ?? 'hybrid')}
              allowDeselect={false}
              style={{ width: 190 }}
              disabled={readOnly}
            />
            <Button
              type="submit"
              loading={sending}
              disabled={readOnly || !query.trim()}
            >
              ➤
            </Button>
          </Group>
          <Switch
            label="Фоновый режим"
            description="Позволяет видеть прогресс и отменять запрос"
            checked={useAsync}
            onChange={(event) => setUseAsync(event.currentTarget.checked)}
            disabled={readOnly}
          />
        </Stack>
      </form>

      <Modal
        opened={clearAsk}
        onClose={() => setClearAsk(false)}
        title="Очистить переписку?"
        centered
      >
        <Stack>
          <Text size="sm">
            Удалить всю переписку этой сессии? Отменить будет нельзя.
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
              loading={clearMessages.isPending}
              onClick={handleClearConfirm}
            >
              Да, очистить
            </Button>
          </Group>
        </Stack>
      </Modal>
    </Stack>
  )
}
