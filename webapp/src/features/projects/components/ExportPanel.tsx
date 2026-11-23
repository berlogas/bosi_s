import { Group, Paper, Select, Button, Text } from '@mantine/core'
import {
  IconDownload,
  IconFileWord,
  IconFileCode,
  IconArchive,
} from '@tabler/icons-react'
import React, { useState } from 'react'
import { useExportProject } from '../queries'
import type { ExportFormat, ProjectOut } from '../../../api/types'

const EXPORT_FORMATS: {
  value: ExportFormat
  label: string
  hint: string
  icon: React.ReactNode
}[] = [
  {
    value: 'docx',
    label: 'Word (.docx)',
    hint: 'готовый файл для журнала',
    icon: <IconFileWord size={14} />,
  },
  {
    value: 'markdown',
    label: 'Markdown (.md)',
    hint: 'для репозитория или вики',
    icon: <IconFileCode size={14} />,
  },
  {
    value: 'zip',
    label: 'ZIP',
    hint: 'статья + библиография + исходники',
    icon: <IconArchive size={14} />,
  },
]

interface ExportPanelProps {
  sessionId: string
  project: ProjectOut
}

export function ExportPanel({ sessionId, project }: ExportPanelProps) {
  const exportProject = useExportProject(sessionId)
  const [format, setFormat] = useState<ExportFormat>('docx')
  const [message, setMessage] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const formatInfo = EXPORT_FORMATS.find((item) => item.value === format)

  const handleExport = () => {
    setMessage(null)
    setError(null)
    exportProject.mutate(
      { projectId: project.id, format },
      {
        onSuccess: ({ filename }) => setMessage(`Файл скачан: ${filename}`),
        onError: (cause) =>
          setError(
            cause instanceof Error ? cause.message : 'Не удалось выгрузить файл',
          ),
      },
    )
  }

  return (
    <Paper withBorder p="sm">
      <Group align="flex-end" gap="sm">
        <Select
          label="Выгрузка статьи"
          data={EXPORT_FORMATS.map((item) => ({
            value: item.value,
            label: item.label,
          }))}
          value={format}
          onChange={(value) => value && setFormat(value as ExportFormat)}
          allowDeselect={false}
          w={200}
        />
        <Button
          onClick={handleExport}
          loading={exportProject.isPending}
          leftSection={<IconDownload size={14} />}
        >
          Выгрузить
        </Button>
        <Text size="xs" c="dimmed">
          {formatInfo?.hint}
        </Text>
      </Group>
      {message && (
        <Text size="sm" c="success" role="status" mt={6}>
          {message}
        </Text>
      )}
      {error && (
        <Text size="sm" c="error" role="alert" mt={6}>
          {error}
        </Text>
      )}
    </Paper>
  )
}
