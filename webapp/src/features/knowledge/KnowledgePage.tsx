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

import {
  Alert,
  Badge,
  Button,
  Group,
  Paper,
  Select,
  Stack,
  Table,
  Text,
  TextInput,
  Title,
} from '@mantine/core'
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { categoryLabel } from '../../lib/format'
import { useAuth } from '../auth/authStore'
import { useKnowledgeDocuments, useKnowledgeStats } from './queries'

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

const STATUS_LABELS: Record<string, string> = {
  ready: 'готов',
  pending: 'в обработке',
  error: 'ошибка',
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} Б`
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} КБ`
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} МБ`
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(1)} ГБ`
}

export function KnowledgePage() {
  const user = useAuth((state) => state.user)
  const navigate = useNavigate()
  const [query, setQuery] = useState('')
  const [search, setSearch] = useState('')
  const [category, setCategory] = useState<string | null>(null)

  // Поиск по подстроке уходит на сервер: база может быть большой, а фильтра
  // на клиенте нет. Ввод разделён с отправкой, иначе каждый символ был бы
  // запросом; форма шлёт по Enter.
  const documents = useKnowledgeDocuments(search, category)
  const stats = useKnowledgeStats()

  return (
    <Stack gap="md">
      <Group justify="space-between" align="flex-start">
        <Stack gap={2}>
          <Title order={3}>База знаний</Title>
          <Text size="sm" c="dimmed">
            Общие документы, по которым ищет система. Наполняет базу администратор;
            здесь список для чтения.
          </Text>
        </Stack>
        {user?.role === 'admin' && (
          <Button variant="light" onClick={() => navigate('/admin')}>
            Управлять базой
          </Button>
        )}
      </Group>

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

      <form
        onSubmit={(event) => {
          event.preventDefault()
          setSearch(query.trim())
        }}
      >
        <Group align="flex-end" gap="sm" wrap="nowrap">
          <TextInput
            label="Поиск по базе"
            placeholder="название, имя файла или метка"
            value={query}
            onChange={(event) => setQuery(event.currentTarget.value)}
            style={{ flex: 1 }}
          />
          <Select
            label="Категория"
            data={CATEGORY_OPTIONS}
            value={category}
            onChange={setCategory}
            allowDeselect={false}
            w={240}
          />
          <Button type="submit" variant="default">
            Найти
          </Button>
        </Group>
      </form>

      {documents.isError && (
        <Alert color="red" role="alert" title="Не удалось загрузить список">
          {documents.error instanceof Error
            ? documents.error.message
            : 'Неизвестная ошибка запроса'}
        </Alert>
      )}

      {documents.data && documents.data.length === 0 && (
        <Paper withBorder p="md">
          <Text c="dimmed" size="sm">
            {search
              ? 'Ничего не нашлось. Попробуйте другое слово или снимите фильтр по категории.'
              : 'База пока пуста. Наполняет её администратор.'}
          </Text>
        </Paper>
      )}

      {documents.data && documents.data.length > 0 && (
        <Paper withBorder>
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
                    <Badge
                      size="sm"
                      color={
                        document.status === 'ready'
                          ? 'green'
                          : document.status === 'error'
                            ? 'red'
                            : 'yellow'
                      }
                    >
                      {STATUS_LABELS[document.status ?? ''] ?? document.status ?? '—'}
                    </Badge>
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
        </Paper>
      )}
    </Stack>
  )
}
