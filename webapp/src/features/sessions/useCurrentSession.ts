/**
 * Какая сессия считается текущей — для пункта меню «Текущая сессия».
 *
 * Раньше пункт определялся разбором URL (`/s/<id>`), и стоило уйти в меню
 * («Информационная панель», «База знаний»), как пункт серел: сессия в адресной
 * строке уже не значит, что её открыли. Возвращаться приходилось через
 * дашборд или руками вбивая адрес.
 *
 * Поэтому последняя открытая сессия запоминается отдельно от адреса.
 * Хранилище — `sessionStorage`, а не `localStorage`: сессия работы не должна
 * переживать закрытие вкладки, и на общей машине чужие следы не остаются.
 * Внутри значения лежит id пользователя (см. `lastSession.ts`): сессия одного
 * не подставляется другому, кто зашёл в ту же вкладку.
 */

import { useEffect, useState } from 'react'
import { useLocation } from 'react-router-dom'

import { useAuth } from '../auth/authStore'
import { readLastSessionPath, saveLastSessionPath } from './lastSession'

export function useCurrentSessionPath(): string | null {
  const location = useLocation()
  const userId = useAuth((state) => state.user?.id ?? null)
  const fromUrl = /^\/s\/[^/]+/.exec(location.pathname)?.[0] ?? null
  const [lastPath, setLastPath] = useState<string | null>(() =>
    readLastSessionPath(userId),
  )

  useEffect(() => {
    if (fromUrl) {
      setLastPath(fromUrl)
      saveLastSessionPath(fromUrl, userId)
      return
    }
    setLastPath(readLastSessionPath(userId))
  }, [fromUrl, location.pathname, userId])

  return fromUrl ?? lastPath
}
