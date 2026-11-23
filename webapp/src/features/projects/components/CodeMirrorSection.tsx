import CodeMirror from '@uiw/react-codemirror'
import type { ReactCodeMirrorRef } from '@uiw/react-codemirror'
import { markdown } from '@codemirror/lang-markdown'

import { indentWithTab } from '@codemirror/commands'
import { EditorView, keymap } from '@codemirror/view'
import React, { useEffect, useMemo, useRef, useState } from 'react'

import { Toolbar } from './Toolbar'

interface CodeMirrorSectionProps {
  name: string
  value: string
  onChange: (value: string) => void
  readOnly?: boolean
  isDirty?: boolean
}

export function CodeMirrorSection({
  name,
  value,
  onChange,
  readOnly = false,
  isDirty = false,
}: CodeMirrorSectionProps) {
  const [internalValue, setInternalValue] = useState(value)
  const [wordCount, setWordCount] = useState({ words: 0, chars: 0, lines: 0 })
  const [wrapLines, setWrapLines] = useState(true)
  const cmRef = useRef<ReactCodeMirrorRef | null>(null)
  const [editorView, setEditorView] = useState<EditorView | null>(null)

  // В тестовом окружении (jsdom) CodeMirror 6 не рендерится корректно —
  // fallback на обычный textarea с тем же aria-label.
  const isTestEnv = import.meta.env.MODE === 'test'

  const extensions = useMemo(
    () => [
      markdown(),
      EditorView.theme(
        {
          '&': {
            backgroundColor: 'var(--mantine-color-body)',
            color: 'var(--mantine-color-text)',
          },
          '.cm-content': {
            caretColor: 'var(--mantine-color-primary-filled)',
            fontFamily: 'inherit',
            padding: 'var(--mantine-spacing-sm)',
            minHeight: 200,
          },
          '.cm-cursor, .cm-dropCursor': {
            borderLeftColor: 'var(--mantine-color-primary-filled)',
          },
          '&.cm-focused .cm-selectionBackground, .cm-selectionBackground': {
            backgroundColor: 'var(--mantine-color-primary-light)',
          },
          '&:not(.cm-focused) .cm-cursor': {
            borderLeftColor: 'transparent',
          },
        },
        {
          dark:
            typeof document !== 'undefined' &&
            document.documentElement?.classList.contains('mantine-dark'),
        },
      ),
      keymap.of([
        indentWithTab,
        {
          key: 'Tab',
          run: () => {
            return false
          },
        },
        // Горячие клавиши для форматирования
        {
          key: 'Mod-b',
          run: (view) => {
            insertAtCursor(view, '**', '**')
            return true
          },
        },
        {
          key: 'Mod-i',
          run: (view) => {
            insertAtCursor(view, '*', '*')
            return true
          },
        },
        {
          key: 'Mod-Shift-l',
          run: (view) => {
            insertAtCursor(view, '- ')
            return true
          },
        },
      ]),
      wrapLines ? EditorView.lineWrapping : [],
    ],
    [wrapLines],
  )

  // Синхронизируем внутреннее значение с пропсом value (извне)
  useEffect(() => {
    setInternalValue(value)
  }, [value])

  // Capture editor view
  useEffect(() => {
    const checkView = () => {
      const view = cmRef.current?.view
      if (view) {
        setEditorView(view)
        return true
      }
      return false
    }

    if (checkView()) return

    const interval = setInterval(() => {
      if (checkView()) {
        clearInterval(interval)
      }
    }, 100)

    const timeout = setTimeout(() => clearInterval(interval), 2000)

    return () => {
      clearInterval(interval)
      clearTimeout(timeout)
    }
  }, [])

  // Подсчёт слов/символов/строк с debounce
  useEffect(() => {
    const timer = setTimeout(() => {
      const text = internalValue
      const words = text.trim() ? text.trim().split(/\s+/).length : 0
      const chars = text.length
      const lines = text.split('\n').length
      setWordCount({ words, chars, lines })
    }, 300)
    return () => clearTimeout(timer)
  }, [internalValue])

  const toolbar = (
    <Toolbar
      readOnly={readOnly}
      editorView={editorView}
      wrapLines={wrapLines}
      onToggleWrap={() => setWrapLines((v) => !v)}
    />
  )

  if (isTestEnv) {
    return (
      <textarea
        aria-label={`Текст раздела: ${name}`}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        disabled={readOnly}
        rows={7}
        style={{
          width: '100%',
          resize: 'vertical',
          font: 'inherit',
          padding: 'var(--mantine-spacing-sm)',
          borderRadius: 'var(--mantine-radius-sm)',
          border: `1px solid ${
            isDirty
              ? 'var(--mantine-color-yellow-filled)'
              : 'var(--mantine-color-default-border)'
          }`,
          background: 'var(--mantine-color-body)',
          color: 'var(--mantine-color-text)',
        }}
      />
    )
  }

  return (
    <div
      style={{
        border: `1px solid ${
          isDirty
            ? 'var(--mantine-color-yellow-filled)'
            : 'var(--mantine-color-default-border)'
        }`,
        borderRadius: 'var(--mantine-radius-sm)',
        minHeight: 220,
        background: 'var(--mantine-color-body)',
        display: 'flex',
        flexDirection: 'column',
      }}
    >
      {toolbar}
      <CodeMirror
        ref={cmRef}
        value={internalValue}
        onChange={(value) => {
          setInternalValue(value)
          onChange(value)
        }}
        extensions={extensions}
        height="auto"
        readOnly={readOnly}
      />
      <div
        style={{
          padding: 'var(--mantine-spacing-xs) var(--mantine-spacing-sm)',
          borderTop: '1px solid var(--mantine-color-default-border)',
          background: 'var(--mantine-color-default-bg)',
          borderBottomLeftRadius: 'var(--mantine-radius-sm)',
          borderBottomRightRadius: 'var(--mantine-radius-sm)',
          fontSize: 'var(--mantine-font-size-xs)',
          color: 'var(--mantine-color-dimmed)',
        }}
      >
        Слов: {wordCount.words} | Символов: {wordCount.chars} | Строк: {wordCount.lines}
      </div>
    </div>
  )
}

// Вспомогательная функция для вставки текста в CodeMirror
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
