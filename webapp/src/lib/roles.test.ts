import { describe, expect, it } from 'vitest'

import { displayName, roleLabel, roleOptions } from './roles'

describe('русские подписи ролей и обращения к пользователю', () => {
  it('переводит значения ролей', () => {
    expect(roleLabel('researcher')).toBe('Исследователь')
    expect(roleLabel('admin')).toBe('Администратор')
  })

  it('неизвестную роль показывает как есть', () => {
    expect(roleLabel('supervisor')).toBe('supervisor')
  })

  it('подписи для выпадающих списков сохраняют технические значения', () => {
    expect(roleOptions(['researcher', 'admin'])).toEqual([
      { value: 'researcher', label: 'Исследователь' },
      { value: 'admin', label: 'Администратор' },
    ])
  })

  it('обращается по ФИО, а без него — по логину', () => {
    expect(displayName({ username: 'ivanov', full_name: 'Иванов Иван Иванович' })).toBe(
      'Иванов Иван Иванович',
    )
    expect(displayName({ username: 'ivanov', full_name: null })).toBe('ivanov')
    expect(displayName({ username: 'ivanov', full_name: '   ' })).toBe('ivanov')
  })
})
