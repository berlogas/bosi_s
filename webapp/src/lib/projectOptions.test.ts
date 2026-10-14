import { describe, expect, it } from 'vitest'

import {
  docRoleLabel,
  docRoleOptions,
  projectStatusLabel,
  projectStatusOptions,
} from './projectOptions'
import { sessionStatusLabel, taskStatusLabel } from './format'

describe('русские подписи технических значений', () => {
  it('переводит статусы проекта, оставляя английское значение', () => {
    expect(projectStatusLabel('planning')).toBe('Планирование (planning)')
    expect(projectStatusLabel('drafting')).toBe('Написание текста (drafting)')
    expect(projectStatusLabel('reviewing')).toBe('Вычитка (reviewing)')
    expect(projectStatusLabel('done')).toBe('Готово (done)')
  })

  it('переводит роли документа в проекте', () => {
    expect(docRoleLabel('reference')).toBe('Литература (reference)')
    expect(docRoleLabel('data')).toBe('Данные (data)')
    expect(docRoleLabel('draft')).toBe('Черновик (draft)')
  })

  it('неизвестные значения показывает как есть', () => {
    expect(projectStatusLabel('submitted')).toBe('submitted')
    expect(docRoleLabel('appendix')).toBe('appendix')
  })

  it('в списках выбора сохраняет технические значения', () => {
    expect(projectStatusOptions(['planning', 'done'])).toEqual([
      { value: 'planning', label: 'Планирование (planning)' },
      { value: 'done', label: 'Готово (done)' },
    ])
    expect(docRoleOptions(['data'])).toEqual([
      { value: 'data', label: 'Данные (data)' },
    ])
  })

  it('переводит статусы сессии и задачи словами', () => {
    expect(sessionStatusLabel('active')).toBe('активная')
    expect(sessionStatusLabel('archived')).toBe('в архиве')
    expect(taskStatusLabel('running')).toBe('выполняется')
    expect(taskStatusLabel('error')).toBe('ошибка')
    expect(sessionStatusLabel('paused')).toBe('приостановлена')
  })
})