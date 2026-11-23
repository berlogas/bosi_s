import { Group, UnstyledButton } from '@mantine/core'
import {
  IconBold,
  IconCode,
  IconEraser,
  IconHeading,
  IconItalic,
  IconLink,
  IconList,
  IconQuote,
  IconStrikethrough,
  IconTable,
} from '@tabler/icons-react'
import React, { useMemo } from 'react'
import { type EditorView } from '@codemirror/view'
import { EditorSelection } from '@codemirror/state'

interface ToolbarAction {
  icon: React.ReactNode
  title: string
  before: string
  after: string
  hotkey?: string
  action?: 'clear'
}

function insertAtCursor(view: EditorView, before: string, after: string = '') {
  const { state } = view
  const { selection } = state
  const changes = selection.ranges.map((range) => {
    const from = range.from
    const to = range.to
    const selectedText = state.doc.sliceString(from, to)
    const newText = before + selectedText + after
    return { from, to, insert: newText }
  })
  view.dispatch({ changes })
}

function clearFormatting(view: EditorView) {
  const { state } = view
  const { selection } = state

  const hasSelection = selection.ranges.some((r) => r.from !== r.to)
  let ranges = selection.ranges
  if (!hasSelection) {
    ranges = [EditorSelection.range(0, state.doc.length)]
  }

  const changes = ranges.map((range) => {
    const from = range.from
    const to = range.to
    const selectedText = state.doc.sliceString(from, to)
    const cleanText = selectedText
      .replace(/\*\*(.+?)\*\*/g, '$1')
      .replace(/\*(.+?)\*/g, '$1')
      .replace(/~~(.+?)~~/g, '$1')
      .replace(/`(.+?)`/g, '$1')
      .replace(/\*\[(.+?)\]\(\S+\)/g, '$1')
      .replace(/^###\s+/gm, '')
      .replace(/^##\s+/gm, '')
      .replace(/\s+###$/gm, '')
      .replace(/\s+##$/gm, '')
      .replace(/(?<!^)(?<!\s)###$/gm, '')
      .replace(/(?<!^)(?<!\s)##$/gm, '')
      .replace(/^>\s+/gm, '')
      .replace(/^-\s+/gm, '')
      .replace(/^\d+\.\s+/gm, '')
    return { from, to, insert: cleanText }
  })
  view.dispatch({ changes })
}

interface ToolbarProps {
  readOnly?: boolean
  editorView: EditorView | null
  wrapLines?: boolean
  onToggleWrap?: () => void
}

export function Toolbar({
  readOnly,
  editorView,
  wrapLines = true,
  onToggleWrap,
}: ToolbarProps) {
  const actions = useMemo<ToolbarAction[]>(
    () => [
      {
        icon: <IconHeading size={14} />,
        title: 'Заголовок 2 (H2)',
        before: '## ',
        after: '',
        hotkey: 'Ctrl+2',
      },
      {
        icon: <IconHeading size={14} />,
        title: 'Заголовок 3 (H3)',
        before: '### ',
        after: '',
        hotkey: 'Ctrl+3',
      },
      {
        icon: <IconBold size={14} />,
        title: 'Жирный (Ctrl+B)',
        before: '**',
        after: '**',
      },
      {
        icon: <IconItalic size={14} />,
        title: 'Курсив (Ctrl+I)',
        before: '*',
        after: '*',
      },
      {
        icon: <IconStrikethrough size={14} />,
        title: 'Зачёркнутый',
        before: '~~',
        after: '~~',
      },
      {
        icon: <IconList size={14} />,
        title: 'Маркированный список',
        before: '- ',
        after: '',
      },
      {
        icon: <IconList size={14} />,
        title: 'Нумерованный список',
        before: '1. ',
        after: '',
      },
      { icon: <IconQuote size={14} />, title: 'Цитата', before: '> ', after: '' },
      { icon: <IconCode size={14} />, title: 'Код (inline)', before: '`', after: '`' },
      {
        icon: <IconLink size={14} />,
        title: 'Ссылка (Ctrl+K)',
        before: '[',
        after: '](url)',
      },
      {
        icon: <IconTable size={14} />,
        title: 'Таблица',
        before: '| Header 1 | Header 2 |\n|---|---|\n| Cell 1 | Cell 2 |',
        after: '',
      },
      {
        icon: <IconEraser size={14} />,
        title: 'Очистить форматирование',
        before: '',
        after: '',
        hotkey: 'Ctrl+\\',
        action: 'clear',
      },
    ],
    [],
  )

  const getView = () => editorView

  if (readOnly) return null

  return (
    <Group
      gap="xs"
      style={{
        flexWrap: 'wrap',
        padding: 'var(--mantine-spacing-xs)',
        borderBottom: '1px solid var(--mantine-color-default-border)',
      }}
    >
      <UnstyledButton
        onClick={onToggleWrap}
        disabled={readOnly}
        title={wrapLines ? 'Отключить перенос строк' : 'Включить перенос строк'}
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          width: 32,
          height: 32,
          borderRadius: 'var(--mantine-radius-sm)',
          color: wrapLines
            ? 'var(--mantine-color-primary-filled)'
            : 'var(--mantine-color-text)',
          backgroundColor: wrapLines
            ? 'var(--mantine-color-primary-light)'
            : 'transparent',
        }}
      >
        <svg
          width="16"
          height="16"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          <path d="M21 10H3" />
          <path d="M15 14H3" />
          <path d="M17 18H3" />
          <path d="M21 6H3" />
        </svg>
      </UnstyledButton>
      <UnstyledButton
        style={{
          width: '1px',
          height: '24px',
          backgroundColor: 'var(--mantine-color-default-border)',
          margin: '0 4px',
        }}
        disabled
      />
      {actions.map((action, idx) => (
        <UnstyledButton
          key={idx}
          onClick={() => {
            const view = getView()
            if (!view) return
            if (action.action === 'clear') {
              clearFormatting(view)
            } else {
              insertAtCursor(view, action.before, action.after)
            }
          }}
          disabled={readOnly}
          title={`${action.title}${action.hotkey ? ` (${action.hotkey})` : ''}`}
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            width: 32,
            height: 32,
            borderRadius: 'var(--mantine-radius-sm)',
            color: 'var(--mantine-color-text)',
            backgroundColor: 'transparent',
          }}
        >
          {action.icon}
        </UnstyledButton>
      ))}
    </Group>
  )
}
