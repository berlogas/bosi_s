import { useCallback, useMemo, useState } from 'react'
import { Stack, TextInput, NumberInput, Button, Group, Badge, Checkbox, Table, Modal, Select, Text } from '@mantine/core'
import { showNotification } from '@mantine/notifications'
import { IconPlus, IconX, IconWand, IconGripVertical, IconRefresh } from '@tabler/icons-react'
import { DndContext, PointerSensor, KeyboardSensor, closestCenter, useSensor, useSensors, type DragEndEvent } from '@dnd-kit/core'
import { SortableContext, verticalListSortingStrategy, sortableKeyboardCoordinates, useSortable } from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import {
  useSectionPlans,
  useCreateSectionPlan,
  useUpdateSectionPlan,
  useDeleteSectionPlan,
  useBatchRegenerateSections,
} from '../hooks'
import { client } from '../../../api/client'
import type { SectionPlan, SectionKind } from '../../../api/types'

const KIND_LABELS: Record<string, string> = {
  standard: 'Стандартный',
  literature_review: 'Обзор литературы',
  data: 'Данные',
  discussion: 'Обсуждение',
  custom: 'Пользовательский',
}

const KIND_COLORS: Record<string, string> = {
  standard: 'blue',
  literature_review: 'green',
  data: 'orange',
  discussion: 'violet',
  custom: 'gray',
}

const STATUS_COLORS: Record<string, string> = {
  pending: 'gray',
  in_progress: 'blue',
  review: 'yellow',
  approved: 'green',
}

const STATUS_LABELS: Record<string, string> = {
  pending: 'Ожидает',
  in_progress: 'В работе',
  review: 'На ревью',
  approved: 'Утверждён',
}

const KIND_OPTIONS = Object.entries(KIND_LABELS).map(([value, label]) => ({ value, label }))

interface PlanDraft {
  id: string | null
  name: string
  kind: SectionKind
  order: number
  word_target: number
  required: boolean
}

const EMPTY_DRAFT: PlanDraft = {
  id: null,
  name: '',
  kind: 'standard',
  order: 1,
  word_target: 500,
  required: true,
}

