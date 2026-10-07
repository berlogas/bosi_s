/** Форматирование — 1-в-1 с helpers Streamlit-компонента ui.py. */

/** «42с» / «3:07» / «1:02:05» — компактная запись секунд. */
export function fmtSeconds(value: unknown): string {
  const seconds = Number.parseInt(String(value ?? 0), 10)
  if (Number.isNaN(seconds) || seconds < 1) return ''
  if (seconds < 60) return `${seconds}с`
  if (seconds < 3600)
    return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`
  const h = Math.floor(seconds / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  return `${h}:${String(m).padStart(2, '0')}:${String(seconds % 60).padStart(2, '0')}`
}

/** Срок хранения сессии словами. */
export function ttlLabel(daysLeft: number): string {
  if (daysLeft <= 0) return 'срок истёк'
  if (daysLeft === 1) return 'остался 1 день'
  if (daysLeft < 5) return `осталось ${daysLeft} дня`
  return `осталось ${daysLeft} дней`
}

const CATEGORY_LABELS: Record<string, string> = {
  project_draft: 'Черновики проекта',
  project_data: 'Данные',
  temp_literature: 'Временная литература',
  notes: 'Заметки',
  supplementary: 'Дополнительные материалы',
  global_knowledge: 'Глобальная база',
}

export function categoryLabel(value: string | null | undefined): string {
  return CATEGORY_LABELS[value ?? ''] ?? value ?? 'Без категории'
}

export const STATUS_ICONS: Record<string, string> = {
  queued: '⏳',
  running: '🔄',
  done: '✅',
  error: '❌',
  cancelled: '🚫',
}

/** «16.10.2026 12:34» из ISO-строки; пусто, если дата невалидна. */
export function shortWhen(iso: string | null | undefined): string {
  if (!iso) return ''
  return iso.slice(0, 16).replace('T', ' ')
}
