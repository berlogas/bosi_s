/**
 * Хуки для новой системы SectionPlan / SectionVersion (Phase 4 UI).
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { client } from '../../../api/client'
import type { SectionKind, SectionPlanStatus, BatchRegenerateResult } from '../../../api/types'

export const sectionPlanKeys = {
  list: (sessionId: string, projectId: string) => ['section-plans', sessionId, projectId] as const,
  history: (sessionId: string, projectId: string, planId: string) => ['section-plan-history', sessionId, projectId, planId] as const,
  diff: (sessionId: string, projectId: string, from: string, to: string) => ['section-diff', sessionId, projectId, from, to] as const,
  languagePolicy: (sessionId: string, projectId: string) => ['language-policy', sessionId, projectId] as const,
  glossary: (sessionId: string, projectId: string) => ['glossary', sessionId, projectId] as const,
  terminologyCheck: (sessionId: string, projectId: string) => ['terminology-check', sessionId, projectId] as const,
  manuscript: (sessionId: string, projectId: string, language?: string) => ['manuscript', sessionId, projectId, language] as const,
}

function useInvalidateSectionPlans(sessionId: string, projectId: string) {
  const queryClient = useQueryClient()
  return (): void => {
    queryClient.invalidateQueries({ queryKey: sectionPlanKeys.list(sessionId, projectId) })
    queryClient.invalidateQueries({ queryKey: ['project-sections', sessionId, projectId] })
    // История версий живёт под префиксным ключом с planId последним сегментом;
    // инвалидируем по сессии+проекту, чтобы подхватить все планы проекта.
    queryClient.invalidateQueries({ queryKey: ['section-plan-history', sessionId, projectId] })
    queryClient.invalidateQueries({ queryKey: ['project-section-versions', sessionId, projectId] })
    queryClient.invalidateQueries({ queryKey: ['manuscript', sessionId, projectId] })
  }
}

// ============================================================ SectionPlan CRUD

export function useSectionPlans(sessionId: string | null, projectId: string | null) {
  return useQuery({
    queryKey: sectionPlanKeys.list(sessionId ?? '', projectId ?? ''),
    queryFn: () => client.sectionPlans(sessionId as string, projectId as string),
    enabled: sessionId !== null && projectId !== null,
  })
}

export function useCreateSectionPlan(sessionId: string, projectId: string) {
  const invalidate = useInvalidateSectionPlans(sessionId, projectId)
  return useMutation({
    mutationFn: (payload: {
      name: string
      kind?: SectionKind
      order?: number
      word_target?: number
      notes?: string
      language?: string
      required?: boolean
      depends_on?: string[]
    }) => client.createSectionPlan(sessionId, projectId, payload),
    onSuccess: () => invalidate(),
  })
}

export function useUpdateSectionPlan(sessionId: string, projectId: string) {
  const invalidate = useInvalidateSectionPlans(sessionId, projectId)
  return useMutation({
    mutationFn: ({
      planId,
      payload,
    }: {
      planId: string
      payload: Partial<{
        name: string
        kind: SectionKind
        order: number
        word_target: number
        notes: string
        language: string
        required: boolean
        depends_on: string[]
        status: SectionPlanStatus
      }>
    }) => client.updateSectionPlan(sessionId, projectId, planId, payload),
    onSuccess: () => invalidate(),
  })
}

export function useDeleteSectionPlan(sessionId: string, projectId: string) {
  const invalidate = useInvalidateSectionPlans(sessionId, projectId)
  return useMutation({
    mutationFn: (planId: string) => client.deleteSectionPlan(sessionId, projectId, planId),
    onSuccess: () => invalidate(),
  })
}

// ============================================================ Generation

export function useGenerateSectionV2(sessionId: string, projectId: string) {
  const invalidate = useInvalidateSectionPlans(sessionId, projectId)
  return useMutation({
    mutationFn: (payload: {
      section: string
      question: string
      notes?: string
      word_target?: number
      use_cache?: boolean
      kind?: string
    }) => client.generateSectionV2(sessionId, projectId, payload),
    onSuccess: () => invalidate(),
  })
}

// ============================================================ Translation v2

export function useTranslateSectionV2(sessionId: string, projectId: string) {
  const invalidate = useInvalidateSectionPlans(sessionId, projectId)
  return useMutation({
    mutationFn: ({
      planId,
      targetLanguage,
      versionId,
    }: {
      planId: string
      targetLanguage: string
      versionId?: string
    }) => client.translateSectionV2(sessionId, projectId, planId, targetLanguage, versionId),
    onSuccess: () => invalidate(),
  })
}

// ============================================================ Ручная правка раздела

/**
 * Сохранить текст раздела, набранный в редакторе.
 *
 * Правка уходит в `section_versions` по id плана. После сохранения обновляем
 * планы: текст приезжает в них из `current_version`.
 */
export function useSaveSectionContent(sessionId: string, projectId: string) {
  const invalidate = useInvalidateSectionPlans(sessionId, projectId)
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ planId, contentMd }: { planId: string; contentMd: string }) =>
      client.saveSectionContent(sessionId, projectId, planId, contentMd),
    onSuccess: () => {
      invalidate()
      void queryClient.invalidateQueries({ queryKey: ['project-progress', sessionId, projectId] })
      void queryClient.invalidateQueries({ queryKey: ['projects', sessionId] })
    },
  })
}

// ============================================================ История & Diff

