/**
 * Типы, которых нет в openapi-схеме.
 *
 * Бэкенд отдаёт задачи и источники как свободный dict (FastAPI-эндпоинт
 * без response_model), поэтому контракт описываем здесь по
 * `Task.to_dict()` (services/tasks.py) и `source_dict()` (rag_fusion.py).
 */

import type { components } from './schema'

export type SessionOut = components['schemas']['SessionOut']
export type SessionDetail = components['schemas']['SessionDetailOut']
export type SessionStatus = components['schemas']['SessionStatus']
export type User = components['schemas']['UserOut']
export type AuditLogEntry = components['schemas']['AuditLogOut']
export type CreateUserRequest = components['schemas']['CreateUserRequest']
export type MessageOut = components['schemas']['MessageOut']
export type MessagePage = components['schemas']['MessagePage']
export type SearchMode = components['schemas']['SearchMode']

/** Ответ POST /api/chat/query — источники как массив объектов (см. AnswerSource). */
export type ChatQueryResponse = Omit<
  components['schemas']['ChatQueryResponse'],
  'sources'
> & { sources?: AnswerSource[] }

/**
 * Полезная нагрузка завершённой фоновой задачи быстрого вопроса
 * (`Task.result`): маршрут `/api/chat/quick-query` отдаёт только task_id,
 * поэтому в openapi-схеме её нет — описываем по телу задачи в
 * `backend/app/api/chat.py::quick_query`.
 */
export type QuickQueryResult = {
  answer: string
  sources: AnswerSource[]
  references: string[]
  query: string
  from_cache: boolean
  stats: Record<string, unknown>
  /** Ответ получен без опоры на базу (база пуста или ничего не нашлось). */
  base_empty: boolean
}

export type TaskStatus = 'queued' | 'running' | 'done' | 'error' | 'cancelled'

// ------------------------------------------------------------ документы
export type DocumentOut = components['schemas']['DocumentOut']
export type DocumentCategory = components['schemas']['DocumentCategory']
export type DocumentBatchResult = components['schemas']['DocumentBatchResultOut']

// ---------------------------------------------------------------- проекты
export type ProjectOut = components['schemas']['ProjectOut']
export type ProjectSection = components['schemas']['ProjectSectionOut']
export type ProjectSectionUpdate = components['schemas']['ProjectSectionUpdate']
export type GenerateRequest = components['schemas']['GenerateRequest']
export type GenerateResult = components['schemas']['GenerateResultOut']
export type ExportFormat = components['schemas']['ExportFormat']

/** Элемент GET .../projects/{id}/documents: { document, role }. */
export interface ProjectDocumentItem {
  document: DocumentOut
  role: string
  [key: string]: unknown
}

/** GET .../projects/{id}/progress — свободный dict (без response_model). */
export interface ProjectProgress {
  project_id: string
  status?: string
  sections: number
  written: number
  words: number
  percent: number
  [key: string]: unknown
}

/** Пробел черновика из draft-analysis (без response_model). */
export interface DraftGap {
  severity: 'high' | 'medium' | 'low' | string
  where: string
  hint: string
  excerpt?: string | null
  [key: string]: unknown
}

/** GET .../projects/{id}/draft-analysis — свободный dict. */
export interface DraftAnalysis {
  has_gaps: boolean
  gaps: DraftGap[]
  by_severity: Record<string, number>
  [key: string]: unknown
}

export interface Task {
  id: string
  kind: string
  title: string
  status: TaskStatus
  progress: number
  step: string | null
  error: string | null
  cancel_requested: boolean
  /** Автор задачи: админ фильтрует по нему, у пользователя — своё же. */
  user_id: string | null
  session_id: string | null
  project_id: string | null
  created_at: string | null
  started_at: string | null
  finished_at: string | null
  /** секунды с запуска; null, пока не стартовала */
  seconds: number | null
  /** секунды в текущем этапе */
  stage_seconds: number | null
  result: unknown
}

export interface TaskListResponse {
  tasks: Task[]
  active: number
}

export interface CancelTaskResponse {
  cancelled: boolean
  task: Task
}

/** Источник ответа — `source_dict()` в rag_fusion.py. */
export interface AnswerSource {
  index: number
  marker: string
  source_scope: 'global' | 'session'
  dockey?: string
  docname?: string | null
  title?: string | null
  citation?: string
  category?: string | null
  tags?: string[]
  page?: string | null
  /** Взвешенная оценка ранжирования (видна в API, в UI не показывается). */
  score?: number
  /** Релевантность 0..1: насколько документ отвечает на вопрос. */
  relevance?: number
  [key: string]: unknown
}

/** Раздел проверок в stats/checks: { grounding: { warnings: [...] }, ... } */
export interface ChecksSection {
  warnings?: string[]
  [key: string]: unknown
}

export interface AnswerChecks {
  grounding?: ChecksSection
  citations?: ChecksSection
  [key: string]: unknown
}
