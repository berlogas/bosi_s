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
 */

import { useEffect, useState } from 'react'
import { useLocation } from 'react-router-dom'

const STORAGE_KEY = 'boasi.lastSessionPath'

/** Прочитать запомненную сессию: значение проверяется, а не берётся как есть. */
export function readLastSessionPath(): string | null {
  try {
    const stored = window.sessionStorage.getItem(STORAGE_KEY)
    return stored && /^\/s\/[^/]+$/.test(stored) ? stored : null
  } catch {
    // приватный режим браузера и отключённое хранилище: пункт останется
    // серым, но приложение работает
    return null
  }
}

export function useCurrentSessionPath(): string | null {
  const location = useLocation()
  const fromUrl = /^\/s\/[^/]+/.exec(location.pathname)?.[0] ?? null
  const [lastPath, setLastPath] = useState<string | null>(readLastSessionPath)

  useEffect(() => {
    if (fromUrl) {
      setLastPath(fromUrl)
      try {
        window.sessionStorage.setItem(STORAGE_KEY, fromUrl)
      } catch {
        // хранилище недоступно — пункт просто не переживёт перезагрузку
      }
      return
    }
    setLastPath(readLastSessionPath())
  }, [fromUrl, location.pathname])

  return fromUrl ?? lastPath
}
