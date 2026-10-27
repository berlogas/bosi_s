/**
 * Хук для страницы «Глобальная база»: документы, сортировка,
 * пагинация, фильтры, удаление документа.
 * URL-параметры имеют префикс `docs_`.
 */

import { useCallback, useMemo } from 'react'
import { useSearchParams } from 'react-router-dom'

import {
  useAdminDocuments,
  useAdminAddPath,
  useAdminUpload,
  useAdminDeleteDocument,
  useAdminReindex,
} from '../../queries'

const PAGE_SIZE_OPTIONS = [10, 25, 50, 100]
const PARAM_PREFIX = 'docs_'

function getParam(searchParams: URLSearchParams, key: string): string | null {
  return searchParams.get(`${PARAM_PREFIX}${key}`)
}

function setParam(searchParams: URLSearchParams, key: string, value: string | null) {
  const fullKey = `${PARAM_PREFIX}${key}`
  if (value) searchParams.set(fullKey, value)
  else searchParams.delete(fullKey)
}

export function useDocumentsPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const documentsQuery = useAdminDocuments()
  const addPath = useAdminAddPath()
  const upload = useAdminUpload()
  const remove = useAdminDeleteDocument()
  const reindex = useAdminReindex()

  // --- URL state ---
  const pageIndex = Math.max(0, Number(getParam(searchParams, 'page')) - 1 || 0)
  const pageSize = Number(getParam(searchParams, 'size')) || 25
  const sorting = useMemo(() => {
    const s = getParam(searchParams, 'sort')
    return s ? JSON.parse(s) : [{ id: 'title', desc: false }]
  }, [searchParams])
  const filters = useMemo(() => {
    const f = getParam(searchParams, 'filters')
    return f ? JSON.parse(f) : []
  }, [searchParams])

  // --- Синхронизация URL ---
  const setPagination = useCallback(
    (next: { pageIndex: number; pageSize: number; pageCount: number }) => {
      const params = new URLSearchParams(searchParams)
      setParam(params, 'page', String(next.pageIndex + 1))
      setParam(params, 'size', String(next.pageSize))
      setSearchParams(params, { replace: true })
    },
    [searchParams, setSearchParams]
  )

  const setSorting = useCallback(
    (next: { id: string; desc: boolean }[]) => {
      const params = new URLSearchParams(searchParams)
      setParam(params, 'page', '1')
      setParam(params, 'sort', JSON.stringify(next))
      setSearchParams(params, { replace: true })
    },
    [searchParams, setSearchParams]
  )

  const setFilters = useCallback(
    (next: { id: string; value: unknown }[]) => {
      const params = new URLSearchParams(searchParams)
      setParam(params, 'page', '1')
      setParam(params, 'filters', JSON.stringify(next))
      setSearchParams(params, { replace: true })
    },
    [searchParams, setSearchParams]
  )

  // --- Колонки таблицы ---
  const columns = useMemo(() => [
    { id: 'title', accessorKey: 'title', header: 'Название' },
    { id: 'filename', accessorKey: 'filename', header: 'Файл' },
    { id: 'category', accessorKey: 'category', header: 'Категория' },
    { id: 'status', accessorKey: 'status', header: 'Статус' },
    { id: 'size_bytes', accessorKey: 'size_bytes', header: 'Размер (КБ)' },
    { id: 'chunk_count', accessorKey: 'chunk_count', header: 'Чанков' },
    { id: 'tags', accessorKey: 'tags', header: 'Теги' },
  ], [])

  // --- Данные ---
  const data = documentsQuery.data ?? []
  const isLoading = documentsQuery.isLoading
  const isError = documentsQuery.isError
  const error = documentsQuery.error

  // --- Пагинация ---
  const pageCount = Math.max(1, Math.ceil(data.length / pageSize))

  // --- Мутации ---
  const handleAddPath = useCallback(
    (path: string) => {
      addPath.mutate(path.trim())
    },
    [addPath]
  )

  const handleUpload = useCallback(
    (files: File[], tags: string, onProgress?: (percent: number) => void) => {
      upload.mutate({ files, tags, onProgress })
    },
    [upload]
  )

  const handleDelete = useCallback(
    (documentId: string) => {
      remove.mutate(documentId as string)
    },
    [remove]
  )

  const handleReindex = useCallback(() => {
    reindex.mutate(undefined)
  }, [reindex])

  return {
    data,
    isLoading,
    isError,
    error,
    columns,
    pagination: { pageIndex, pageSize, pageCount },
    sorting,
    filters,
    setPagination,
    setSorting,
    setFilters,
    handleAddPath,
    handleUpload,
    handleDelete,
    handleReindex,
    PAGE_SIZE_OPTIONS,
    addPath,
    upload,
    remove,
    reindex,
  }
}