export function SectionPlanEditor({ sessionId, projectId, readOnly, projectTargetJournal }: { sessionId: string; projectId: string; readOnly?: boolean; projectTargetJournal?: string }) {
  const { data: plans, isLoading } = useSectionPlans(sessionId, projectId)
  const createPlan = useCreateSectionPlan(sessionId, projectId)
  const updatePlan = useUpdateSectionPlan(sessionId, projectId)
  const deletePlan = useDeleteSectionPlan(sessionId, projectId)
  const regenerate = useBatchRegenerateSections(sessionId, projectId)

  const [draft, setDraft] = useState<PlanDraft | null>(null)

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 4 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  )

  const handleSuggestFromJournal = useCallback(async () => {
    if (!projectTargetJournal) {
      showNotification({ title: 'Ошибка', message: 'Не выбран стиль журнала', color: 'red' })
      return
    }

    try {
      const suggested = await client.getSuggestedSectionPlan(projectTargetJournal)

      if (!suggested || suggested.length === 0) {
        showNotification({ title: 'Информация', message: 'Для этого стиля журнала нет шаблонов разделов', color: 'blue' })
        return
      }

      for (const section of suggested) {
        await new Promise<void>((resolve, reject) => {
          createPlan.mutate({
            name: section.name,
            kind: section.kind,
            order: section.order,
            word_target: section.word_target,
            notes: section.notes,
            required: section.required,
            language: section.language,
            depends_on: section.depends_on,
          }, {
            onSuccess: () => resolve(),
            onError: reject,
          })
        })
      }

      showNotification({ title: 'Готово', message: `Добавлено разделов: ${suggested.length}`, color: 'green' })
    } catch (e) {
      showNotification({ title: 'Ошибка', message: e instanceof Error ? e.message : 'Неизвестная ошибка', color: 'red' })
    }
  }, [projectTargetJournal, createPlan])

  const handleCreate = () => {
    setDraft({ ...EMPTY_DRAFT, order: (plans?.length ?? 0) + 1 })
  }

  const handleEdit = (plan: SectionPlan) => {
    setDraft({
      id: plan.id,
      name: plan.name,
      kind: plan.kind,
      order: plan.order,
      word_target: plan.word_target,
      required: plan.required,
    })
  }

  const handleSubmit = () => {
    if (!draft) return
    const name = draft.name.trim()
    if (!name) {
      showNotification({ title: 'Ошибка', message: 'Название раздела не задано', color: 'red' })
      return
    }
    const payload = {
      name,
      kind: draft.kind,
      order: draft.order,
      word_target: draft.word_target,
      required: draft.required,
    }
    const options = {
      onSuccess: () => setDraft(null),
      onError: (cause: unknown) =>
        showNotification({
          title: 'Ошибка',
          message: cause instanceof Error ? cause.message : 'Не удалось сохранить',
          color: 'red',
        }),
    }
    if (draft.id) {
      updatePlan.mutate({ planId: draft.id, payload }, options)
    } else {
      createPlan.mutate(payload, options)
    }
  }

  // Перетаскивание строк меняет порядок разделов.
  const handleDragEnd = (event: DragEndEvent) => {
    const { active, over } = event
    if (!over || active.id === over.id) return
    const list = plans ?? []
    const from = list.findIndex((p) => p.id === active.id)
    const to = list.findIndex((p) => p.id === over.id)
    if (from === -1 || to === -1) return
    const next = [...list]
    const [moved] = next.splice(from, 1)
    next.splice(to, 0, moved)
    next.forEach((plan, index) => {
      if (plan.order !== index + 1) {
        updatePlan.mutate({ planId: plan.id, payload: { order: index + 1 } })
      }
    })
  }

  const planIds = useMemo(() => (plans ?? []).map((p) => p.id), [plans])

  if (isLoading) return <Text size="sm" c="dimmed">Загрузка плана…</Text>

  return (
    <Stack gap="md">
      <Group justify="space-between" align="center">
        <Text fw={600}>План разделов</Text>
        <Group gap="xs">
          <Button onClick={handleSuggestFromJournal} leftSection={<IconWand size={14} />} variant="filled" disabled={!projectTargetJournal}>
            Предложить по стилю журнала
          </Button>
          <Button onClick={handleCreate} leftSection={<IconPlus size={14} />} disabled={readOnly}>
            Добавить раздел
          </Button>
          <Button
            onClick={() => regenerate.mutate(false)}
            variant="subtle"
            leftSection={<IconRefresh size={14} />}
            disabled={readOnly}
            loading={regenerate.isPending}
          >
            Перегенерировать устаревшие
          </Button>
        </Group>
      </Group>

      <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={handleDragEnd}>
        <SortableContext items={planIds} strategy={verticalListSortingStrategy}>
          <Table highlightOnHover stickyHeader>
            <thead>
              <tr>
                <th style={{ width: 40 }}>⋮⋮</th>
                <th>Название / Тип</th>
                <th style={{ width: 100 }}>Порядок</th>
                <th style={{ width: 100 }}>Слов</th>
                <th style={{ width: 100 }}>Статус</th>
                <th style={{ width: 80 }}>Обязательный</th>
                <th style={{ width: 120, textAlign: 'right' }} />
              </tr>
            </thead>
            <tbody>
              {(plans ?? []).map((section) => (
                <SortablePlanRow
                  key={section.id}
                  plan={section}
                  readOnly={readOnly}
                  onEdit={handleEdit}
                  onDelete={(id) => deletePlan.mutate(id)}
                  onOrder={(order) => updatePlan.mutate({ planId: section.id, payload: { order } })}
                  onWordTarget={(wordTarget) =>
                    updatePlan.mutate({ planId: section.id, payload: { word_target: wordTarget } })
                  }
                  onRequired={(required) =>
                    updatePlan.mutate({ planId: section.id, payload: { required } })
                  }
                />
              ))}
            </tbody>
          </Table>
        </SortableContext>
      </DndContext>

      {(plans ?? []).length === 0 && (
        <Text size="sm" c="dimmed" ta="center" py="xl">
          План пуст. Добавьте разделы.
        </Text>
      )}

      <Modal
        opened={draft !== null}
        onClose={() => setDraft(null)}
        title={draft?.id ? 'Править раздел' : 'Добавить раздел'}
        centered
      >
        {draft && (
          <Stack gap="sm">
            <TextInput
              label="Название"
              value={draft.name}
              onChange={(e) => setDraft({ ...draft, name: e.currentTarget.value })}
              data-autofocus
            />
            <Select
              label="Тип"
              data={KIND_OPTIONS}
              value={draft.kind}
              onChange={(value) => setDraft({ ...draft, kind: (value ?? 'standard') as SectionKind })}
              allowDeselect={false}
            />
            <NumberInput
              label="Порядок"
              value={draft.order}
              min={1}
              onChange={(value) => setDraft({ ...draft, order: Number(value) || 1 })}
            />
            <NumberInput
              label="Слов"
              value={draft.word_target}
              min={0}
              onChange={(value) => setDraft({ ...draft, word_target: Number(value) || 0 })}
            />
            <Checkbox
              label="Обязательный раздел"
              checked={draft.required}
              onChange={(e) => setDraft({ ...draft, required: e.currentTarget.checked })}
            />
            <Group justify="flex-end">
              <Button variant="default" onClick={() => setDraft(null)} leftSection={<IconX size={14} />}>
                Отмена
              </Button>
              <Button onClick={handleSubmit}>Сохранить</Button>
            </Group>
          </Stack>
        )}
      </Modal>
    </Stack>
  )
}

