/**
 * Подписи разделов статьи для интерфейса.
 *
 * Имя раздела — технический контракт: его backend использует в плане,
 * в ключе генерации и в ссылках API, поэтому «Introduction» там менять
 * нельзя. Пользователю же понятнее «Введение (Introduction)»: русский
 * термин для чтения, английский — чтобы свериться с требованиями
 * журнала и планом в Word. Здесь единственное место с этим переводом,
 * чтобы подписи не разъехались по экранам.
 */

/** Техническое имя раздела → русский термин. */
const SECTION_TITLES: Record<string, string> = {
  Introduction: 'Введение',
  Methods: 'Методы исследования',
  Results: 'Результаты',
  Discussion: 'Обсуждение',
  Conclusions: 'Заключение',
  Conclusion: 'Заключение',
}

/**
 * Подпись раздела: «Введение (Introduction)».
 *
 * Регистр и лишние пробелы не важны — план мог прийти из файла или из
 * ручной правки. Раздел, которого нет в справочнике, показываем как
 * есть: своё название лучше, чем пустое место.
 */
export function sectionTitle(name: string): string {
  const clean = (name ?? '').trim()
  // charAt, а не clean[0]: с noUncheckedIndexedAccess индекс даёт string | undefined
  const titled = clean ? clean.charAt(0).toUpperCase() + clean.slice(1) : clean
  const known = SECTION_TITLES[clean] ?? SECTION_TITLES[titled]
  if (!known) return clean
  return `${known} (${clean})`
}
