import { Group, Select, Text } from '@mantine/core'
import React from 'react'
import { useSessionStyleGuideDocuments } from '../../documents/queries'
import { useSetProjectStyleGuide } from '../queries'
import { notifications } from '@mantine/notifications'

interface StyleGuideSelectorProps {
  sessionId: string
  project: { id: string; style_guide_document_id?: string | null }
  readOnly?: boolean
}

export function StyleGuideSelector({ sessionId, project, readOnly = false }: StyleGuideSelectorProps) {
  const styleGuideDocs = useSessionStyleGuideDocuments(sessionId)
  const setStyleGuide = useSetProjectStyleGuide(sessionId)

  const styleGuideOptions = (styleGuideDocs.data ?? []).map((doc) => ({
    value: doc.id,
    label: doc.title ?? doc.docname ?? doc.dockey,
  }))

  const handleChange = (documentId: string | null) => {
    setStyleGuide.mutate(
      { projectId: project.id, documentId },
      {
        onError: (cause) =>
          notifications.show({
            title: 'Ошибка',
            message: cause instanceof Error ? cause.message : 'Не удалось установить style_guide',
            color: 'error',
          }),
      },
    )
  }

  return (
    <Group gap="sm">
      <Select
        label="Правила оформления"
        placeholder="Не выбран"
        data={styleGuideOptions}
        value={project.style_guide_document_id ?? null}
        onChange={(value) => handleChange(value ?? null)}
        allowDeselect
        disabled={readOnly || styleGuideOptions.length === 0}
        style={{ flex: 1, minWidth: 200 }}
      />
      {styleGuideOptions.length === 0 && (
        <Text size="sm" c="dimmed">
          Нет документов категории "Правила оформления журнала". Добавьте документ в разделе Документы.
        </Text>
      )}
    </Group>
  )
}