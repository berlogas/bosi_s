/**
 * Подписи видов генерации для интерфейса.
 *
 * Вид — техническое значение из `GenerationKind` в backend: он уходит в
 * теле запроса и по нему выбирается промпт, поэтому менять его нельзя.
 * Исследователь выбирает вид из списка и мыслит по-русски: «Сверка с
 * литературой» читается, `data_comparison` — нет. Английское значение
 * оставлено в подписи в скобках — оно пригодится при чтении документации
 * и разборе логов.
 *
 * По той же причине, что и в `sections.ts`, перевод живёт здесь: в
 * `ProjectsTab` он разъехался бы по мере добавления экранов.
 */

/** Техническое значение вида → подпись для выпадающего списка. */
const KIND_LABELS: Record<string, string> = {
  section: 'Раздел плана (section)',
  discussion: 'Обсуждение результатов (discussion)',
  literature_review: 'Обзор литературы (literature_review)',
  data_comparison: 'Сверка с литературой (data_comparison)',
  gap_analysis: 'Пробелы в литературе (gap_analysis)',
  draft_analysis: 'Разбор черновика (draft_analysis)',
  report: 'Отчёт по шаблону (report)',
}

/** Значение вида → подпись; неизвестное значение показываем как есть. */
export function kindLabel(kind: string): string {
  return KIND_LABELS[kind] ?? kind
}

/** Значения видов → пары для Mantine `Select`. */
export function kindOptions(
  values: readonly string[],
): { value: string; label: string }[] {
  return values.map((value) => ({ value, label: kindLabel(value) }))
}
