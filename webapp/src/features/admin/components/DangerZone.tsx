/**
 * Компонент для danger zone действий: typed confirmation.
 * Кнопка disabled до ввода точной фразы подтверждения.
 */

import { cloneElement, useState } from 'react'
import { Modal, TextInput, Button, Group, Alert, Stack } from '@mantine/core'

export interface DangerZoneProps {
  /** Текст кнопки-триггера (если не передан children) */
  label?: string
  /** Текст, который нужно ввести для подтверждения */
  confirmText: string
  /** Callback при подтверждении. Промис, который отклоняется при ошибке,
   *  оставляет окно открытым. */
  onConfirm: () => void | Promise<void>
  /** Кастомный рендер триггера (если нужна не кнопка) */
  children?: React.ReactNode
  /** Цвет кнопки подтверждения */
  confirmColor?: 'red' | 'orange' | 'blue'
  /** Дополнительное предупреждение */
  warning?: string
  /** Блокирует триггер и открытие модалки (например, нельзя удалить себя) */
  disabled?: boolean
  /** Ошибка действия: показывается в окне, и окно не закрывается. */
  error?: React.ReactNode
}

export function DangerZone({
  label = 'Удалить',
  confirmText,
  onConfirm,
  children,
  confirmColor = 'red',
  warning,
  disabled = false,
  error,
}: DangerZoneProps) {
  const [opened, setOpened] = useState(false)
  const [input, setInput] = useState('')

  const canConfirm = input === confirmText

  const handleOpen = () => {
    if (disabled) return
    setInput('')
    setOpened(true)
  }

  const handleConfirm = async () => {
    try {
      await onConfirm()
    } catch {
      // Действие не удалось: окно оставляем открытым, ошибку показывает
      // вызывающий (свойство error).
      return
    }
    setOpened(false)
    setInput('')
  }

  // Триггер: либо своя кнопка, либо переданный элемент. В своём элементе
  // onClick обязателен — иначе модалка не откроется (кнопка «Удалить» в
  // таблице копий и «Сбросить…» на странице обслуживания).
  const child = children as React.ReactElement<{
    onClick?: () => void
    disabled?: boolean
  }> | null
  const trigger = child ? (
    cloneElement(child, {
      onClick: handleOpen,
      disabled: disabled || child.props?.disabled,
    })
  ) : (
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
      <Modal
        opened={opened}
        onClose={() => {
          setOpened(false)
          setInput('')
        }}
        title={label}
        centered
        size="sm"
      >
        <Stack gap="md">
          <Alert color="red" title="Действие необратимо">
            Введите <b>{confirmText}</b> для подтверждения.
          </Alert>
          {warning && <Alert color="yellow">{warning}</Alert>}
          {error && (
            <Alert color="red" role="alert">
              {error}
            </Alert>
          )}
          <TextInput
            label={`Введите "${confirmText}"`}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            disabled={canConfirm}
            autoFocus
          />
          <Group justify="flex-end">
            <Button
              variant="default"
              onClick={() => {
                setOpened(false)
                setInput('')
              }}
            >
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
