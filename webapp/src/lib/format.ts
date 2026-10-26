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

/**
 * Даты — в локальной зоне пользователя.
 * Полная дата — в `title` (день.месяц.год часы:минуты).
 */

/** «20.10.2026» — только день, локальная зона; пусто, если дата невалидна. */
export function dayWhen(value: string | null | undefined): string {
  const d = parseWhen(value)
  return d ? DAY_WHEN.format(d) : ''
}

/** «вторник, 20 октября 2026 г. в 15:00:00 GMT+3» — для `title`. */
export function fullWhen(value: string | null | undefined): string {
  const d = parseWhen(value)
  return d ? FULL_WHEN.format(d) : ''
}

/** «20.10.2026, 15:00» — дата и время в локальной зоне; пусто, если дата невалидна. */
export function shortWhen(value: string | null | undefined): string {
  const d = parseWhen(value)
  return d ? SHORT_WHEN.format(d) : ''
}

function parseWhen(value: string | null | undefined): Date | null {
  if (!value) return null
  const d = new Date(value)
  return Number.isNaN(d.getTime()) ? null : d
}

const SHORT_WHEN = new Intl.DateTimeFormat('ru-RU', {
  dateStyle: 'short',
  timeStyle: 'short',
})

const DAY_WHEN = new Intl.DateTimeFormat('ru-RU', {
  dateStyle: 'short',
})

const FULL_WHEN = new Intl.DateTimeFormat('ru-RU', {
  dateStyle: 'full',
  timeStyle: 'long',
})

export function dayLabel(value: string | null | undefined): string {
  if (!value) return ''
  const d = new Date(value)
  if (Number.isNaN(d.getTime())) return ''
  return d.toLocaleDateString(undefined, {
    day: 'numeric',
    month: 'long',
    year: 'numeric',
  })
}
