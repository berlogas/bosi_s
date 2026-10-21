/**
 * Тесты ответа: клик по цитате `[n]` подсвечивает источник (Фаза 2),
 * санитизация markdown, блоки References и предупреждений.
 */

import { render as rtlRender, screen } from '@testing-library/react'
import type { RenderResult } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ReactElement } from 'react'
import { MantineProvider } from '@mantine/core'
import { beforeEach, describe, expect, it } from 'vitest'

import { AnswerView } from './AnswerView'
import { MarkdownText } from './MarkdownText'

/** компоненты используют Mantine — без провайдера рендер падает */
function render(ui: ReactElement): RenderResult {
  return rtlRender(<MantineProvider>{ui}</MantineProvider>)
}

const SOURCES = [
  {
    index: 1,
    marker: '📚',
    source_scope: 'global' as const,
    dockey: 'k1',
    title: 'Данные GF/F',
    category: 'global_knowledge',
    score: 0.87,
  },
  {
    index: 2,
    marker: '📁',
    source_scope: 'session' as const,
    dockey: 'k2',
    title: 'Заметки экспедиции',
    category: 'notes',
    score: 0.41,
  },
]

describe('AnswerView', () => {
  it('клик по цитате [2] подсвечивает второй источник', async () => {
    render(
      <AnswerView
        answer={{ answer: 'Ответ по данным [1] и заметкам [2].', sources: SOURCES }}
      />,
    )

    // цитаты стали ссылками
    const citation = screen.getByRole('link', { name: '[2]' })
    expect(citation).toHaveAttribute('href', '#src-2')

    await userEvent.click(citation)
    const highlighted = document.querySelector('[data-src="2"]')
    expect(highlighted).not.toBeNull()
    expect(highlighted?.className).toContain('mantine-')
    // второй клик снимает подсветку
    await userEvent.click(citation)
    expect(document.querySelector('[data-src="2"]')?.getAttribute('bg')).toBeNull()
  })

  it('цитата без колбэка остаётся ссылкой, но не ломает рендер', () => {
    render(<AnswerView answer={{ answer: 'Сноска [12] в тексте' }} />)
    expect(screen.getByRole('link', { name: '[12]' })).toHaveAttribute(
      'href',
      '#src-12',
    )
  })

  it('санитизация: скрипт из ответа LLM не исполняется', () => {
    render(
      <AnswerView
        answer={{
          answer: 'Текст <script>alert(1)</script> <img src=x onerror=alert(2)>',
        }}
      />,
    )
    expect(document.querySelector('script')).toBeNull()
    expect(document.querySelector('img')).toBeNull()
    expect(screen.getByText(/Текст/)).toBeInTheDocument()
  })

  it('формат References «1. [2]: doc» не теряет строку (citation_guard)', () => {
    render(
      <AnswerView
        answer={{
          answer: 'Ответ.\n\n1. [2]: Данные GF/F (глобальная база)\n2. [1]: Заметки',
          references: ['[2] Данные GF/F', '[1] Заметки'],
        }}
      />,
    )
    // двоеточие убрано (mdSafeReferences) — строки списка живы, а не
    // съедены link-definition'ом (паритет citation_guard)
    const list = screen.getByRole('list')
    expect(list.textContent).toContain('[2] Данные GF/F (глобальная база)')
    expect(list.textContent).toContain('[1] Заметки')
    // expander со списком источников открывается
    expect(screen.getByText('Список источников')).toBeInTheDocument()
  })

  it('«Список источников» — кнопка: Enter и Space раскрывают', async () => {
    render(<AnswerView answer={{ answer: 'Ответ', references: ['[1] Данные GF/F'] }} />)

    const toggle = screen.getByRole('button', { name: 'Список источников' })
    expect(toggle).toHaveAttribute('aria-expanded', 'false')
    toggle.focus()
    expect(toggle).toHaveFocus()

    await userEvent.keyboard('{Enter}')
    expect(toggle).toHaveAttribute('aria-expanded', 'true')
    expect(screen.getByText('• [1] Данные GF/F')).toBeInTheDocument()

    await userEvent.keyboard(' ')
    expect(toggle).toHaveAttribute('aria-expanded', 'false')
  })

  it('предупреждения grounding из stats: первое + expander остальных', async () => {
    render(
      <AnswerView
        answer={{
          answer: 'Ответ с проблемой',
          stats: {
            grounding: { warnings: ['Цитата [3] не найдена', 'Факт без опоры'] },
            citations: { warnings: [] },
          },
        }}
      />,
    )
    expect(screen.getByText(/Цитата \[3\] не найдена/)).toBeInTheDocument()
    const expander = screen.getByRole('button', {
      name: /Все предупреждения проверки \(2\)/,
    })
    expect(expander).toHaveAttribute('aria-expanded', 'false')
    expander.focus()
    await userEvent.keyboard('{Enter}')
    expect(await screen.findByText(/Факт без опоры/)).toBeInTheDocument()
    expect(expander).toHaveAttribute('aria-expanded', 'true')
  })

  it('base_empty и from_cache: поясняющие подписи', () => {
    render(<AnswerView answer={{ answer: '', base_empty: true, from_cache: true }} />)
    expect(screen.getByText(/в базе знаний нет документов/)).toBeInTheDocument()
    expect(screen.getByText('Ответ взят из кэша')).toBeInTheDocument()
  })
})

/**
 * Плотная вёрстка ответа: стандартные margin абзацев съедали место, а ответ
 * почти всегда состоит из пары абзацев и списка ссылок.
 */
describe('MarkdownText: компактные отступы', () => {
  const answer = 'Текст ответа [1].\n\nСсылки\n\n1. [1] napoleon_bonaparte_context'
  // Рендер внутри beforeEach: авто-cleanup Testing Library вычищает DOM после
  // каждого теста, поэтому рендер на уровне describe остался бы пустым.
  let container: HTMLElement
  beforeEach(() => {
    container = rtlRender(
      <MantineProvider>
        <MarkdownText text={answer} />
      </MantineProvider>,
    ).container
  })

  it('у абзацев нет собственных вертикальных отступов', () => {
    for (const p of Array.from(container.querySelectorAll('p'))) {
      expect((p as HTMLElement).style.margin).toBe('0px')
    }
  })

  it('у списка источников обнулены отступы', () => {
    const list = container.querySelector('ol') as HTMLElement | null
    expect(list, 'нумерованный список источников должен рендериться').not.toBeNull()
    expect(list!.style.margin).toBe('0px')
  })

  it('блоки разнесены малым фиксированным интервалом', () => {
    const root = container.querySelector('div[style*="flex"]') as HTMLElement | null
    expect(root, 'контейнер с плотной вёрсткой должен быть').not.toBeNull()
    expect(root!.style.gap).toBe('2px')
  })
})
