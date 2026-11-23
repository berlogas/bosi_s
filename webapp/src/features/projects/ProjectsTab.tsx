/**
 * Вкладка «Проекты» — тонкий контейнер, оркестрирующий дочерние компоненты.
 * Рефакторинг: разбит на модули в features/projects/components и hooks.
 */

import {
  Stack,
  Group,
  Text,
  TextInput,
  Select,
  Button,
  Alert,
  UnstyledButton,
} from '@mantine/core'
import React, { useState, useEffect, useMemo, useCallback } from 'react'
import { useHotkeys } from '@mantine/hooks'
import type { DragEndEvent } from '@dnd-kit/core'
import { IconSearch, IconX, IconPlus } from '@tabler/icons-react'

import { ConfirmDeleteModal } from '../../components/ConfirmDeleteModal'

import { useBreadcrumbContext } from '../layout/BreadcrumbContext'
import {
  useProjects as useProjectsQuery,
  useCreateProject,
  usePatchProject,
  useDeleteProject,
  useReorderProjects,
  useJournalStyles,
} from './queries'

// Import extracted components

import { ProjectEditor } from './components/ProjectEditor'
import { ProjectList } from './components/ProjectList'
import { HowToPanel } from './components/HowToPanel'

interface ProjectsTabProps {
  sessionId: string
  readOnly: boolean
}

function lastActiveKey(sessionId: string): string {
  return `boasi_last_active_project_${sessionId}`
}

function getLastActiveProjectId(sessionId: string): string | null {
  try {
    const raw = localStorage.getItem(lastActiveKey(sessionId))
    return raw ?? null
  } catch {
    return null
  }
}

function setLastActiveProjectId(sessionId: string, projectId: string): void {
  try {
    localStorage.setItem(lastActiveKey(sessionId), projectId)
  } catch {
    /* storage may be unavailable in private mode */
  }
}

