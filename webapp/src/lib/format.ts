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

const SESSION_STATUS_LABELS: Record<string, string> = {
  active: 'активная',
  paused: 'приостановлена',
  archived: 'в архиве',
}

/** Статус сессии словами: на карточке «active» читалось как метка, а не слово. */
export function sessionStatusLabel(value: string | null | undefined): string {
  return SESSION_STATUS_LABELS[value ?? ''] ?? value ?? '—'
}

const TASK_STATUS_LABELS: Record<string, string> = {
  queued: 'в очереди',
  running: 'выполняется',
  done: 'готово',
  error: 'ошибка',
  cancelled: 'отменено',
}

/** Статус фоновой задачи словами — вместо `running` и `error`. */
export function taskStatusLabel(value: string | null | undefined): string {
  return TASK_STATUS_LABELS[value ?? ''] ?? value ?? '—'
}

export const STATUS_ICONS: Record<string, string> = {
  queued: '⏳',
  running: '🔄',
  done: '✅',
  error: '❌',
  cancelled: '🚫',
}

/**
 * Даты — в локальной зоне пользователя.
 *
 * Сервер отдаёт UTC (`...Z` или `+00:00`); срез строки показывал UTC-время,
 * то есть в Москве событие «уезжало» на три часа назад.
 */
const SHORT_WHEN = new Intl.DateTimeFormat('ru-RU', {
  dateStyle: 'short',
  timeStyle: 'short',
})
// В `title` — та же дата с зоной: по нему видно, что перевод действительно был.
const FULL_WHEN = new Intl.DateTimeFormat('ru-RU', {
  dateStyle: 'full',
  timeStyle: 'long',
})

// День без времени — для подписей вида «самые старые от 05.01.2026».
const DAY_WHEN = new Intl.DateTimeFormat('ru-RU', { dateStyle: 'short' })

function parseWhen(iso: string | null | undefined): Date | null {
  if (!iso) return null
  const date = new Date(iso)
  return Number.isNaN(date.getTime()) ? null : date
}

/** «20.10.2026, 15:00» в локальной зоне; пусто, если дата невалидна. */
export function shortWhen(iso: string | null | undefined): string {
  const date = parseWhen(iso)
  return date ? SHORT_WHEN.format(date) : ''
}

/** «20.10.2026» — только день, локальная зона; пусто, если дата невалидна. */
export function dayWhen(iso: string | null | undefined): string {
  const date = parseWhen(iso)
  return date ? DAY_WHEN.format(date) : ''
}

/** «вторник, 20 октября 2026 г. в 15:00:00 GMT+3» — для `title`. */
export function fullWhen(iso: string | null | undefined): string {
  const date = parseWhen(iso)
  return date ? FULL_WHEN.format(date) : ''
}
