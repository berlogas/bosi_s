import { describe, expect, it } from 'vitest'

import { dayWhen, fullWhen, shortWhen } from './format'

// TZ зафиксирована в vite.config.ts (`test.env`): 12:00 UTC = 15:00 MSK.
describe('shortWhen', () => {
  it('переводит UTC в локальную зону', () => {
    expect(shortWhen('2026-10-20T12:00:00Z')).toBe('20.10.2026, 15:00')
  })

  it('понимает смещение в ISO-строке', () => {
    expect(shortWhen('2026-10-20T12:00:00+00:00')).toBe('20.10.2026, 15:00')
  })

  it('сдвигает сутки: полночь UTC уже следующий день по локальному времени', () => {
    expect(shortWhen('2026-10-20T23:30:00Z')).toBe('21.10.2026, 02:30')
  })

  it('пустая и битая дата дают пустую строку', () => {
    expect(shortWhen(null)).toBe('')
    expect(shortWhen(undefined)).toBe('')
    expect(shortWhen('')).toBe('')
    expect(shortWhen('не дата')).toBe('')
  })
})

describe('dayWhen', () => {
  it('отдаёт только день в локальной зоне', () => {
    expect(dayWhen('2026-10-20T12:00:00Z')).toBe('20.10.2026')
  })

  it('битая дата → пусто', () => {
    expect(dayWhen('не дата')).toBe('')
  })
})

describe('fullWhen', () => {
  it('отдаёт полную дату с зоной — для title', () => {
    expect(fullWhen('2026-10-20T12:00:00Z')).toContain('20 октября 2026')
    expect(fullWhen('2026-10-20T12:00:00Z')).toContain('15:00:00')
    expect(fullWhen('2026-10-20T12:00:00Z')).toContain('GMT+3')
  })

  it('битая дата → пусто', () => {
    expect(fullWhen('не дата')).toBe('')
  })
})
