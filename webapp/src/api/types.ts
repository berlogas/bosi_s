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
export type SessionResume = components['schemas']['SessionResumeOut']
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
/** Документ глобальной базы в виде для чтения (обычный исследователь). */
export type GlobalDocumentOut = components['schemas']['GlobalDocumentOut']
export type DocumentCategory = components['schemas']['DocumentCategory']
export type DocumentBatchResult = components['schemas']['DocumentBatchResultOut']

// ---------------------------------------------------------------- проекты
export type ProjectOut = components['schemas']['ProjectOut'] & {
  /** ID документа, прикреплённого как правила оформления журнала (style guide). */
  style_guide_document_id?: string | null
  /** Язык генерации разделов статьи (ru | en и т.д.). */
  language?: string
  /** Порядок сортировки проекта в списке. */
  order?: number
}
export type ProjectSection = components['schemas']['ProjectSectionOut']
export type ProjectSectionUpdate = components['schemas']['ProjectSectionUpdate']
export type GenerateRequest = components['schemas']['GenerateRequest']
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

// ============================================================ SectionPlan / SectionVersion
/** Тип раздела из SectionKind enum. */
export type SectionKind = 'standard' | 'literature_review' | 'data' | 'discussion' | 'custom'

export type SectionStatus = 'pending' | 'in_progress' | 'review' | 'approved'
export type SectionPlanStatus = SectionStatus

export type VersionStatus = 'draft' | 'review' | 'approved' | 'superseded' | 'archived'

/** План раздела (SectionPlan) */
export interface SectionPlan {
  id: string
  project_id: string
  name: string
  kind: SectionKind
  order: number
  required: boolean
  word_target: number
  word_min: number
  word_max: number
  notes: string
  language: string
  depends_on: string[]
  status: SectionStatus
  current_version_id: string | null
  /** Текущая версия раздела вместе с её текстом (`content_md`). */
  current_version: SectionVersion | null
  created_at: string
  updated_at: string
}

/** Версия раздела (SectionVersion) */
export interface SectionVersion {
  id: string
  section_plan_id: string
  project_id: string
  session_id: string | null
  content_md: string
  language: string
  source_language: string | null
  word_count: number
  citation_map: AnswerSource[]
  generation_params: Record<string, unknown>
  seconds: number | null
  cost_usd: number | null
  token_counts: {
    prompt_tokens?: number
    completion_tokens?: number
    cache_read_tokens?: number
    cache_creation_tokens?: number
    /** Имя модели — строка, поэтому значения здесь не только числа. */
    model?: string
    [key: string]: unknown
  }
  quality_report: Partial<QualityReport>
  status: VersionStatus
  parent_version_id: string | null
  created_by: string | null
  created_at: string
  updated_at: string
}

/** Отчёт качества версии */
export interface QualityReport {
  citations_ok: boolean
  dangling_citations: number[]
  unused_sources: number[]
  grounding_score: number | null
  completeness_score: number | null
  style_compliance: Record<string, boolean>
  terminology_consistency: Record<string, string>
  warnings: string[]
  passed: boolean
}

/** Дерево версий */
export interface VersionNode {
  version: SectionVersion
  children: VersionNode[]
}

export interface VersionTree {
  section_plan_id: string
  section_name: string
  roots: VersionNode[]
  all_versions: SectionVersion[]
}

/** Семантический diff */
export interface SemanticDiff {
  from_version_id: string
  to_version_id: string
  added_claims: Array<{ index: number; text: string; citations: number[] }>
  removed_claims: Array<{ index: number; text: string; citations: number[] }>
  modified_claims: Array<{ from: { index: number; text: string; citations: number[] }; to: { index: number; text: string; citations: number[] }; type: string }>
  citation_changes: { added: number[]; removed: number[] }
  terminology_changes: Record<string, string>
  word_count_delta: number
  summary: string
}

/** Языковая политика проекта */
export interface ProjectLanguagePolicy {
  primary_language: string
  allowed_languages: string[]
  translate_on_approve: boolean
  auto_translate_target: string | null
  quality_grounding_threshold: number
  quality_completeness_threshold: number
  quality_citations_required: boolean
  max_generation_iterations: number
}

/** Глоссарий терминов */
export interface TerminologyGlossaryEntry {
  id: string
  project_id: string
  term: string
  translations: Record<string, string>
  definition: string | null
  created_at: string
  updated_at: string
}

/** Результат пакетной перегенерации */
export interface BatchRegenerateResult {
  total: number
  regenerated: Array<{ section: string; version_id: string; word_count: number }>
  skipped: Array<{ section: string; reason: string }>
  failed: Array<{ section: string; error: string }>
}

/** Результат сборки манускрипта */
export interface CompiledManuscript {
  full_text: string
  sections: Array<{ name: string; kind: string; content: string; word_count: number }>
  bibliography: Array<{ index: number; title: string | null; citation: string | null; dockey: string | null }>
  stats: { total_words: number; sections_count: number; sources_count: number; language: string }
  warnings: string[]
}

/** Результат LLM merge */
export interface MergeResult {
  version_id: string
  content_md: string
  citation_map: AnswerSource[]
  word_count: number
  strategy: string
}

/** Результат terminology check */
export interface TerminologyCheckResult {
  project_id: string
  glossary_terms: Record<string, Record<string, string>>
  section_terminology: Array<{ section: string; term: string; expected: string; type: string }>
  consistent: boolean
}

/** Результат style compliance */
export interface StyleComplianceResult {
  compliant: boolean
  violations: Array<{ rule: string; location: string; suggestion: string }>
  warnings: string[]
}

/** Результат pre-generation check */
export interface PreGenerationCheckResult {
  ready: boolean
  checks: {
    section_exists: boolean
    has_question: boolean
    sources_found: number
    sources_sufficient: boolean
    has_style_guide: boolean
    has_glossary: boolean
    language_supported: boolean
  }
  warnings: string[]
  sources_preview: Array<{ index: number; title: string | null; score: number }>
}
