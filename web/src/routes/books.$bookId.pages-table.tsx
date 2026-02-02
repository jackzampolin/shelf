import { useState, useMemo } from 'react'
import { createFileRoute, Link } from '@tanstack/react-router'
import { useQuery } from '@tanstack/react-query'
import { client, unwrap } from '@/api/client'

export const Route = createFileRoute('/books/$bookId/pages-table')({
  component: PagesTablePage,
})

type SortField = 'page_num'
type SortDirection = 'asc' | 'desc'

function PagesTablePage() {
  const { bookId } = Route.useParams()
  const [sortField, setSortField] = useState<SortField>('page_num')
  const [sortDirection, setSortDirection] = useState<SortDirection>('asc')
  const [filter, setFilter] = useState('')

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

  // Filter and sort pages
  const filteredPages = useMemo(() => {
    let result = [...pages]

    // Text filter
    if (filter) {
      const lowerFilter = filter.toLowerCase()
      result = result.filter(
        (p) =>
          (p.page_num?.toString() || '').includes(lowerFilter)
      )
    }

    // Sort
    result.sort((a, b) => {
      const aVal = a.page_num ?? 0
      const bVal = b.page_num ?? 0
      return sortDirection === 'asc' ? aVal - bVal : bVal - aVal
    })

    return result
  }, [pages, filter, sortField, sortDirection])

  const handleSort = (field: SortField) => {
    if (sortField === field) {
      setSortDirection(sortDirection === 'asc' ? 'desc' : 'asc')
    } else {
      setSortField(field)
      setSortDirection('asc')
    }
  }

  const SortIcon = ({ field }: { field: SortField }) => {
    if (sortField !== field) return <span className="text-gray-300 ml-1">&#8597;</span>
    return <span className="text-blue-600 ml-1">{sortDirection === 'asc' ? '\u2191' : '\u2193'}</span>
  }

  const downloadCSV = () => {
    const headers = [
      'Scan Page',
      'OCR Complete',
    ]

    const rows = filteredPages.map((p) => [
      p.page_num,
      p.ocr_complete ? 'Yes' : 'No',
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

  const ocrCount = pages.filter((p) => p.ocr_complete).length

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
            {ocrCount} of {pages.length} pages OCR complete
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
              placeholder="Filter by page #..."
              className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm"
            />
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
                  <td className="px-4 py-3 whitespace-nowrap">
                    {page.ocr_complete ? (
                      <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-green-100 text-green-800">
                        OCR Complete
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
