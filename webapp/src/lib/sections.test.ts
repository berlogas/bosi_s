import { describe, expect, it } from 'vitest'

import { sectionTitle } from './sections'

describe('двуязычные подписи разделов', () => {
  it('переводит названия плана и оставляет английское имя', () => {
    expect(sectionTitle('Introduction')).toBe('Введение (Introduction)')
    expect(sectionTitle('Methods')).toBe('Методы исследования (Methods)')
    expect(sectionTitle('Results')).toBe('Результаты (Results)')
    expect(sectionTitle('Discussion')).toBe('Обсуждение (Discussion)')
    expect(sectionTitle('Conclusions')).toBe('Заключение (Conclusions)')
  })

  it('принимает единственное число в имени раздела', () => {
    expect(sectionTitle('Conclusion')).toBe('Заключение (Conclusion)')
  })

  it('не зависит от регистра и лишних пробелов', () => {
    expect(sectionTitle('  results  ')).toBe('Результаты (results)')
  })

  it('свой раздел показывает как есть, а не пустым местом', () => {
    expect(sectionTitle('Приложение А')).toBe('Приложение А')
  })
})