/** Строка плана: перетаскивается за ручку, значения меняются на месте. */
function SortablePlanRow({
  plan,
  readOnly,
  onEdit,
  onDelete,
  onOrder,
  onWordTarget,
  onRequired,
}: {
  plan: SectionPlan
  readOnly?: boolean
  onEdit: (plan: SectionPlan) => void
  onDelete: (id: string) => void
  onOrder: (order: number) => void
  onWordTarget: (words: number) => void
  onRequired: (required: boolean) => void
}) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
    id: plan.id,
    disabled: readOnly,
  })

  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.5 : 1,
  }

  return (
    <tr ref={setNodeRef} style={style}>
      <td style={{ width: 40, textAlign: 'center' }}>
        <span
          {...attributes}
          {...listeners}
          aria-label={`Перетащить раздел ${plan.name}`}
          style={{
            cursor: readOnly ? 'default' : 'grab',
            color: 'var(--mantine-color-gray-5)',
            display: 'inline-block',
          }}
        >
          <IconGripVertical size={14} />
        </span>
      </td>
      <td>
        <Group gap="xs" align="center">
          <Badge variant="light" color={KIND_COLORS[plan.kind] || 'gray'} size="xs">
            {KIND_LABELS[plan.kind] || plan.kind}
          </Badge>
          <Text fw={500}>{plan.name}</Text>
        </Group>
      </td>
      <td style={{ width: 100 }}>
        <NumberInput
          value={plan.order}
          min={1}
          step={1}
          size="xs"
          style={{ width: 80 }}
          readOnly={readOnly}
          onChange={(v) => v !== undefined && onOrder(Number(v) || 1)}
        />
      </td>
      <td style={{ width: 100 }}>
        <TextInput
          type="number"
          value={String(plan.word_target)}
          size="xs"
          style={{ width: 80 }}
          readOnly={readOnly}
          onChange={(e) => onWordTarget(parseInt(e.currentTarget.value) || 0)}
        />
      </td>
      <td style={{ width: 100 }}>
        <Badge variant="light" color={STATUS_COLORS[plan.status] || 'gray'} size="xs">
          {STATUS_LABELS[plan.status] || plan.status}
        </Badge>
      </td>
      <td style={{ width: 80 }}>
        <Checkbox
          checked={plan.required}
          size="sm"
          disabled={readOnly}
          onChange={(e) => onRequired(e.currentTarget.checked)}
        />
      </td>
      <td style={{ width: 120, textAlign: 'right' }}>
        {!readOnly && (
          <Group gap="xs">
            <Button variant="subtle" size="xs" onClick={() => onEdit(plan)}>
              Править
            </Button>
            <Button variant="subtle" color="red" size="xs" onClick={() => { if (window.confirm('Удалить?')) onDelete(plan.id) }}>
              Удалить
            </Button>
          </Group>
        )}
      </td>
    </tr>
  )
}
