import { createFileRoute, Link } from '@tanstack/react-router'
import { useQuery } from '@tanstack/react-query'
import { client, unwrap } from '@/api/client'

export const Route = createFileRoute('/books/$bookId/pages/')({
  component: PagesListPage,
})

function PagesListPage() {
  const { bookId } = Route.useParams()

  const { data: book } = useQuery({
    queryKey: ['books', bookId],
    queryFn: async () =>
      unwrap(
        await client.GET('/api/books/{id}', {
          params: { path: { id: bookId } },
        })
      ),
  })

  const { data, isLoading, error } = useQuery({
    queryKey: ['books', bookId, 'pages'],
    queryFn: async () =>
      unwrap(
        await client.GET('/api/books/{book_id}/pages', {
          params: { path: { book_id: bookId } },
        })
      ),
  })

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

  const pages = data?.pages || []

  return (
    <div className="space-y-6">
      {/* Breadcrumb */}
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
        <span className="text-gray-600">Pages</span>
      </nav>

      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Pages</h1>
        <p className="text-gray-500">{pages.length} pages</p>
      </div>

      {/* Page Grid */}
      {pages.length === 0 ? (
        <div className="bg-white rounded-lg shadow p-12 text-center">
          <p className="text-gray-500">No pages extracted yet.</p>
          <p className="text-sm text-gray-400 mt-2">
            Start processing the book to extract pages.
          </p>
        </div>
      ) : (
        <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6 gap-4">
          {pages.map((page) => (
            <Link
              key={page.page_num}
              to="/books/$bookId/pages/$pageNum"
              params={{ bookId, pageNum: String(page.page_num) }}
              className="group"
            >
              <div className="bg-white rounded-lg shadow overflow-hidden hover:shadow-lg transition-shadow">
                <div className="aspect-[3/4] bg-gray-100 relative">
                  <img
                    src={`/api/books/${bookId}/pages/${page.page_num}/image`}
                    alt={`Page ${page.page_num}`}
                    className="w-full h-full object-cover"
                    loading="lazy"
                  />
                  {/* Status indicators */}
                  <div className="absolute bottom-1 right-1 flex space-x-1">
                    {page.ocr_complete && (
                      <span className="w-2 h-2 bg-green-500 rounded-full" title="OCR complete" />
                    )}
                    {page.blend_complete && (
                      <span className="w-2 h-2 bg-blue-500 rounded-full" title="Blend complete" />
                    )}
                    {page.label_complete && (
                      <span className="w-2 h-2 bg-purple-500 rounded-full" title="Labels complete" />
                    )}
                  </div>
                </div>
                <div className="p-2 text-center">
                  <span className="text-sm font-medium text-gray-700 group-hover:text-blue-600">
                    Page {page.page_num}
                  </span>
                </div>
              </div>
            </Link>
          ))}
        </div>
      )}

      {/* Legend */}
      {pages.length > 0 && (
        <div className="flex items-center space-x-4 text-xs text-gray-500">
          <span className="flex items-center">
            <span className="w-2 h-2 bg-green-500 rounded-full mr-1" /> OCR
          </span>
          <span className="flex items-center">
            <span className="w-2 h-2 bg-blue-500 rounded-full mr-1" /> Blend
          </span>
          <span className="flex items-center">
            <span className="w-2 h-2 bg-purple-500 rounded-full mr-1" /> Labels
          </span>
        </div>
      )}
    </div>
  )
}
