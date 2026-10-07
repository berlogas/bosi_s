/**
 * Рендер markdown ответов LLM.
 *
 * Безопасность: rehype-sanitize режет всё, что не разрешено схемой
 * (скрипты, iframe, style) — ответ генерирует модель и может содержать
 * произвольный текст. `mdSafeReferences` чинит формат «1. [2]: doc»:
 * markdown-it/streamlit трактовали это как link-definition и съедали
 * строку, оставляя голые «1. 2.» (см. citation_guard).
 *
 * Цитаты `[n]` превращаются в ссылки `#src-n` (remark-плагин): клик
 * подсвечивает источник n в списке ответа (кнопка/Enter тоже работают —
 * это настоящий <a>).
 */

import type { ReactNode } from 'react'
import rehypeSanitize from 'rehype-sanitize'
import ReactMarkdown from 'react-markdown'

/** «1. [2]: doc» → «1. [2] doc» — убираем двоеточие после сноски. */
const REF_ENTRY_RE = /^([ \t]*\d+\.)[ \t]+\[([0-9]+)\]:/gm

export function mdSafeReferences(text: string): string {
  return text.replace(REF_ENTRY_RE, '$1 [$2]')
}

// ---------------------------------------------------------------- цитаты

/** Минимальный mdast-узел (без зависимости от пакета mdast в рантайме). */
interface MdastNode {
  type: string
  value?: string
  url?: string
  children?: MdastNode[]
  [key: string]: unknown
}

/** `[12]` в тексте → ссылка `#src-12`; уже готовые ссылки не трогаем. */
const CITATION_RE = /\[(\d{1,3})\]/g

function splitTextNode(node: MdastNode): MdastNode[] {
  const value = node.value ?? ''
  CITATION_RE.lastIndex = 0
  if (!CITATION_RE.test(value)) return [node]
  CITATION_RE.lastIndex = 0

  const parts: MdastNode[] = []
  let cursor = 0
  for (const match of value.matchAll(CITATION_RE)) {
    const start = match.index ?? 0
    if (start > cursor) {
      parts.push({ type: 'text', value: value.slice(cursor, start) })
    }
    parts.push({
      type: 'link',
      url: `#src-${match[1]}`,
      children: [{ type: 'text', value: match[0] }],
    })
    cursor = start + match[0].length
  }
  if (cursor < value.length) parts.push({ type: 'text', value: value.slice(cursor) })
  return parts
}

function walk(node: MdastNode): void {
  if (!node.children || node.type === 'link' || node.type === 'code') return
  const next: MdastNode[] = []
  for (const child of node.children) {
    if (child.type === 'text') next.push(...splitTextNode(child))
    else {
      walk(child)
      next.push(child)
    }
  }
  node.children = next
}

/** remark-плагин: делает `[n]` кликабельными цитатами. */
export function remarkCitations() {
  return (tree: MdastNode) => walk(tree)
}

// ---------------------------------------------------------------- рендер

export function MarkdownText({
  text,
  onCitation,
}: {
  text: string
  /** Клик по `[n]`: подсветить источник n в списке ответа. */
  onCitation?: (index: number) => void
}) {
  return (
    <ReactMarkdown
      rehypePlugins={[rehypeSanitize]}
      remarkPlugins={[remarkCitations]}
      components={{
        a({ href, children }: { href?: string; children?: ReactNode }) {
          const match = href?.match(/^#src-(\d+)$/)
          if (match && onCitation) {
            const index = Number(match[1])
            return (
              <a
                href={href}
                onClick={(event) => {
                  event.preventDefault()
                  onCitation(index)
                }}
              >
                {children}
              </a>
            )
          }
          return <a href={href}>{children}</a>
        },
      }}
    >
      {mdSafeReferences(text)}
    </ReactMarkdown>
  )
}
