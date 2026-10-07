/**
 * Рендер markdown ответов LLM.
 *
 * Безопасность: rehype-sanitize режет всё, что не разрешено схемой
 * (скрипты, iframe, style) — ответ генерирует модель и может содержать
 * произвольный текст. `mdSafeReferences` чинит формат «1. [2]: doc»:
 * markdown-it/streamlit трактовали это как link-definition и съедали
 * строку, оставляя голые «1. 2.» (см. citation_guard).
 */

import rehypeSanitize from 'rehype-sanitize'
import ReactMarkdown from 'react-markdown'

/** «1. [2]: doc» → «1. [2] doc» — убираем двоеточие после сноски. */
const REF_ENTRY_RE = /^([ \t]*\d+\.)[ \t]+\[([0-9]+)\]:/gm

export function mdSafeReferences(text: string): string {
  return text.replace(REF_ENTRY_RE, '$1 [$2]')
}

export function MarkdownText({ text }: { text: string }) {
  return (
    <ReactMarkdown rehypePlugins={[rehypeSanitize]}>
      {mdSafeReferences(text)}
    </ReactMarkdown>
  )
}
