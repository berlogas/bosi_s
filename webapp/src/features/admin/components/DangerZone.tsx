/**
 * Компонент для danger zone действий: typed confirmation.
 * Кнопка disabled до ввода точной фразы подтверждения.
 */

import { useState } from 'react'
import { Modal, TextInput, Button, Group, Alert, Stack } from '@mantine/core'

export interface DangerZoneProps {
  /** Текст кнопки-триггера (если не передан children) */
  label?: string
  /** Текст, который нужно ввести для подтверждения */
  confirmText: string
  /** Callback при подтверждении */
  onConfirm: () => void
  /** Кастомный рендер триггера (если нужна не кнопка) */
  children?: React.ReactNode
  /** Цвет кнопки подтверждения */
  confirmColor?: 'red' | 'orange' | 'blue'
  /** Дополнительное предупреждение */
  warning?: string
  /** Блокирует триггер и открытие модалки (например, нельзя удалить себя) */
  disabled?: boolean
}

export function DangerZone({
  label = 'Удалить',
  confirmText,
  onConfirm,
  children,
  confirmColor = 'red',
  warning,
  disabled = false,
}: DangerZoneProps) {
  const [opened, setOpened] = useState(false)
  const [input, setInput] = useState('')

  const canConfirm = input === confirmText

  const handleOpen = () => {
    if (disabled) return
    setInput('')
    setOpened(true)
  }

  const handleConfirm = () => {
    onConfirm()
    setOpened(false)
    setInput('')
  }

  const trigger = children || (
    <Button
      variant="subtle"
      color={confirmColor}
      onClick={handleOpen}
      disabled={disabled}
    >
      {label}
    </Button>
  )

  return (
    <>
      {trigger}
      <Modal opened={opened} onClose={() => { setOpened(false); setInput('') }} title={label} centered size="sm">
        <Stack gap="md">
          <Alert color="red" title="Действие необратимо">
            Введите <b>{confirmText}</b> для подтверждения.
          </Alert>
          {warning && <Alert color="yellow">{warning}</Alert>}
          <TextInput
            label={`Введите "${confirmText}"`}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            disabled={canConfirm}
            autoFocus
          />
          <Group justify="flex-end">
            <Button variant="default" onClick={() => { setOpened(false); setInput('') }}>
              Отмена
            </Button>
            <Button color={confirmColor} disabled={!canConfirm} onClick={handleConfirm}>
              Подтвердить
            </Button>
          </Group>
        </Stack>
      </Modal>
    </>
  )
}