export function ProjectsTab({ sessionId, readOnly }: ProjectsTabProps) {
  const { setActiveProject, reset } = useBreadcrumbContext()

  // Queries
  const projectsQuery = useProjectsQuery(sessionId)
  const styles = useJournalStyles()
  const create = useCreateProject(sessionId)
  const patch = usePatchProject(sessionId)
  const remove = useDeleteProject(sessionId)
  const reorder = useReorderProjects(sessionId)

  // State
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [title, setTitle] = useState('')
  const [journal, setJournal] = useState('')
  const [createError, setCreateError] = useState<string | null>(null)
  const [deleteConfirmOpened, setDeleteConfirmOpened] = useState(false)
  const [deletePendingProjectId, setDeletePendingProjectId] = useState<string | null>(
    null,
  )
  const [deleteError, setDeleteError] = useState<string | null>(null)
  const [searchQuery, setSearchQuery] = useState('')
  const [actionError, setActionError] = useState<string | null>(null)

  // Derived state
  const list = useMemo(() => projectsQuery.data ?? [], [projectsQuery.data])
  const filteredList = useMemo(() => {
    if (!searchQuery.trim()) return list
    const query = searchQuery.toLowerCase()
    return list.filter(
      (project) =>
        project.title.toLowerCase().includes(query) ||
        ((project.sections as Array<{ name: string }> | undefined)?.some?.((s) =>
          s.name.toLowerCase().includes(query),
        ) ??
          false),
    )
  }, [list, searchQuery])

  const selected =
    projectsQuery.data?.find((project) => project.id === selectedId) ?? null

  // Effects
  // Persist the user's project choice so the next visit re-opens the same project.
  useEffect(() => {
    if (selectedId) {
      setLastActiveProjectId(sessionId, selectedId)
    }
  }, [selectedId, sessionId])

  // On first load, prefer the project the user worked on last (persisted in localStorage);
  // otherwise fall back to the most recently updated project.
  useEffect(() => {
    const data = projectsQuery.data ?? []
    if (selectedId === null && data && data.length > 0) {
      const persisted = getLastActiveProjectId(sessionId)
      if (persisted && data.some((p) => p.id === persisted)) {
        setSelectedId(persisted)
      } else {
        const byUpdated = [...data].sort(
          (a, b) =>
            new Date(b.updated_at ?? 0).getTime() -
            new Date(a.updated_at ?? 0).getTime(),
        )
        setSelectedId(byUpdated[0].id ?? null)
      }
    }
    if (selectedId !== null && (!data || !data.some((p) => p.id === selectedId))) {
      setSelectedId(data?.[0]?.id ?? null)
    }
  }, [projectsQuery.data, selectedId, sessionId])

  useEffect(() => {
    if (selected) {
      setActiveProject(selected.id, selected.title)
    } else {
      reset()
    }
  }, [selected, setActiveProject, reset])

  // Handlers
  const handleCreate = useCallback(() => {
    setCreateError(null)
    create.mutate(
      { title: title.trim(), journal: journal.trim(), language: 'ru' },
      {
        onSuccess: (project) => {
          setTitle('')
          setJournal('')
          setSelectedId(project.id)
        },
        onError: (cause) =>
          setCreateError(cause instanceof Error ? cause.message : 'Не удалось создать'),
      },
    )
  }, [title, journal, create])

  const handleStatusChange = useCallback(
    (projectId: string, status: string) => {
      setActionError(null)
      patch.mutate(
        { projectId, fields: { status } },
        {
          onError: (cause) =>
            setActionError(
              cause instanceof Error ? cause.message : 'Не удалось обновить статус',
            ),
        },
      )
    },
    [patch],
  )

  const handleDelete = useCallback((projectId: string) => {
    setDeletePendingProjectId(projectId)
    setDeleteConfirmOpened(true)
  }, [])

  const handleDragEnd = useCallback(
    (event: DragEndEvent) => {
      const { active, over } = event
      if (!over || active.id === over.id) return
      const oldIndex = filteredList.findIndex((p) => p.id === active.id)
      const newIndex = filteredList.findIndex((p) => p.id === over.id)
      if (oldIndex === -1 || newIndex === -1) return

      // Переставляем в списке и сохраняем новый порядок на сервере.
      const projectsToUpdate = filteredList.slice()
      const [moved] = projectsToUpdate.splice(oldIndex, 1)
      projectsToUpdate.splice(newIndex, 0, moved)
      projectsToUpdate.forEach((p, idx) => {
        if (p.order !== idx) {
          reorder.mutate({ projectId: p.id, order: idx })
        }
      })
    },
    [filteredList, reorder],
  )

  const handleFocusNewProject = useCallback(() => {
    const input = document.querySelector('input[label="Название"]') as HTMLInputElement
    input?.focus()
  }, [])

  // Hotkeys
  useHotkeys([
    ['ctrl+n', handleFocusNewProject],
    [
      'ctrl+s',
      () => {
        const saveBtn = document.querySelector(
          'button:has-text("Сохранить")',
        ) as HTMLButtonElement
        if (saveBtn && !saveBtn.disabled) saveBtn.click()
      },
    ],
    [
      'escape',
      () => {
        const closeBtn = document.querySelector(
          '[aria-label="Close"]',
        ) as HTMLButtonElement
        closeBtn?.click()
      },
    ],
  ])

  const journalChoices = useMemo(
    () => (styles.data ?? []).map((item) => ({ value: item.key, label: item.title })),
    [styles.data],
  )

  const chosenStyle = (styles.data ?? []).find((item) => item.key === journal)

  return (
    <Stack gap="sm">
      <Group justify="space-between" align="center">
        <Text fw={600}>Проекты статей</Text>
        <TextInput
          placeholder="Поиск по названию или разделу…"
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.currentTarget.value)}
          leftSection={<IconSearch size={14} />}
          rightSection={
            searchQuery && (
              <UnstyledButton
                onClick={() => setSearchQuery('')}
                aria-label="Очистить поиск"
              >
                <IconX size={14} />
              </UnstyledButton>
            )
          }
          style={{ maxWidth: 300 }}
        />
      </Group>
      {searchQuery && (
        <Text size="xs" c="dimmed">
          Показано {filteredList.length} из {list.length} проектов
        </Text>
      )}

      {/* форма создания */}
      <Group align="flex-end" gap="sm">
        <TextInput
          label="Название"
          value={title}
          onChange={(event) => setTitle(event.currentTarget.value)}
          disabled={readOnly}
          style={{ flex: 2 }}
        />
        <Select
          label="Стиль журнала"
          placeholder="Выберите стиль"
          data={journalChoices}
          value={journal || null}
          onChange={(value) => setJournal(value ?? '')}
          disabled={readOnly}
          searchable
          allowDeselect={false}
          style={{ flex: 2 }}
        />
        <Button
          onClick={handleCreate}
          disabled={readOnly || !title.trim()}
          loading={create.isPending}
          leftSection={<IconPlus size={14} />}
        >
          Создать
        </Button>
      </Group>

      {chosenStyle && (
        <Alert color="info" variant="light" p="xs">
          <Text size="sm">
            Стиль «{chosenStyle.title}»: {chosenStyle.summary}
          </Text>
          <Text size="xs" c="dimmed" mt="xs">
            Журналы: {chosenStyle.journals.join(', ')}
          </Text>
        </Alert>
      )}
      {createError && (
        <Alert color="error" role="alert">
          {createError}
        </Alert>
      )}
      {actionError && (
        <Alert color="error" role="alert">
          {actionError}
        </Alert>
      )}
      {projectsQuery.isError && (
        <Alert color="error" role="alert">
          {projectsQuery.error instanceof Error
            ? projectsQuery.error.message
            : 'Не удалось загрузить проекты'}
        </Alert>
      )}

      <HowToPanel hasProjects={list.length > 0} />

      {/* список проектов слева */}
      <ProjectList
        projects={list}
        filteredProjects={filteredList}
        selectedId={selectedId}
        readOnly={readOnly}
        onSelect={setSelectedId}
        onStatusChange={handleStatusChange}
        onDelete={handleDelete}
        onCreate={handleFocusNewProject}
        onReorder={handleDragEnd}
      />

      {selected ? (
        <ProjectEditor sessionId={sessionId} project={selected} readOnly={readOnly} />
      ) : null}

      {/* Подтверждение удаления проекта */}
      <ConfirmDeleteModal
        opened={deleteConfirmOpened}
        title="Удалить проект статьи"
        subject={deletePendingProjectId ? `Проект будет удалён безвозвратно.` : null}
        error={deleteError}
        loading={remove.isPending && remove.variables === deletePendingProjectId}
        onCancel={() => {
          setDeleteConfirmOpened(false)
          setDeletePendingProjectId(null)
          setDeleteError(null)
        }}
        onConfirm={() => {
          if (!deletePendingProjectId) return
          setDeleteError(null)
          remove.mutate(deletePendingProjectId, {
            onSuccess: () => {
              setSelectedId(null)
              setDeletePendingProjectId(null)
              setDeleteConfirmOpened(false)
              setDeleteError(null)
            },
            onError: (cause) =>
              setDeleteError(
                cause instanceof Error ? cause.message : 'Не удалось удалить',
              ),
          })
        }}
      />
    </Stack>
  )
}
