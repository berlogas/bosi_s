/**
 * Страница «База знаний» — глобальный корпус для чтения.
 *
 * Зачем она исследователю, который не может наполнять базу: поиск по базе
 * ссылается на источники, и без списка нельзя понять, есть ли нужный документ
 * вообще и кто его завёл. Наполняет базу администратор (раздел
 * «Администрирование» → «Глобальная база»), здесь только чтение, поэтому
 * кнопок загрузки и удаления на странице нет намеренно.
 *
 * Если пользователь — администратор, вверху есть ссылка в его раздел: тот же
 * список с возможностью наполнения, чтобы не искать его по меню.
 */

import { useDeferredValue } from 'react'
import {
  Alert,
  Badge,
  Button,
  Group,
  Select,
  Stack,
  Table,
  Text,
  TextInput,
} from '@mantine/core'
import { useDebouncedValue } from '@mantine/hooks'
import { useNavigate, useSearchParams } from 'react-router-dom'

import { categoryLabel } from '../../lib/format'
import { useAuth } from '../auth/authStore'
import { useKnowledgeDocuments, useKnowledgeStats } from './queries'
import { EmptyState } from '../../components/EmptyState'
import { PageHeader } from '../../components/PageHeader'
import { SkeletonList } from '../../components/SkeletonList'
import { StatusBadge } from '../../components/StatusBadge'

/** Категории глобальной базы: те же, что и в админском списке. */
const CATEGORIES = [
  'global_knowledge',
  'temp_literature',
  'supplementary',
  'notes',
] as const

const CATEGORY_OPTIONS = [
  { value: '', label: 'Все категории' },
  ...CATEGORIES.map((value) => ({ value, label: categoryLabel(value) })),
]

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} Б`
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} КБ`
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} МБ`
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(1)} ГБ`
}

export function KnowledgePage() {
  const user = useAuth((state) => state.user)
  const navigate = useNavigate()

  // Фильтры живут в URL (план Волны 2, п. 7): ссылка shareable, F5 ничего
  // не сбрасывает. Debounce остаётся — URL меняется сразу, запрос через 300 мс.
  const [searchParams, setSearchParams] = useSearchParams()
  const search = searchParams.get('q') ?? ''
  const category = searchParams.get('category') ?? ''

  const setFilter = (key: string, value: string) => {
    const next = new URLSearchParams(searchParams)
    if (value) next.set(key, value)
    else next.delete(key)
    setSearchParams(next, { replace: true })
  }

  const [debouncedSearch] = useDebouncedValue(search.trim(), 300)
  // useDeferredValue — отложенное отображение результатов, чтобы поле ввода
  // оставалось отзывчивым, пока рендерится/загружается список документов.
  const deferredSearch = useDeferredValue(search.trim())
  const documents = useKnowledgeDocuments(debouncedSearch, category || null)
  const stats = useKnowledgeStats()

  return (
    <Stack gap="md">
      <PageHeader
        title="База знаний"
        description="Общие документы, по которым ищет система. Наполняет базу администратор; здесь список для чтения."
        actions={
          user?.role === 'admin' ? (
            <Button variant="light" onClick={() => navigate('/admin/base')}>
              Управлять базой
            </Button>
          ) : undefined
        }
      />

      {stats.data && (
        <Group gap="xs">
          <Badge size="lg" variant="light">
            документов: {stats.data.total}
          </Badge>
          <Badge size="lg" variant="light" color="gray">
            объём: {formatBytes(stats.data.storage_bytes)}
          </Badge>
        </Group>
      )}

      <Group align="flex-end" gap="sm" wrap="nowrap">
        <TextInput
          label="Поиск по базе"
          placeholder="название, имя файла или метка"
          value={search}
          onChange={(event) => setFilter('q', event.currentTarget.value.trim())}
          style={{ flex: 1 }}
        />
        <Select
          label="Категория"
          data={CATEGORY_OPTIONS}
          value={category}
          onChange={(value) => setFilter('category', value ?? '')}
          allowDeselect={false}
          w={240}
        />
      </Group>

      {documents.isError && (
        <Alert color="error" role="alert" title="Не удалось загрузить список">
          {documents.error instanceof Error
            ? documents.error.message
            : 'Неизвестная ошибка запроса'}
        </Alert>
      )}

      {documents.isPending ? (
        <SkeletonList count={6} />
      ) : documents.data && documents.data.length === 0 ? (
        <EmptyState
          title={
            deferredSearch || category
              ? 'Ничего не нашлось.'
              : 'База пока пуста.'
          }
          description={
            deferredSearch || category
              ? 'Попробуйте другое слово или снимите фильтр.'
              : 'Наполняет её администратор.'
          }
          action={
            deferredSearch || category ? (
              <Button
                variant="subtle"
                size="xs"
                onClick={() => setSearchParams({}, { replace: true })}
              >
                Сбросить фильтр
              </Button>
            ) : undefined
          }
        />
      ) : null}

      {documents.data && documents.data.length > 0 && (
        <Table.ScrollContainer minWidth={640} type="native">
          <Table highlightOnHover>
            <Table.Thead>
              <Table.Tr>
                <Table.Th>Название</Table.Th>
                <Table.Th>Категория</Table.Th>
                <Table.Th>Статус</Table.Th>
                <Table.Th>Чанков</Table.Th>
                <Table.Th>Объём</Table.Th>
                <Table.Th>Метки</Table.Th>
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {documents.data.map((document) => (
                <Table.Tr key={document.id ?? document.dockey}>
                  <Table.Td>
                    <Text size="sm">{document.title || document.filename}</Text>
                    {document.citation && (
                      <Text size="xs" c="dimmed">
                        {document.citation}
                      </Text>
                    )}
                  </Table.Td>
                  <Table.Td>
                    <Text size="sm">{categoryLabel(document.category)}</Text>
                  </Table.Td>
                  <Table.Td>
                    <StatusBadge
                      kind="document"
                      status={document.status ?? undefined}
                    />
                  </Table.Td>
                  <Table.Td>{document.chunk_count}</Table.Td>
                  <Table.Td>{formatBytes(document.size_bytes)}</Table.Td>
                  <Table.Td>
                    <Text size="xs" c="dimmed">
                      {document.tags?.join(', ') || '—'}
                    </Text>
                  </Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </Table.ScrollContainer>
      )}
    </Stack>
  )
}
