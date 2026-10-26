/**
 * Чат сессии — Волна 3 (план UI_REDESIGN_PLAN.md).
 *
 * История пузырей → закреплённый композитор снизу (sticky bottom внутри
 * scroll-контейнера) → undo-тост вместо модалки при удалении пары →
 * оценка времени из панели задачи → A11y (role="log", aria-live,
 * prefers-reduced-motion).
 *
 * Жизнь фоновой задачи: `task_id` лежит в sessionStorage — панель этапов
 * восстанавливается после F5. Завершение задачи гасит панель:
 * done → ответ в истории, error/cancelled → вопрос с ошибкой в чате.
 */

import {
  Alert,
  Box,
  Button,
  Group,
  Modal,
  SegmentedControl,
  Stack,
  Text,
  Textarea,
} from '@mantine/core'
import { notifications } from '@mantine/notifications'
import { useMediaQuery } from '@mantine/hooks'
import { useQueryClient } from '@tanstack/react-query'
import { useEffect, useMemo, useRef, useState } from 'react'

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

export function ChatTab({
  sessionId,
  readOnly,
}: {
  sessionId: string
  readOnly: boolean
}) {
  const queryClient = useQueryClient()
  // prefers-reduced-motion: не анимируем автоскролл, если пользователь так 요청
  const reduceMotion = useMediaQuery('(prefers-reduced-motion: reduce)')

  const restored = useMemo(() => loadChatTask(sessionId), [sessionId])
  const [taskId, setTaskId] = useState<string | null>(restored?.taskId ?? null)
  const [pending, setPending] = useState<string | null>(restored?.question ?? null)
  const [failed, setFailed] = useState<FailedExchange | null>(null)
  const [last, setLast] = useState<LastExchange | null>(null)

  const [query, setQuery] = useState('')
  const [mode, setMode] = useState<SearchMode>('hybrid')
  const [sendError, setSendError] = useState<string | null>(null)
  const [sending, setSending] = useState(false)
  const [clearAsk, setClearAsk] = useState(false)
  const [clearError, setClearError] = useState<string | null>(null)

  // Скролл-контейнер истории: отслеживаем, ушёл ли пользователь от низа,
  // чтобы показать кнопку «К последнему» и счётчик непрочитанных.
  const scrollRef = useRef<HTMLDivElement>(null)
  const [scrolledFromBottom, setScrolledFromBottom] = useState(false)
  const [unreadCount, setUnreadCount] = useState(0)

  // Якорь автоскролла: следуем за свежим ответом, пока он не приедет.
  const answerRef = useRef<HTMLDivElement>(null)
  const [follow, setFollow] = useState<number | null>(null)

  // Контекст отмены удаления пары (храним предыдущий кэш для undo-тоста).
  const undoRef = useRef<{ previous: unknown; messageId: string } | null>(null)

  // ---------------------------------------------------------------- запросы
  const [limit, setLimit] = useState(100)
  const messages = useMessages(sessionId, limit)
  const task = useTask(taskId)
  const clearMessages = useClearMessages(sessionId)
  const items = useMemo(() => messages.data?.messages ?? [], [messages.data])
  const total = messages.data?.total ?? 0
  const lastAssistantIndex = useMemo(() => {
    for (let i = items.length - 1; i >= 0; i -= 1) {
      if (items[i]?.role === 'assistant') return i
    }
    return -1
  }, [items])
  const chatEmpty = items.length === 0 && !pending && !failed && !last
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
      clearChatTask()
      setTaskId(null)
      setPending(null)
      void queryClient.invalidateQueries({
        queryKey: chatKeys.messages(sessionId),
      })
    } else if (status === 'error' || status === 'cancelled') {
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
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [status, taskId])

  useEffect(() => {
    if (task.isError && taskId) {
      clearChatTask()
      setTaskId(null)
      setPending(null)
    }
  }, [task.isError, taskId])

  useEffect(() => {
    if (!messages.data) return
    if (failed && asked(items, failed.q)) setFailed(null)
    if (last && asked(items, last.q)) setLast(null)
    if (pending && asked(items, pending)) setPending(null)
  }, [items, messages.data, failed, last, pending])

  useEffect(() => {
    if (follow === null) return
    if (last === null && items.length <= follow) return
    requestAnimationFrame(() => {
      if (reduceMotion) {
        answerRef.current?.scrollIntoView({ block: 'start' })
      } else {
        answerRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })
      }
    })
    setFollow(null)
  }, [follow, items.length, last, reduceMotion])

  // отслеживаем скролл: ушёл от низа → кнопка «вниз» + счётчик непрочитанных
  useEffect(() => {
    const el = scrollRef.current
    if (!el) return
    const onScroll = () => {
      const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 24
      setScrolledFromBottom(!atBottom)
      if (atBottom && unreadCount > 0) setUnreadCount(0)
    }
    el.addEventListener('scroll', onScroll)
    return () => el.removeEventListener('scroll', onScroll)
  }, [unreadCount])

  // ---------------------------------------------------------------- отправка
  async function send(text: string) {
    const question = text.trim()
    if (!question || sending || readOnly) return
    setSendError(null)
    setSending(true)
    setQuery('')

    try {
      const { task_id } = await client.chatQueryAsync(sessionId, question, mode)
      saveChatTask({ sessionId, taskId: task_id, question })
      setTaskId(task_id)
      setPending(question)
      setFollow(items.length)
    } catch (cause) {
      setSendError(
        cause instanceof Error ? cause.message : 'Не удалось отправить вопрос',
      )
      setQuery(question) // вернуть текст, чтобы не перепечатывать
    } finally {
      setSending(false)
    }
  }

  function handleKeyDown(event: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault()
      void send(query)
    }
  }

  // ---------------------------------------------------------------- действия

  /** Удаление пары с оптимистичным откатом и undo-тостом (план Волны 3, п. 7). */
  const deleteMessage = useDeleteMessage(sessionId, {
    onMutate: async (messageId: string) => {
      await queryClient.cancelQueries({ queryKey: chatKeys.messages(sessionId) })
      const previous = queryClient.getQueryData(
        chatKeys.messages(sessionId),
      )
      undoRef.current = { previous, messageId }

      queryClient.setQueryData(chatKeys.messages(sessionId), (old: unknown) => {
          if (!old || typeof old !== 'object' || old === null) return old
          const data = old as { messages: MessageOut[]; total: number }
          if (!data.messages) return old
          const idx = data.messages.findIndex((m: MessageOut) => m.id === messageId)
          if (idx === -1) return old
          const toRemove = new Set([idx])
          const msg = data.messages[idx]!
          if (msg.role === 'user') {
            const adjacent = data.messages[idx + 1]
            if (adjacent?.role === 'assistant') {
              toRemove.add(idx + 1)
            }
          } else if (msg.role === 'assistant') {
            if (idx - 1 >= 0 && data.messages[idx - 1]?.role === 'user') {
              toRemove.add(idx - 1)
            }
          }
          return {
            ...data,
            messages: data.messages.filter((_unknown: unknown, i: number) => !toRemove.has(i)),
            total: Math.max(0, data.total - toRemove.size),
          }
        },
      )
      return { previous }
    },
    onError: (_err: unknown, _messageId: string, context: { previous?: unknown } | undefined) => {
      queryClient.setQueryData(chatKeys.messages(sessionId), context?.previous)
      undoRef.current = null
      notifications.show({
        title: 'Не удалось удалить пару',
        color: 'error',
        message: 'Попробуйте ещё раз',
      })
    },
    onSuccess: () => {
      notifications.show({
        title: 'Пара удалена',
        message: 'Вопрос и ответ убраны из переписки',
      })
    },
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: chatKeys.messages(sessionId) })
    },
  })

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
      onError: (cause: unknown) =>
        setClearError(
          cause instanceof Error ? cause.message : 'Не удалось очистить историю',
        ),
    })
  }

  function scrollToBottom() {
    const el = scrollRef.current
    if (!el) return
    el.scrollTop = el.scrollHeight
    setScrolledFromBottom(false)
    setUnreadCount(0)
  }

  // ---------------------------------------------------------------- рендер
  return (
    <Box style={{ height: '100dvh', overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
      <Box
        style={{ flex: 1, overflowY: 'auto', position: 'relative' }}
        ref={scrollRef}
      >
        <Stack gap="sm" px="md" pt="md" pb="xl">
          <Group justify="space-between">
            <Text fw={600}>Чат</Text>
            {!readOnly && !chatEmpty && (
              <Button
                size="xs"
                variant="subtle"
                color="error"
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

          {historyError && <Alert color="error">{historyError}</Alert>}

          {chatEmpty && (
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

          {/* История — live-регион для скрин-ридеров (план Волны 3, п. 8) */}
          <div role="log" aria-live="polite" aria-relevant="additions">
            {items.map((message, index) => {
              const role = message.role === 'user' ? 'user' : 'assistant'
              const orphanAnswer =
                role === 'assistant' &&
                !items.slice(0, index).some((m) => m.role === 'user')
              const deletable =
                !readOnly && !!message.id && (role === 'user' || orphanAnswer)
              return (
                <ChatBubble
                  key={message.id ?? `${index}-${message.created_at}`}
                  ref={
                    follow !== null && index === lastAssistantIndex
                      ? answerRef
                      : undefined
                  }
                  role={role}
                  action={
                    deletable ? (
                      <Button
                        size="compact-xs"
                        variant="subtle"
                        color="error"
                        aria-label="Удалить вопрос вместе с ответом"
                        loading={
                          deleteMessage.isPending &&
                          deleteMessage.variables === message.id
                        }
                        onClick={() => {
                          deleteMessage.mutate(message.id)
                          setUnreadCount((n) => n + 1)
                        }}
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

            {/* Вопрос, ушедший в фоновую задачу */}
            {pending && !asked(items, pending) && (
              <ChatBubble
                role="user"
                action={
                  !readOnly && (
                    <Button
                      size="compact-xs"
                      variant="subtle"
                      color="error"
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
                <Text size="sm" c="dimmed">Вопрос обрабатывается…</Text>
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
                        color="error"
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
                    <Text size="sm" c="dimmed">{failed.text}</Text>
                  ) : (
                    <Alert color="error" role="alert">
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
                        color="error"
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
                <ChatBubble role="assistant" ref={answerRef}>
                  <AnswerView answer={last.answer} />
                </ChatBubble>
              </>
            )}
          </div>

          {sendError && (
            <Alert color="error" role="alert">{sendError}</Alert>
          )}
        </Stack>
      </Box>

      {/* Закреплённый композитор — sticky bottom (план Волны 3, п. 1–2) */}
      <Box style={{ position: 'sticky', bottom: 0, top: 'auto' }}>
        <form
          onSubmit={(event) => {
            event.preventDefault()
            void send(query)
          }}
        >
          <Stack gap="xs" p="md">
            <Group align="flex-end" wrap="nowrap" gap="xs" px="md" py="xs">
              <Textarea
                label="Ваш вопрос"
                placeholder="Спросите что-нибудь…"
                value={query}
                onChange={(event) => setQuery(event.currentTarget.value)}
                onKeyDown={handleKeyDown}
                autosize
                disabled={readOnly || sending}
                style={{ flex: 1, minHeight: 'auto' }}
              />
              <SegmentedControl
                size="xs"
                data={MODE_OPTIONS}
                value={mode}
                onChange={(value) => setMode((value as SearchMode) ?? 'hybrid')}
                disabled={readOnly || sending}
              />
              <Button
                type="submit"
                loading={sending}
                disabled={readOnly || !query.trim()}
              >
                ➤
              </Button>
            </Group>
          </Stack>
        </form>
      </Box>

      {/* Кнопка «К последнему» — когда пользователь прокрутил историю вверх (план Волны 3, п. 5) */}
      {scrolledFromBottom && (
        <Box style={{ position: 'absolute', bottom: 20, right: 20, zIndex: 100 }}>
          <Button
            size="xs"
            variant="default"
            onClick={scrollToBottom}
            aria-label="К последнему сообщению"
          >
            К последнему
          </Button>
        </Box>
      )}

      {/* Очистка переписки — в два шага, модалка остаётся только для этого (план Волны 3, п. 7) */}
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
            <Alert color="error" role="alert">{clearError}</Alert>
          )}
          <Group justify="flex-end">
            <Button variant="default" onClick={() => setClearAsk(false)}>
              Отмена
            </Button>
            <Button
              color="error"
              loading={clearMessages.isPending}
              onClick={handleClearConfirm}
            >
              Да, очистить
            </Button>
          </Group>
        </Stack>
      </Modal>
    </Box>
  )
}
