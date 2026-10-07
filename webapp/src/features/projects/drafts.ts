/**
 * Черновики разделов статьи — паритет `state.drafts` из boasi_ui/state.py.
 *
 * Streamlit держал черновики в session_state и писал их в «точку
 * возврата» (snapshot) при смене вкладки. Здесь — sessionStorage
 * (переживает F5 вкладки), ключ содержит sessionId; черновики
 * подмешиваются в snapshot при автосохранении вкладки.
 */

export interface Drafts {
  [section: string]: string
}

const KEY = 'boasi.project.drafts'

interface StoredDrafts {
  sessionId: string
  drafts: Drafts
}

export function loadDrafts(sessionId: string): Drafts {
  try {
    const raw = sessionStorage.getItem(KEY)
    if (!raw) return {}
    const parsed = JSON.parse(raw) as StoredDrafts
    return parsed.sessionId === sessionId ? (parsed.drafts ?? {}) : {}
  } catch {
    return {}
  }
}

export function saveDraft(sessionId: string, section: string, value: string): void {
  try {
    const drafts = loadDrafts(sessionId)
    drafts[section] = value
    sessionStorage.setItem(KEY, JSON.stringify({ sessionId, drafts }))
  } catch {
    // приватный режим — черновик живёт только в памяти компонента
  }
}

/** Пустые черновики в snapshot не тащим (как в snapshot() state.py). */
export function nonEmptyDrafts(drafts: Drafts): Drafts {
  return Object.fromEntries(
    Object.entries(drafts).filter(([, value]) => Boolean(value)),
  )
}
