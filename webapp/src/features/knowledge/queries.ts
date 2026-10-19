/**
 * Запросы глобальной базы знаний для чтения (парность `GET /api/documents`).
 *
 * Отдельный ключ от `adminKeys.documents`: админский список и список для
 * чтения — разные данные с разными правами, и общий ключ привёл бы к тому,
 * что один из них закэшировался бы вместо другого.
 */

import { useQuery } from '@tanstack/react-query'

import { client } from '../../api/client'

export const knowledgeKeys = {
  documents: (q: string, category: string) =>
    ['knowledge', 'documents', q, category] as const,
  stats: ['knowledge', 'stats'] as const,
}

export function useKnowledgeDocuments(
  q: string,
  category: string | null,
  enabled = true,
) {
  return useQuery({
    queryKey: knowledgeKeys.documents(q, category ?? ''),
    queryFn: () =>
      client.globalDocuments({
        q,
        category: category ?? undefined,
      }),
    enabled,
  })
}

export function useKnowledgeStats() {
  return useQuery({
    queryKey: knowledgeKeys.stats,
    queryFn: () => client.globalDocumentsStats(),
  })
}
