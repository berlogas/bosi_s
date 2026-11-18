/**
 * Панель документов проекта с поиском, виртуализацией, inline-сменой роли
 * и превью в Drawer.
 */

import { Badge, Button, Drawer, Divider, Group, Paper, Select, Stack, Table, Text, TextInput, UnstyledButton } from '@mantine/core'
import { useMemo, useRef, useState } from 'react'
import { useVirtualizer } from '@tanstack/react-virtual'
import { motion, AnimatePresence } from 'framer-motion'
import {
  IconFile,
  IconFileTypePdf,
  IconFileTypeCsv,
  IconFileText,
  IconFileTypeTxt,
  IconFileCode as IconFileCode2,
  IconFileWord,
  IconSearch,
  IconX,
  IconTrash,
  IconEdit,
  IconFilePlus,
} from '@tabler/icons-react'
import { MarkdownText } from '../../components/MarkdownText'
import { docRoleLabel, docRoleOptions, DOC_ROLES } from '../../lib/projectOptions'
import type { DocumentOut } from '../../api/types'
import {
  useBindDocument,
  useProjectDocuments,
  useUnbindDocument,
} from './queries'
import { useSessionDocuments } from '../documents/queries'

interface ProjectDocumentsPanelProps {
  sessionId: string
  projectId: string
  readOnly: boolean
}

function getDocumentIcon(mime?: string | null, filename?: string | null) {
  if (!mime && !filename) return <IconFile size={16} />
  const mimeType = mime ?? ''
  const ext = filename?.split('.').pop()?.toLowerCase() ?? ''

  if (mimeType.includes('pdf') || ext === 'pdf')
    return <IconFileTypePdf size={16} color="var(--mantine-color-red-filled)" />
  if (mimeType.includes('csv') || ext === 'csv')
    return <IconFileTypeCsv size={16} color="var(--mantine-color-green-filled)" />
  if (mimeType.includes('markdown') || ext === 'md')
    return <IconFileText size={16} color="var(--mantine-color-blue-filled)" />
  if (mimeType.includes('text') || ext === 'txt')
    return <IconFileTypeTxt size={16} color="var(--mantine-color-gray-filled)" />
  if (mimeType.includes('json') || ext === 'json')
    return <IconFileCode2 size={16} color="var(--mantine-color-yellow-filled)" />
  if (mimeType.includes('word') || ext === 'docx' || ext === 'doc')
    return <IconFileWord size={16} color="var(--mantine-color-blue-filled)" />

  return <IconFile size={16} />
}

function renderPreviewContent(doc: DocumentOut) {
  const mime = doc.mime ?? ''
  const filename = doc.filename ?? ''

  if (mime.includes('pdf') || filename.endsWith('.pdf')) {
    return (
      <iframe
        src={doc.url ?? `/api/documents/${doc.id}/content`}
        style={{ width: '100%', height: '100%', border: 'none' }}
        title={doc.title ?? doc.dockey}
      />
    )
  }

  if (mime.includes('csv') || filename.endsWith('.csv')) {
    return (
      <div style={{ padding: 'var(--mantine-spacing-md)' }}>
        <Text size="sm" c="dimmed" mb="sm">
          CSV превью (первые 100 строк). Полный файл доступен по ссылке.
        </Text>
        <Table>
          <thead>
            <tr>
              <th>Колонка 1</th>
              <th>Колонка 2</th>
              <th>Колонка 3</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td colSpan={3} style={{ textAlign: 'center', color: 'dimmed' }}>
                Загрузка CSV...
              </td>
            </tr>
          </tbody>
        </Table>
      </div>
    )
  }

  // Markdown, текст, код - показываем как MarkdownText
  if (
    mime.includes('text') ||
    mime.includes('markdown') ||
    filename.match(/\.(md|txt|py|js|ts|json|yaml|yml)$/i)
  ) {
    return (
      <div style={{ padding: 'var(--mantine-spacing-md)', maxHeight: 400, overflow: 'auto' }}>
        <MarkdownText
          text={
            `**${doc.title ?? doc.dockey}**\n\n` +
            (doc.citation ? `*Источник: ${doc.citation}*\n\n` : '') +
            (doc.content_hash ? `\`${doc.content_hash}\`\n\n` : '') +
            `Размер: ${doc.size_bytes} байт\n` +
            `Страниц: ${doc.pages ?? '—'}\n` +
            `Чанков: ${doc.chunk_count}`
          }
        />
      </div>
    )
  }

  // Default - info card
  return (
    <div style={{ padding: 'var(--mantine-spacing-md)' }}>
      <Stack gap="xs">
        <Group>
          {getDocumentIcon(doc.mime, doc.filename)}
          <Text fw={500}>{doc.title ?? doc.dockey}</Text>
        </Group>
        {doc.citation && (
          <Text size="sm" c="dimmed">
            Источник: {doc.citation}
          </Text>
        )}
        <Text size="sm" c="dimmed">
          MIME: {doc.mime ?? '—'} | Размер: {doc.size_bytes} байт
        </Text>
        <Text size="sm" c="dimmed">
          Страниц: {doc.pages ?? '—'} | Чанков: {doc.chunk_count}
        </Text>
        {doc.tags?.length && (
          <Group gap="xs">
            {doc.tags.map((tag) => (
              <Badge key={tag} variant="light" size="xs">
                {tag}
              </Badge>
            ))}
          </Group>
        )}
      </Stack>
    </div>
  )
}

