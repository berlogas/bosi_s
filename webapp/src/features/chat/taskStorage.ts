/**
 * Восстановление фоновой задачи чата после F5.
 *
 * У Streamlit `task_id` жил в `st.session_state` и переживал только
 * перерисовки; закрытие вкладки обрывало опрос. Здесь — sessionStorage
 * (живёт до закрытия вкладки), ключ содержит sessionId: задача другой
 * сессии к текущему чату не подмешивается.
 */

const KEY = 'boasi.chat.task'

export interface StoredChatTask {
  sessionId: string
  taskId: string
  /** Вопрос, ушедший в задачу (пузырь pending переживает F5). */
  question: string
}

export function loadChatTask(sessionId: string): StoredChatTask | null {
  try {
    const raw = sessionStorage.getItem(KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw) as StoredChatTask
    return parsed.sessionId === sessionId ? parsed : null
  } catch {
    return null
  }
}

export function saveChatTask(task: StoredChatTask): void {
  try {
    sessionStorage.setItem(KEY, JSON.stringify(task))
  } catch {
    // приватный режим — просто без восстановления после F5
  }
}

export function clearChatTask(): void {
  try {
    sessionStorage.removeItem(KEY)
  } catch {
    // нет доступа к sessionStorage — не критично
  }
}
