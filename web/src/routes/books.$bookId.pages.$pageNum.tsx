import { useState, useEffect } from 'react'
import { createFileRoute, Link, useNavigate } from '@tanstack/react-router'
import { useQuery } from '@tanstack/react-query'
import { client, unwrap } from '@/api/client'

export const Route = createFileRoute('/books/$bookId/pages/$pageNum')({
  component: PageViewerPage,
})

type TabType = 'blend' | 'ocr' | 'diff'

function PageViewerPage() {
  const { bookId, pageNum } = Route.useParams()
  const navigate = useNavigate()
  const [activeTab, setActiveTab] = useState<TabType>('blend')
  const [selectedOcrIndex, setSelectedOcrIndex] = useState(0)
  const [zoom, setZoom] = useState(100)

  const pageNumber = parseInt(pageNum, 10)

  const { data: book } = useQuery({
    queryKey: ['books', bookId],
    queryFn: async () =>
      unwrap(
        await client.GET('/api/books/{id}', {
          params: { path: { id: bookId } },
        })
      ),
  })

  const { data: page, isLoading, error } = useQuery({
    queryKey: ['books', bookId, 'pages', pageNum],
    queryFn: async () =>
      unwrap(
        await client.GET('/api/books/{book_id}/pages/{page_num}', {
          params: { path: { book_id: bookId, page_num: parseInt(pageNum, 10) } },
        })
      ),
  })

  const totalPages = book?.page_count || 0

  // Keyboard navigation
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'ArrowLeft' && pageNumber > 1) {
        navigate({
          to: '/books/$bookId/pages/$pageNum',
          params: { bookId, pageNum: String(pageNumber - 1) },
        })
      } else if (e.key === 'ArrowRight' && pageNumber < totalPages) {
        navigate({
          to: '/books/$bookId/pages/$pageNum',
          params: { bookId, pageNum: String(pageNumber + 1) },
        })
      }
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [pageNumber, totalPages, bookId, navigate])

  if (isLoading) {
    return (
      <div className="text-center py-12">
        <div className="text-gray-500">Loading page...</div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="text-center py-12">
        <div className="text-red-500">Error loading page: {error.message}</div>
      </div>
    )
  }

  const ocrResults = page?.ocr_results || []
  const currentOcr = ocrResults[selectedOcrIndex]

  const getDisplayText = () => {
    if (activeTab === 'blend') {
      return page?.blend_markdown || 'No blend output available'
    } else if (activeTab === 'ocr' && currentOcr) {
      return currentOcr.text || 'No OCR text available'
    }
    return ''
  }

  return (
    <div className="h-[calc(100vh-120px)] flex flex-col">
      {/* Header with navigation */}
      <div className="flex items-center justify-between py-3 border-b">
        <nav className="text-sm">
          <Link to="/books" className="text-blue-600 hover:text-blue-800">
            Library
          </Link>
          <span className="mx-2 text-gray-400">/</span>
          <Link
            to="/books/$bookId"
            params={{ bookId }}
            className="text-blue-600 hover:text-blue-800"
          >
            {book?.title || 'Book'}
          </Link>
          <span className="mx-2 text-gray-400">/</span>
          <Link
            to="/books/$bookId/pages"
            params={{ bookId }}
            className="text-blue-600 hover:text-blue-800"
          >
            Pages
          </Link>
        </nav>

        <div className="flex items-center space-x-4">
          <button
            onClick={() =>
              navigate({
                to: '/books/$bookId/pages/$pageNum',
                params: { bookId, pageNum: String(pageNumber - 1) },
              })
            }
            disabled={pageNumber <= 1}
            className="px-3 py-1 text-sm border rounded hover:bg-gray-50 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            Previous
          </button>
          <div className="flex items-center space-x-1 text-sm text-gray-600">
            <span>Page</span>
            <input
              type="number"
              min={1}
              max={totalPages}
              value={pageNumber}
              onChange={(e) => {
                const val = parseInt(e.target.value, 10)
                if (val >= 1 && val <= totalPages) {
                  navigate({
                    to: '/books/$bookId/pages/$pageNum',
                    params: { bookId, pageNum: String(val) },
                  })
                }
              }}
              className="w-16 px-2 py-1 text-center border rounded focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
            <span>of {totalPages}</span>
          </div>
          <button
            onClick={() =>
              navigate({
                to: '/books/$bookId/pages/$pageNum',
                params: { bookId, pageNum: String(pageNumber + 1) },
              })
            }
            disabled={pageNumber >= totalPages}
            className="px-3 py-1 text-sm border rounded hover:bg-gray-50 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            Next
          </button>
        </div>
      </div>

      {/* Main content - split view */}
      <div className="flex-1 flex overflow-hidden">
        {/* Left panel - Image */}
        <div className="w-1/2 border-r overflow-auto bg-gray-100 p-4">
          <div className="flex justify-center mb-2 space-x-2">
            <button
              onClick={() => setZoom(Math.max(25, zoom - 25))}
              className="px-2 py-1 text-xs border rounded hover:bg-white"
            >
              -
            </button>
            <span className="px-2 py-1 text-xs">{zoom}%</span>
            <button
              onClick={() => setZoom(Math.min(200, zoom + 25))}
              className="px-2 py-1 text-xs border rounded hover:bg-white"
            >
              +
            </button>
            <button
              onClick={() => setZoom(100)}
              className="px-2 py-1 text-xs border rounded hover:bg-white"
            >
              Reset
            </button>
          </div>
          <div className="flex justify-center">
            <img
              src={`/api/books/${bookId}/pages/${pageNum}/image`}
              alt={`Page ${pageNum}`}
              style={{ width: `${zoom}%`, maxWidth: 'none' }}
              className="shadow-lg"
            />
          </div>
        </div>

        {/* Right panel - Text content */}
        <div className="w-1/2 flex flex-col overflow-hidden">
          {/* Labels banner */}
          {page?.labels && (
            <div className="bg-gray-50 px-4 py-2 border-b flex items-center space-x-4 text-sm">
              {page.labels.page_number_label && (
                <span className="text-gray-600">
                  Page: <span className="font-medium">{page.labels.page_number_label}</span>
                </span>
              )}
              {page.labels.running_header && (
                <span className="text-gray-600">
                  Header: <span className="font-medium">{page.labels.running_header}</span>
                </span>
              )}
              {page.labels.is_toc_page && (
                <span className="bg-yellow-100 text-yellow-800 px-2 py-0.5 rounded text-xs">
                  ToC
                </span>
              )}
              {page.labels.is_front_matter && (
                <span className="bg-blue-100 text-blue-800 px-2 py-0.5 rounded text-xs">
                  Front Matter
                </span>
              )}
              {page.labels.is_back_matter && (
                <span className="bg-purple-100 text-purple-800 px-2 py-0.5 rounded text-xs">
                  Back Matter
                </span>
              )}
            </div>
          )}

          {/* Tab bar */}
          <div className="border-b px-4 py-2 flex items-center space-x-2">
            <button
              onClick={() => setActiveTab('blend')}
              className={`px-3 py-1 text-sm rounded ${
                activeTab === 'blend'
                  ? 'bg-blue-100 text-blue-800'
                  : 'text-gray-600 hover:bg-gray-100'
              }`}
            >
              Blend
              {page?.blend_confidence !== undefined && (
                <span className="ml-1 text-xs opacity-75">
                  ({(page.blend_confidence * 100).toFixed(0)}%)
                </span>
              )}
            </button>

            {ocrResults.length > 0 && (
              <>
                <button
                  onClick={() => setActiveTab('ocr')}
                  className={`px-3 py-1 text-sm rounded ${
                    activeTab === 'ocr'
                      ? 'bg-blue-100 text-blue-800'
                      : 'text-gray-600 hover:bg-gray-100'
                  }`}
                >
                  OCR ({ocrResults.length})
                </button>

                {activeTab === 'ocr' && ocrResults.length > 1 && (
                  <select
                    value={selectedOcrIndex}
                    onChange={(e) => setSelectedOcrIndex(parseInt(e.target.value, 10))}
                    className="text-sm border rounded px-2 py-1"
                  >
                    {ocrResults.map((ocr, idx) => (
                      <option key={idx} value={idx}>
                        {ocr.provider}
                        {ocr.confidence !== undefined &&
                          ` (${(ocr.confidence * 100).toFixed(0)}%)`}
                      </option>
                    ))}
                  </select>
                )}
              </>
            )}

            {/* Status indicators */}
            <div className="flex-1" />
            <div className="flex items-center space-x-2 text-xs">
              <span
                className={`px-2 py-0.5 rounded ${
                  page?.status?.ocr_complete
                    ? 'bg-green-100 text-green-800'
                    : 'bg-gray-100 text-gray-500'
                }`}
              >
                OCR
              </span>
              <span
                className={`px-2 py-0.5 rounded ${
                  page?.status?.blend_complete
                    ? 'bg-green-100 text-green-800'
                    : 'bg-gray-100 text-gray-500'
                }`}
              >
                Blend
              </span>
              <span
                className={`px-2 py-0.5 rounded ${
                  page?.status?.label_complete
                    ? 'bg-green-100 text-green-800'
                    : 'bg-gray-100 text-gray-500'
                }`}
              >
                Labels
              </span>
            </div>
          </div>

          {/* Text content */}
          <div className="flex-1 overflow-auto p-4">
            <pre className="whitespace-pre-wrap font-mono text-sm text-gray-800 leading-relaxed">
              {getDisplayText()}
            </pre>
          </div>

          {/* Copy button */}
          <div className="border-t px-4 py-2">
            <button
              onClick={() => navigator.clipboard.writeText(getDisplayText())}
              className="text-sm text-blue-600 hover:text-blue-800"
            >
              Copy to clipboard
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