// Отдельный компонент для строки свободного документа
interface FreeDocumentRowProps {
  document: DocumentOut
  onClick: (doc: DocumentOut) => void
  onBind: (docId: string, role: string) => void
  readOnly: boolean
  bindPending: boolean
  chosen: string | null
  role: string
}

function FreeDocumentRow({
  document,
  onClick,
  onBind,
  readOnly,
  bindPending,
  chosen,
  role,
}: FreeDocumentRowProps) {
  const isChosen = chosen === document.id

  return (
    <Paper
      withBorder={false}
      p="xs"
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 'var(--mantine-spacing-sm)',
        cursor: 'pointer',
        borderBottom: '1px solid var(--mantine-color-default-border)',
        background: isChosen ? 'var(--mantine-color-primary-light)' : 'transparent',
        transition: 'background 0.15s',
      }}
      onClick={() => onClick(document)}
    >
      {getDocumentIcon(document.mime, document.filename)}
      <Text
        size="sm"
        style={{ flex: 1, minWidth: 0, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}
      >
        {document.title ?? document.docname ?? document.dockey}
      </Text>
      {document.category && <Badge variant="light" size="xs">{document.category}</Badge>}
      {isChosen ? (
        <Select
          data={docRoleOptions(DOC_ROLES)}
          value={role}
          onChange={(value) => value && onBind(document.id, value)}
          autoFocus
          disabled={readOnly}
          allowDeselect={false}
          w={160}
          size="sm"
        />
      ) : (
        <Button
          size="compact-xs"
          variant="subtle"
          disabled={readOnly || bindPending}
          loading={bindPending && isChosen}
          onClick={(e) => {
            e.stopPropagation()
            onBind(document.id, 'reference')
          }}
        >
          Привязать
        </Button>
      )}
    </Paper>
  )
}

