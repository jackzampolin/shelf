import { useState, useMemo } from 'react'
import { createFileRoute, Link } from '@tanstack/react-router'
import { useQuery } from '@tanstack/react-query'
import { client, unwrap } from '@/api/client'

export const Route = createFileRoute('/books/$bookId/pages-table')({
  component: PagesTablePage,
})

type SortField = 'page_num' | 'page_number_label' | 'content_type' | 'running_header'
type SortDirection = 'asc' | 'desc'

function PagesTablePage() {
  const { bookId } = Route.useParams()
  const [sortField, setSortField] = useState<SortField>('page_num')
  const [sortDirection, setSortDirection] = useState<SortDirection>('asc')
  const [filter, setFilter] = useState('')
  const [contentTypeFilter, setContentTypeFilter] = useState<string>('')
  const [showChapterStartsOnly, setShowChapterStartsOnly] = useState(false)

  const { data: book } = useQuery({
    queryKey: ['books', bookId],
    queryFn: async () =>
      unwrap(
        await client.GET('/api/books/{id}', {
          params: { path: { id: bookId } },
        })
      ),
  })

  const { data: pagesData, isLoading, error } = useQuery({
    queryKey: ['books', bookId, 'pages'],
    queryFn: async () =>
      unwrap(
        await client.GET('/api/books/{book_id}/pages', {
          params: { path: { book_id: bookId } },
        })
      ),
    refetchInterval: 10000,
  })

  const pages = pagesData?.pages || []

  // Get unique content types for filter dropdown
  const contentTypes = useMemo(() => {
    const types = new Set<string>()
    pages.forEach((p) => {
      if (p.content_type) types.add(p.content_type)
    })
    return Array.from(types).sort()
  }, [pages])

  // Filter and sort pages
  const filteredPages = useMemo(() => {
    let result = [...pages]

    // Text filter
    if (filter) {
      const lowerFilter = filter.toLowerCase()
      result = result.filter(
        (p) =>
          (p.page_num?.toString() || '').includes(lowerFilter) ||
          p.page_number_label?.toLowerCase().includes(lowerFilter) ||
          p.running_header?.toLowerCase().includes(lowerFilter) ||
          p.chapter_title?.toLowerCase().includes(lowerFilter) ||
          p.chapter_number?.toLowerCase().includes(lowerFilter)
      )
    }

    // Content type filter
    if (contentTypeFilter) {
      result = result.filter((p) => p.content_type === contentTypeFilter)
    }

    // Chapter starts filter
    if (showChapterStartsOnly) {
      result = result.filter((p) => p.is_chapter_start)
    }

    // Sort
    result.sort((a, b) => {
      let aVal: string | number = ''
      let bVal: string | number = ''

      switch (sortField) {
        case 'page_num':
          aVal = a.page_num ?? 0
          bVal = b.page_num ?? 0
          break
        case 'page_number_label':
          aVal = a.page_number_label || ''
          bVal = b.page_number_label || ''
          break
        case 'content_type':
          aVal = a.content_type || ''
          bVal = b.content_type || ''
          break
        case 'running_header':
          aVal = a.running_header || ''
          bVal = b.running_header || ''
          break
      }

      if (typeof aVal === 'number' && typeof bVal === 'number') {
        return sortDirection === 'asc' ? aVal - bVal : bVal - aVal
      }

      const cmp = String(aVal).localeCompare(String(bVal))
      return sortDirection === 'asc' ? cmp : -cmp
    })

    return result
  }, [pages, filter, contentTypeFilter, showChapterStartsOnly, sortField, sortDirection])

  const handleSort = (field: SortField) => {
    if (sortField === field) {
      setSortDirection(sortDirection === 'asc' ? 'desc' : 'asc')
    } else {
      setSortField(field)
      setSortDirection('asc')
    }
  }

  const SortIcon = ({ field }: { field: SortField }) => {
    if (sortField !== field) return <span className="text-gray-300 ml-1">↕</span>
    return <span className="text-blue-600 ml-1">{sortDirection === 'asc' ? '↑' : '↓'}</span>
  }

  const downloadCSV = () => {
    const headers = [
      'Scan Page',
      'Page Label',
      'Content Type',
      'Running Header',
      'Chapter Start',
      'Chapter #',
      'Chapter Title',
      'ToC Page',
      'Blank',
      'Footnotes',
      'Label Complete',
    ]

    const rows = filteredPages.map((p) => [
      p.page_num,
      p.page_number_label || '',
      p.content_type || '',
      p.running_header || '',
      p.is_chapter_start ? 'Yes' : '',
      p.chapter_number || '',
      p.chapter_title || '',
      p.is_toc_page ? 'Yes' : '',
      p.is_blank_page ? 'Yes' : '',
      p.has_footnotes ? 'Yes' : '',
      p.label_complete ? 'Yes' : 'No',
    ])

    const csvContent = [headers.join(','), ...rows.map((r) => r.map((c) => `"${c}"`).join(','))].join('\n')

    const blob = new Blob([csvContent], { type: 'text/csv' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `${book?.title || bookId}_pages.csv`
    a.click()
    URL.revokeObjectURL(url)
  }

  if (isLoading) {
    return (
      <div className="text-center py-12">
        <div className="text-gray-500">Loading pages...</div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="text-center py-12">
        <div className="text-red-500">Error loading pages: {error.message}</div>
      </div>
    )
  }

  const labeledCount = pages.filter((p) => p.label_complete).length

  return (
    <div className="space-y-4">
      {/* Breadcrumb */}
      <nav className="text-sm">
        <Link to="/books" className="text-blue-600 hover:text-blue-800">
          Library
        </Link>
        <span className="mx-2 text-gray-400">/</span>
        <Link to="/books/$bookId" params={{ bookId }} className="text-blue-600 hover:text-blue-800">
          {book?.title || 'Book'}
        </Link>
        <span className="mx-2 text-gray-400">/</span>
        <span className="text-gray-600">Pages Table</span>
      </nav>

      {/* Header */}
      <div className="flex justify-between items-center">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Pages Table</h1>
          <p className="text-gray-500">
            {labeledCount} of {pages.length} pages labeled
          </p>
        </div>
        <div className="flex items-center space-x-3">
          <button
            onClick={downloadCSV}
            className="inline-flex items-center px-4 py-2 border border-gray-300 text-sm font-medium rounded-md text-gray-700 bg-white hover:bg-gray-50"
          >
            Download CSV
          </button>
          <Link
            to="/books/$bookId"
            params={{ bookId }}
            className="inline-flex items-center px-4 py-2 border border-gray-300 text-sm font-medium rounded-md text-gray-700 bg-white hover:bg-gray-50"
          >
            Back to Book
          </Link>
        </div>
      </div>

      {/* Filters */}
      <div className="bg-white rounded-lg shadow p-4">
        <div className="flex flex-wrap gap-4">
          <div className="flex-1 min-w-[200px]">
            <label className="block text-sm font-medium text-gray-700 mb-1">Search</label>
            <input
              type="text"
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
              placeholder="Filter by page #, label, header..."
              className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm"
            />
          </div>
          <div className="w-48">
            <label className="block text-sm font-medium text-gray-700 mb-1">Content Type</label>
            <select
              value={contentTypeFilter}
              onChange={(e) => setContentTypeFilter(e.target.value)}
              className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm"
            >
              <option value="">All Types</option>
              {contentTypes.map((type) => (
                <option key={type} value={type}>
                  {type}
                </option>
              ))}
            </select>
          </div>
          <div className="flex items-end">
            <label className="inline-flex items-center">
              <input
                type="checkbox"
                checked={showChapterStartsOnly}
                onChange={(e) => setShowChapterStartsOnly(e.target.checked)}
                className="rounded border-gray-300 text-blue-600 focus:ring-blue-500"
              />
              <span className="ml-2 text-sm text-gray-700">Chapter starts only</span>
            </label>
          </div>
        </div>
        <div className="mt-2 text-sm text-gray-500">
          Showing {filteredPages.length} of {pages.length} pages
        </div>
      </div>

      {/* Table */}
      <div className="bg-white rounded-lg shadow overflow-hidden">
        <div className="overflow-x-auto">
          <table className="min-w-full divide-y divide-gray-200">
            <thead className="bg-gray-50">
              <tr>
                <th
                  className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider cursor-pointer hover:bg-gray-100"
                  onClick={() => handleSort('page_num')}
                >
                  Scan Page <SortIcon field="page_num" />
                </th>
                <th
                  className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider cursor-pointer hover:bg-gray-100"
                  onClick={() => handleSort('page_number_label')}
                >
                  Page Label <SortIcon field="page_number_label" />
                </th>
                <th
                  className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider cursor-pointer hover:bg-gray-100"
                  onClick={() => handleSort('content_type')}
                >
                  Type <SortIcon field="content_type" />
                </th>
                <th
                  className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider cursor-pointer hover:bg-gray-100"
                  onClick={() => handleSort('running_header')}
                >
                  Running Header <SortIcon field="running_header" />
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                  Chapter
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                  Flags
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                  Status
                </th>
              </tr>
            </thead>
            <tbody className="bg-white divide-y divide-gray-200">
              {filteredPages.map((page) => (
                <tr key={page.page_num ?? 0} className="hover:bg-gray-50">
                  <td className="px-4 py-3 whitespace-nowrap">
                    <Link
                      to="/books/$bookId/pages/$pageNum"
                      params={{ bookId, pageNum: (page.page_num ?? 1).toString() }}
                      className="text-blue-600 hover:text-blue-800 font-medium"
                    >
                      {page.page_num}
                    </Link>
                  </td>
                  <td className="px-4 py-3 whitespace-nowrap text-sm text-gray-900">
                    {page.page_number_label || <span className="text-gray-400">-</span>}
                  </td>
                  <td className="px-4 py-3 whitespace-nowrap">
                    {page.content_type ? (
                      <span
                        className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${
                          page.content_type === 'body'
                            ? 'bg-green-100 text-green-800'
                            : page.content_type === 'front_matter'
                              ? 'bg-blue-100 text-blue-800'
                              : page.content_type === 'back_matter'
                                ? 'bg-purple-100 text-purple-800'
                                : page.content_type === 'toc'
                                  ? 'bg-yellow-100 text-yellow-800'
                                  : 'bg-gray-100 text-gray-800'
                        }`}
                      >
                        {page.content_type}
                      </span>
                    ) : (
                      <span className="text-gray-400">-</span>
                    )}
                  </td>
                  <td className="px-4 py-3 text-sm text-gray-900 max-w-xs truncate">
                    {page.running_header || <span className="text-gray-400">-</span>}
                  </td>
                  <td className="px-4 py-3 text-sm">
                    {page.is_chapter_start ? (
                      <div>
                        <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-orange-100 text-orange-800">
                          Start
                        </span>
                        {(page.chapter_number || page.chapter_title) && (
                          <div className="text-xs text-gray-500 mt-1">
                            {page.chapter_number && <span>Ch. {page.chapter_number}</span>}
                            {page.chapter_number && page.chapter_title && <span>: </span>}
                            {page.chapter_title && <span className="truncate">{page.chapter_title}</span>}
                          </div>
                        )}
                      </div>
                    ) : (
                      <span className="text-gray-400">-</span>
                    )}
                  </td>
                  <td className="px-4 py-3 whitespace-nowrap text-xs">
                    <div className="flex flex-wrap gap-1">
                      {page.is_toc_page && (
                        <span className="inline-flex items-center px-1.5 py-0.5 rounded bg-yellow-100 text-yellow-800">
                          ToC
                        </span>
                      )}
                      {page.is_blank_page && (
                        <span className="inline-flex items-center px-1.5 py-0.5 rounded bg-gray-100 text-gray-600">
                          Blank
                        </span>
                      )}
                      {page.has_footnotes && (
                        <span className="inline-flex items-center px-1.5 py-0.5 rounded bg-indigo-100 text-indigo-800">
                          FN
                        </span>
                      )}
                      {!page.is_toc_page && !page.is_blank_page && !page.has_footnotes && (
                        <span className="text-gray-400">-</span>
                      )}
                    </div>
                  </td>
                  <td className="px-4 py-3 whitespace-nowrap">
                    {page.label_complete ? (
                      <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-green-100 text-green-800">
                        Labeled
                      </span>
                    ) : page.blend_complete ? (
                      <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-blue-100 text-blue-800">
                        Blended
                      </span>
                    ) : page.ocr_complete ? (
                      <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-yellow-100 text-yellow-800">
                        OCR'd
                      </span>
                    ) : (
                      <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-gray-100 text-gray-600">
                        Pending
                      </span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}
