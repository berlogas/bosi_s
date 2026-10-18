/**
 * Подписи технических значений, которые выбирают в интерфейсе.
 *
 * Все значения приходят из backend и уходят обратно без изменений: статус
 * проекта разбирает `ProjectStatus`, роль документа — `ProjectDocRole`.
 * Менять их нельзя, а показывать пользователю `planning` вместо
 * «Планирование» — значит заставлять его держать в голове словарь из
 * документации. Здесь значения переводятся один раз.
 *
 * Соседние словари живут в `roles.ts` (роли пользователей), `sections.ts`
 * (названия разделов) и `kinds.ts` (виды генерации): у каждого свой
 * домен, но правило одно — интерфейс говорит по-русски, API остаётся
 * английским.
 */

/** Статус проекта → подпись. */
const PROJECT_STATUS_LABELS: Record<string, string> = {
  planning: 'Планирование (planning)',
  drafting: 'Написание текста (drafting)',
  reviewing: 'Вычитка (reviewing)',
  done: 'Готово (done)',
}

/** Роль документа в проекте → подпись. */
const DOC_ROLE_LABELS: Record<string, string> = {
  reference: 'Литература (reference)',
  data: 'Данные (data)',
  draft: 'Черновик (draft)',
}

/** Значение статуса → подпись; неизвестное значение показываем как есть. */
export function projectStatusLabel(status: string): string {
  return PROJECT_STATUS_LABELS[status] ?? status
}

/** Значение роли документа → подпись; неизвестное значение как есть. */
export function docRoleLabel(role: string): string {
  return DOC_ROLE_LABELS[role] ?? role
}

/** Статусы → пары для Mantine `Select`. */
export function projectStatusOptions(
  values: readonly string[],
): { value: string; label: string }[] {
  return values.map((value) => ({ value, label: projectStatusLabel(value) }))
}

/** Роли документа → пары для Mantine `Select`. */
export function docRoleOptions(
  values: readonly string[],
): { value: string; label: string }[] {
  return values.map((value) => ({ value, label: docRoleLabel(value) }))
}
