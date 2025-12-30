import { createFileRoute, Link } from '@tanstack/react-router'
import { useQuery } from '@tanstack/react-query'
import { client } from '@/api/client'

export const Route = createFileRoute('/books/$bookId')({
  component: BookDetailPage,
})

function BookDetailPage() {
  const { bookId } = Route.useParams()

  const { data: book, isLoading, error } = useQuery({
    queryKey: ['books', bookId],
    queryFn: async () => {
      const res = await client.GET('/api/books/{id}', {
        params: { path: { id: bookId } },
      })
      return res.data
    },
  })

  const { data: cost } = useQuery({
    queryKey: ['books', bookId, 'cost'],
    queryFn: async () => {
      const res = await client.GET('/api/books/{id}/cost', {
        params: { path: { id: bookId }, query: { by: 'stage' } },
      })
      return res.data
    },
  })

  const { data: jobStatus } = useQuery({
    queryKey: ['jobs', 'status', bookId],
    queryFn: async () => {
      const res = await client.GET('/api/jobs/status/{book_id}', {
        params: { path: { book_id: bookId } },
      })
      return res.data
    },
    refetchInterval: 5000,
  })

  if (isLoading) {
    return (
      <div className="text-center py-12">
        <div className="text-gray-500">Loading book...</div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="text-center py-12">
        <div className="text-red-500">Error loading book: {error.message}</div>
      </div>
    )
  }

  if (!book) {
    return (
      <div className="text-center py-12">
        <div className="text-gray-500">Book not found</div>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      {/* Breadcrumb */}
      <nav className="text-sm">
        <Link to="/books" className="text-blue-600 hover:text-blue-800">
          Library
        </Link>
        <span className="mx-2 text-gray-400">/</span>
        <span className="text-gray-600">{book.title}</span>
      </nav>

      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold text-gray-900">{book.title}</h1>
        {book.author && <p className="text-gray-500">{book.author}</p>}
      </div>

      {/* Info Cards */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        <div className="bg-white rounded-lg shadow p-6">
          <h3 className="text-sm font-medium text-gray-500">Pages</h3>
          <p className="mt-2 text-2xl font-semibold">{book.page_count}</p>
        </div>

        <div className="bg-white rounded-lg shadow p-6">
          <h3 className="text-sm font-medium text-gray-500">Status</h3>
          <p className="mt-2">
            <span
              className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-sm font-medium ${
                book.status === 'complete'
                  ? 'bg-green-100 text-green-800'
                  : book.status === 'processing'
                  ? 'bg-blue-100 text-blue-800'
                  : 'bg-gray-100 text-gray-800'
              }`}
            >
              {book.status}
            </span>
          </p>
        </div>

        <div className="bg-white rounded-lg shadow p-6">
          <h3 className="text-sm font-medium text-gray-500">Total Cost</h3>
          <p className="mt-2 text-2xl font-semibold">
            ${cost?.total_cost_usd?.toFixed(4) || '0.0000'}
          </p>
        </div>
      </div>

      {/* Processing Progress */}
      {jobStatus && (
        <div className="bg-white rounded-lg shadow p-6">
          <h3 className="text-lg font-medium text-gray-900 mb-4">Processing Progress</h3>
          <div className="space-y-4">
            <ProgressBar
              label="OCR"
              current={jobStatus.ocr_complete || 0}
              total={jobStatus.total_pages || 0}
            />
            <ProgressBar
              label="Blend"
              current={jobStatus.blend_complete || 0}
              total={jobStatus.total_pages || 0}
            />
            <ProgressBar
              label="Label"
              current={jobStatus.label_complete || 0}
              total={jobStatus.total_pages || 0}
            />
            <div className="flex items-center space-x-4 text-sm">
              <span className="text-gray-500">Metadata:</span>
              <span className={jobStatus.metadata_complete ? 'text-green-600' : 'text-gray-400'}>
                {jobStatus.metadata_complete ? 'Complete' : 'Pending'}
              </span>
            </div>
            <div className="flex items-center space-x-4 text-sm">
              <span className="text-gray-500">ToC:</span>
              <span className={jobStatus.toc_extracted ? 'text-green-600' : 'text-gray-400'}>
                {jobStatus.toc_extracted ? 'Extracted' : jobStatus.toc_found ? 'Found' : 'Pending'}
              </span>
            </div>
          </div>
        </div>
      )}

      {/* Cost Breakdown */}
      {cost?.breakdown && Object.keys(cost.breakdown).length > 0 && (
        <div className="bg-white rounded-lg shadow p-6">
          <h3 className="text-lg font-medium text-gray-900 mb-4">Cost Breakdown</h3>
          <div className="space-y-2">
            {Object.entries(cost.breakdown).map(([stage, amount]) => (
              <div key={stage} className="flex justify-between text-sm">
                <span className="text-gray-600">{stage}</span>
                <span className="font-mono">${(amount as number).toFixed(4)}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

function ProgressBar({ label, current, total }: { label: string; current: number; total: number }) {
  const percentage = total > 0 ? (current / total) * 100 : 0

  return (
    <div>
      <div className="flex justify-between text-sm mb-1">
        <span className="text-gray-600">{label}</span>
        <span className="text-gray-500">
          {current} / {total}
        </span>
      </div>
      <div className="w-full bg-gray-200 rounded-full h-2">
        <div
          className="bg-blue-600 h-2 rounded-full transition-all"
          style={{ width: `${percentage}%` }}
        />
      </div>
    </div>
  )
}
