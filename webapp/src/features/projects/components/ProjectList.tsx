import { Stack } from '@mantine/core'
import { DndContext, closestCenter, type DragEndEvent } from '@dnd-kit/core'
import { SortableContext, verticalListSortingStrategy } from '@dnd-kit/sortable'
import { motion, AnimatePresence } from 'framer-motion'
import React, { useMemo } from 'react'
import { SortableProjectItem } from './SortableProjectItem'
import { EmptyProjectsState } from './EmptyState'
import type { ProjectOut } from '../../../api/types'

interface ProjectListProps {
  projects: ProjectOut[]
  filteredProjects: ProjectOut[]
  selectedId: string | null
  readOnly: boolean
  onSelect: (id: string) => void
  onStatusChange: (projectId: string, status: string) => void
  onDelete: (projectId: string) => void
  onCreate: () => void
  onReorder: (event: DragEndEvent) => void
}

export function ProjectList({
  projects,
  filteredProjects,
  selectedId,
  readOnly,
  onSelect,
  onStatusChange,
  onDelete,
  onCreate,
  onReorder,
}: ProjectListProps) {
  const items = useMemo(() => filteredProjects.map((p) => p.id), [filteredProjects])

  return (
    <Stack gap="xs" style={{ overflowY: 'auto', maxHeight: 'calc(100vh - 320px)', minHeight: 0 }}>
      {projects.length === 0 && (
        <EmptyProjectsState onCreate={onCreate} />
      )}
      {/* DndContext обязателен: без него SortableContext не даёт перетаскивания. */}
      <DndContext collisionDetection={closestCenter} onDragEnd={onReorder}>
        <SortableContext items={items} strategy={verticalListSortingStrategy}>
          <AnimatePresence mode="popLayout">
          {filteredProjects.map((project) => (
            <motion.div
              key={project.id}
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -10 }}
              transition={{ duration: 0.2 }}
            >
              <SortableProjectItem
                project={project}
                isActive={project.id === selectedId}
                onSelect={() => onSelect(project.id)}
                onStatusChange={(status) => onStatusChange(project.id, status)}
                onDelete={() => onDelete(project.id)}
                readOnly={readOnly}
              />
            </motion.div>
          ))}
          </AnimatePresence>
        </SortableContext>
      </DndContext>
    </Stack>
  )
}