export function ProjectDocumentsPanel({
  sessionId,
  projectId,
  readOnly,
}: ProjectDocumentsPanelProps) {
  const bound = useProjectDocuments(sessionId, projectId)
  const all = useSessionDocuments(sessionId)
  const bind = useBindDocument(sessionId, projectId)
  const unbind = useUnbindDocument(sessionId, projectId)
  const [chosen, setChosen] = useState<string | null>(null)
  const [role, setRole] = useState<string>('reference')
  const [docError, setDocError] = useState<string | null>(null)
  const [searchQuery, setSearchQuery] = useState('')
  const [previewDoc, setPreviewDoc] = useState<DocumentOut | null>(null)
  const [previewOpen, setPreviewOpen] = useState(false)
  const [editingRole, setEditingRole] = useState<string | null>(null)

  const boundIds = useMemo(
    () => new Set((bound.data ?? []).map((item) => item.document.id ?? '')),
    [bound.data],
  )
  const free = useMemo(() => {
    return (all.data ?? []).filter(
      (document) => document.id && !boundIds.has(document.id),
    )
  }, [all.data, boundIds])

  const filteredFree = useMemo(() => {
    if (!searchQuery.trim()) return free
    const query = searchQuery.toLowerCase()
    return free.filter(
      (doc) =>
        (doc.title ?? '').toLowerCase().includes(query) ||
        (doc.docname ?? '').toLowerCase().includes(query) ||
        (doc.dockey ?? '').toLowerCase().includes(query),
    )
  }, [free, searchQuery])

  const boundItems = bound.data ?? []

  // Виртуализация для списка свободных документов при >50
  const freeListRef = useRef<HTMLDivElement>(null)
  const freeVirtualizer = useVirtualizer({
    count: filteredFree.length,
    getScrollElement: () => freeListRef.current,
    estimateSize: () => 50,
    overscan: 5,
  })

  function handleRoleChange(documentId: string, newRole: string) {
    // Сначала отвязываем, потом привязываем с новой ролью
    unbind.mutate(documentId, {
      onSuccess: () => {
        bind.mutate({ documentId, role: newRole }, {
          onError: (cause) =>
            setDocError(cause instanceof Error ? cause.message : 'Не удалось сменить роль'),
        })
      },
      onError: (cause) =>
        setDocError(cause instanceof Error ? cause.message : 'Не удалось отвязать для смены роли'),
    })
    setEditingRole(null)
  }

  function openPreview(doc: DocumentOut) {
    setPreviewDoc(doc)
    setPreviewOpen(true)
  }

  function closePreview() {
    setPreviewOpen(false)
    setPreviewDoc(null)
  }

  return (
    <Stack gap="xs">
      <Group justify="space-between" align="center">
        <Text size="sm" fw={600}>
          Документы проекта
        </Text>
        <Badge size="xs" variant="light">
          Привязано: {boundItems.length} | Свободно: {filteredFree.length}
        </Badge>
      </Group>

      {docError && (
        <div role="alert">
          <Text size="sm" c="error">{docError}</Text>
        </div>
      )}

      {/* Привязанные документы с inline сменой роли */}
      {boundItems.length > 0 && (
        <Stack gap="xs" mb="xs">
          <Text size="xs" c="dimmed" fw={500}>
            Привязанные к проекту
          </Text>
          {(boundItems as Array<{ document: DocumentOut; role: string }>).map((item) => (
            <motion.div
              key={item.document.id}
              initial={{ opacity: 0, y: -10 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.2 }}
            >
              <Paper
                withBorder
                p="xs"
                style={{ display: 'flex', alignItems: 'center', gap: 'var(--mantine-spacing-sm)' }}
              >
                {getDocumentIcon(item.document.mime, item.document.filename)}
                <Text size="sm" style={{ flex: 1, minWidth: 0 }}>
                  {item.document.title ?? item.document.dockey}
                </Text>
                {editingRole === item.document.id ? (
                  <Select
                    data={docRoleOptions(DOC_ROLES)}
                    value={item.role}
                    onChange={(value) => value && handleRoleChange(item.document.id, value)}
                    onBlur={() => setEditingRole(null)}
                    autoFocus
                    disabled={readOnly}
                    allowDeselect={false}
                    w={180}
                    size="sm"
                  />
                ) : (
                  <Group gap="xs">
                    <Badge
                      variant="light"
                      size="xs"
                      onClick={() => setEditingRole(item.document.id)}
                      style={{ cursor: readOnly ? 'default' : 'pointer' }}
                    >
                      {docRoleLabel(item.role)}
                      {!readOnly && <IconEdit size={10} style={{ marginLeft: 4 }} />}
                    </Badge>
                    <Button
                      size="compact-xs"
                      color="error"
                      variant="subtle"
                      disabled={readOnly}
                      loading={unbind.isPending && unbind.variables === item.document.id}
                      onClick={() =>
                        unbind.mutate(item.document.id as string, {
                          onError: (cause) =>
                            setDocError(
                              cause instanceof Error ? cause.message : 'Не удалось отвязать',
                            ),
                        })
                      }
                      aria-label={`Отвязать ${item.document.title ?? item.document.dockey}`}
                    >
                      <IconTrash size={12} />
                    </Button>
                  </Group>
                )}
              </Paper>
            </motion.div>
          ))}
        </Stack>
      )}

      {/* Свободные документы с поиском и виртуализацией */}
      {free.length > 0 && (
        <Stack gap="xs">
          <Group gap="sm" align="center">
            <TextInput
              placeholder="Поиск среди свободных документов…"
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
              style={{ width: 300 }}
            />
            <Text size="xs" c="dimmed">
              {filteredFree.length} из {free.length}
            </Text>
          </Group>

          <div
            ref={freeListRef}
            style={{
              height: filteredFree.length > 50 ? 300 : 'auto',
              maxHeight: 300,
              overflow: filteredFree.length > 50 ? 'auto' : 'visible',
              border: '1px solid var(--mantine-color-default-border)',
              borderRadius: 'var(--mantine-radius-sm)',
              background: 'var(--mantine-color-body)',
            }}
          >
            {filteredFree.length > 50 ? (
              <div style={{ height: freeVirtualizer.getTotalSize(), position: 'relative' }}>
                {freeVirtualizer.getVirtualItems().map((virtualRow) => (
                  <motion.div
                    key={filteredFree[virtualRow.index].id}
                    style={{
                      position: 'absolute',
                      top: 0,
                      left: 0,
                      right: 0,
                      height: virtualRow.size,
                      transform: `translateY(${virtualRow.start}px)`,
                    }}
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1 }}
                  >
                    <FreeDocumentRow
                      document={filteredFree[virtualRow.index]}
                      onClick={openPreview}
                      onBind={(docId, r) => {
                        setChosen(docId)
                        setRole(r)
                        bind.mutate({ documentId: docId, role: r }, {
                          onSuccess: () => setChosen(null),
                          onError: (cause) =>
                            setDocError(cause instanceof Error ? cause.message : 'Не удалось привязать'),
                        })
                      }}
                      readOnly={readOnly}
                      bindPending={bind.isPending}
                      chosen={chosen}
                      role={role}
                    />
                  </motion.div>
                ))}
              </div>
            ) : (
              <Stack gap={0}>
                {filteredFree.map((doc) => (
                  <FreeDocumentRow
                    key={doc.id}
                    document={doc}
                    onClick={openPreview}
                    onBind={(docId, r) => {
                      setChosen(docId)
                      setRole(r)
                      bind.mutate({ documentId: docId, role: r }, {
                        onSuccess: () => setChosen(null),
                        onError: (cause) =>
                          setDocError(cause instanceof Error ? cause.message : 'Не удалось привязать'),
                      })
                    }}
                    readOnly={readOnly}
                    bindPending={bind.isPending}
                    chosen={chosen}
                    role={role}
                  />
                ))}
              </Stack>
            )}
          </div>

          {filteredFree.length === 0 && searchQuery && (
            <Text size="sm" c="dimmed" ta="center" py="md">
              Документы не найдены
            </Text>
          )}
        </Stack>
      )}

      {boundItems.length === 0 && free.length === 0 && (
        <Paper withBorder p="md" style={{ textAlign: 'center' }}>
          <Stack align="center" gap="xs">
            <IconFilePlus size={48} style={{ color: 'var(--mantine-color-primary-filled)' }} />
            <Text fw={500}>Документов нет</Text>
            <Text size="sm" c="dimmed">
              Добавьте документы в разделе «Документы», чтобы привязать их к проекту.
            </Text>
          </Stack>
        </Paper>
      )}

      <Divider />

      {/* Preview Drawer */}
      <Drawer
        opened={previewOpen}
        onClose={closePreview}
        title={previewDoc?.title ?? previewDoc?.dockey ?? 'Превью документа'}
        size="700px"
        withCloseButton
      >
        <AnimatePresence mode="wait">
          {previewDoc && (
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.2 }}
              style={{ height: '100%', display: 'flex', flexDirection: 'column' }}
            >
              {renderPreviewContent(previewDoc)}
            </motion.div>
          )}
        </AnimatePresence>
      </Drawer>
    </Stack>
  )
}