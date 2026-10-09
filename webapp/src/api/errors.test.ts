import { describe, expect, it } from 'vitest'

import { explainError, translateErrorText } from './errors'

describe('русские тексты ошибок', () => {
  it('переводит стандартные фразы сервера', () => {
    expect(translateErrorText('Not Found', 404)).toBe('Не найдено')
    expect(translateErrorText('Method Not Allowed', 405)).toBe(
      'Метод не поддерживается',
    )
    expect(translateErrorText('Internal Server Error', 500)).toBe(
      'Внутренняя ошибка сервера',
    )
  })

  it('не трогает собственные тексты приложения', () => {
    expect(translateErrorText('Сессия не найдена', 404)).toBe('Сессия не найдена')
    expect(
      translateErrorText('Папка-приёмник не найдена: /data/inbox', 404),
    ).toBe('Папка-приёмник не найдена: /data/inbox')
  })

  it('plain-текст 404 без JSON показывается по-русски', () => {
    const result = explainError(404, undefined, 'Not Found')

    expect(result.message).toBe('Не найдено')
    expect(result.detail).toBe('Не найдено')
  })

  it('JSON detail переводится, лимиты сохраняются', () => {
    const result = explainError(
      404,
      { detail: 'Not Found', meta: { limit: 10 } },
      '',
    )

    expect(result.message).toBe('Не найдено (лимит: 10)')
  })

  it('пустое тело даёт русский текст по статусу', () => {
    expect(explainError(403, undefined, '').message).toBe('Доступ запрещён')
    expect(explainError(422, {}, '').message).toBe('Некорректные данные запроса')
  })
})