export function useSectionHistory(sessionId: string | null, projectId: string | null, planId: string | null) {
  return useQuery({
    queryKey: sectionPlanKeys.history(sessionId ?? '', projectId ?? '', planId ?? ''),
    queryFn: () => client.sectionHistory(sessionId as string, projectId as string, planId as string),
    enabled: sessionId !== null && projectId !== null && planId !== null,
  })
}

/** Все версии разделов проекта — реальная история генераций. */
export function useProjectSectionVersions(
  sessionId: string | null,
  projectId: string | null,
) {
  return useQuery({
    queryKey: ['project-section-versions', sessionId, projectId],
    queryFn: () => client.projectSectionVersions(sessionId as string, projectId as string),
    enabled: sessionId !== null && projectId !== null,
  })
}

export function useDiffSectionVersions(
  sessionId: string | null,
  projectId: string | null,
  fromVersion: string | null,
  toVersion: string | null,
) {
  return useQuery({
    queryKey: sectionPlanKeys.diff(sessionId ?? '', projectId ?? '', fromVersion ?? '', toVersion ?? ''),
    queryFn: () => client.diffSectionVersions(sessionId as string, projectId as string, fromVersion as string, toVersion as string),
    enabled: sessionId !== null && projectId !== null && fromVersion !== null && toVersion !== null,
  })
}

// ============================================================ Rollback / Approve / Merge

export function useRollbackSection(sessionId: string, projectId: string) {
  const invalidate = useInvalidateSectionPlans(sessionId, projectId)
  return useMutation({
    mutationFn: ({
      planId,
      versionId,
    }: {
      planId: string
      versionId: string
    }) => client.rollbackSection(sessionId, projectId, planId, versionId),
    onSuccess: () => invalidate(),
  })
}

export function useApproveSection(sessionId: string, projectId: string) {
  const invalidate = useInvalidateSectionPlans(sessionId, projectId)
  return useMutation({
    mutationFn: ({
      planId,
      versionId,
    }: {
      planId: string
      versionId: string
    }) => client.approveSection(sessionId, projectId, planId, versionId),
    onSuccess: () => invalidate(),
  })
}

// ============================================================ Language Policy

// ============================================================ Glossary

export function useGlossary(sessionId: string | null, projectId: string | null) {
  return useQuery({
    queryKey: sectionPlanKeys.glossary(sessionId ?? '', projectId ?? ''),
    queryFn: () => client.getGlossary(sessionId as string, projectId as string),
    enabled: sessionId !== null && projectId !== null,
  })
}

export function useAddGlossaryEntry(sessionId: string, projectId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (payload: { term: string; translations?: Record<string, string>; definition?: string }) =>
      client.addGlossaryEntry(sessionId, projectId, payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: sectionPlanKeys.glossary(sessionId, projectId) })
    },
  })
}

export function useDeleteGlossaryEntry(sessionId: string, projectId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (entryId: string) => client.deleteGlossaryEntry(sessionId, projectId, entryId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: sectionPlanKeys.glossary(sessionId, projectId) })
    },
  })
}

// ============================================================ Batch Operations

export function useBatchRegenerateSections(sessionId: string, projectId: string) {
  const invalidate = useInvalidateSectionPlans(sessionId, projectId)
  return useMutation<BatchRegenerateResult, Error, boolean, unknown>({
    mutationFn: (force = false) => client.batchRegenerateSections(sessionId, projectId, force),
    onSuccess: (): void => { invalidate() },
  })
}

export function useCompileManuscript(
  sessionId: string | null,
  projectId: string | null,
  language?: string,
  includeUnapproved = false,
  enabled = true,
) {
  return useQuery({
    queryKey: [
      ...sectionPlanKeys.manuscript(sessionId ?? '', projectId ?? '', language ?? ''),
      includeUnapproved,
    ],
    queryFn: () => client.compileManuscript(sessionId as string, projectId as string, language, includeUnapproved),
    enabled: enabled && sessionId !== null && projectId !== null,
  })
}

// ============================================================ Quality Checks

export function useTerminologyCheck(sessionId: string | null, projectId: string | null) {
  return useQuery({
    queryKey: sectionPlanKeys.terminologyCheck(sessionId ?? '', projectId ?? ''),
    queryFn: () => client.checkTerminologyConsistency(sessionId as string, projectId as string),
    enabled: sessionId !== null && projectId !== null,
  })
}

export function useStyleCompliance(
  sessionId: string | null,
  projectId: string | null,
  sectionPlanId: string | null,
  versionId: string | null,
) {
  return useQuery({
    queryKey: ['style-compliance', sessionId, projectId, sectionPlanId, versionId] as const,
    queryFn: () =>
      client.checkStyleCompliance(
        sessionId as string,
        projectId as string,
        sectionPlanId as string,
        versionId as string,
      ),
    enabled: sessionId !== null && projectId !== null && sectionPlanId !== null,
  })
}

export function usePreGenerationCheck(
  sessionId: string | null,
  projectId: string | null,
  sectionName: string | null,
  question: string | null,
  requiredSources = 3,
  enabled = true,
) {
  return useQuery({
    queryKey: ['pre-generation-check', sessionId, projectId, sectionName, question, requiredSources] as const,
    queryFn: () =>
      client.preGenerationCheck(
        sessionId as string,
        projectId as string,
        sectionName as string,
        question as string,
        requiredSources,
      ),
    // По требованию: без явного запуска проверки запрос не уходит — иначе
    // она летела бы на каждый ввод вопроса.
    enabled:
      enabled &&
      sessionId !== null &&
      projectId !== null &&
      sectionName !== null &&
      question !== null,
  })
}

// ============================================================ Suggested plan from journal style

