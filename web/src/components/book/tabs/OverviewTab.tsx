import { Link } from '@tanstack/react-router'
import { useBookCost, useDetailedStatus, useChapters, type BookData } from './useBookData'

interface OverviewTabProps {
  bookId: string
  book: BookData
}

export function OverviewTab({ bookId, book }: OverviewTabProps) {
  const { data: cost } = useBookCost(bookId)
  const { data: detailedStatus } = useDetailedStatus(bookId)
  const { data: chaptersData } = useChapters(bookId, book.status === 'complete')

  const chapters = chaptersData?.chapters || []
  const hasChapters = chapters.length > 0

  // Calculate stats
  const frontMatter = chapters.filter((c: { matter_type?: string }) => c.matter_type === 'front_matter').length
  const bodyChapters = chapters.filter((c: { matter_type?: string }) => c.matter_type === 'body').length
  const backMatter = chapters.filter((c: { matter_type?: string }) => c.matter_type === 'back_matter').length

  // Determine processing stage
  const getProcessingStage = () => {
    if (!detailedStatus) return null
    if (detailedStatus.structure?.complete) return 'Complete'
    if (detailedStatus.structure?.started) return 'Building Structure'
    if (detailedStatus.toc?.finalize_started) return 'Finalizing ToC'
    if (detailedStatus.toc?.link_started) return 'Linking ToC'
    if (detailedStatus.toc?.extract_started) return 'Extracting ToC'
    if (detailedStatus.toc?.finder_started) return 'Finding ToC'
    if (detailedStatus.stages?.ocr?.complete) return 'OCR Complete'
    return 'Processing'
  }

  const processingStage = getProcessingStage()

  return (
    <div className="space-y-6">
      {/* Quick Stats Grid */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <StatCard label="Pages" value={book.page_count || 0} />
        <StatCard
          label="Status"
          value={
            <span
              className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-sm font-medium ${
                book.status === 'complete'
                  ? 'bg-green-100 text-green-800'
                  : book.status === 'processing'
                    ? 'bg-blue-100 text-blue-800'
                    : book.status === 'error'
                      ? 'bg-red-100 text-red-800'
                      : 'bg-gray-100 text-gray-800'
              }`}
            >
              {book.status || 'pending'}
            </span>
          }
        />
        <StatCard
          label="Total Cost"
          value={cost?.total_cost_usd !== undefined ? `$${cost.total_cost_usd.toFixed(4)}` : '--'}
          mono
        />
        <StatCard label="Chapters" value={hasChapters ? chapters.length : '--'} />
      </div>

      {/* Processing Status (only show if not complete) */}
      {book.status !== 'complete' && processingStage && (
        <div className="bg-blue-50 border border-blue-200 rounded-lg p-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center space-x-3">
              <div className="animate-pulse">
                <div className="h-3 w-3 bg-blue-500 rounded-full" />
              </div>
              <div>
                <div className="font-medium text-blue-900">Processing in Progress</div>
                <div className="text-sm text-blue-700">{processingStage}</div>
              </div>
            </div>
            <Link
              to="/books/$bookId"
              params={{ bookId }}
              search={{ tab: 'processing' }}
              className="text-sm text-blue-600 hover:text-blue-800 font-medium"
            >
              View Details →
            </Link>
          </div>
        </div>
      )}

      {/* Book Structure Summary (if complete) */}
      {hasChapters && (
        <div className="bg-white border rounded-lg p-6">
          <h3 className="text-lg font-medium text-gray-900 mb-4">Book Structure</h3>
          <div className="grid grid-cols-3 gap-6">
            <StructureStat label="Front Matter" count={frontMatter} color="purple" />
            <StructureStat label="Body" count={bodyChapters} color="blue" />
            <StructureStat label="Back Matter" count={backMatter} color="orange" />
          </div>
          <div className="mt-4 pt-4 border-t">
            <Link
              to="/books/$bookId/chapters"
              params={{ bookId }}
              className="text-blue-600 hover:text-blue-800 text-sm font-medium"
            >
              View All Chapters →
            </Link>
          </div>
        </div>
      )}

      {/* Cost Breakdown (if available) */}
      {cost?.breakdown && Object.keys(cost.breakdown).length > 0 && (
        <div className="bg-white border rounded-lg p-6">
          <h3 className="text-lg font-medium text-gray-900 mb-4">Cost Breakdown</h3>
          <div className="space-y-2">
            {Object.entries(cost.breakdown)
              .sort(([, a], [, b]) => (b as number) - (a as number))
              .map(([stage, amount]) => (
                <div key={stage} className="flex justify-between text-sm">
                  <span className="text-gray-600 capitalize">{stage.replace(/_/g, ' ')}</span>
                  <span className="font-mono text-gray-900">${(amount as number).toFixed(4)}</span>
                </div>
              ))}
          </div>
        </div>
      )}

      {/* Quick Actions */}
      <div className="bg-gray-50 border rounded-lg p-6">
        <h3 className="text-lg font-medium text-gray-900 mb-4">Quick Actions</h3>
        <div className="flex flex-wrap gap-3">
          <Link
            to="/books/$bookId/pages/$pageNum"
            params={{ bookId, pageNum: '1' }}
            className="inline-flex items-center px-4 py-2 border border-gray-300 text-sm font-medium rounded-md text-gray-700 bg-white hover:bg-gray-50"
          >
            Browse Pages
          </Link>
          <Link
            to="/books/$bookId/pages-table"
            params={{ bookId }}
            className="inline-flex items-center px-4 py-2 border border-gray-300 text-sm font-medium rounded-md text-gray-700 bg-white hover:bg-gray-50"
          >
            Pages Table
          </Link>
          {hasChapters && (
            <Link
              to="/books/$bookId/chapters"
              params={{ bookId }}
              className="inline-flex items-center px-4 py-2 border border-gray-300 text-sm font-medium rounded-md text-gray-700 bg-white hover:bg-gray-50"
            >
              Read Chapters
            </Link>
          )}
        </div>
      </div>
    </div>
  )
}

function StatCard({
  label,
  value,
  mono = false,
}: {
  label: string
  value: React.ReactNode
  mono?: boolean
}) {
  return (
    <div className="bg-white border rounded-lg p-4">
      <div className="text-sm font-medium text-gray-500">{label}</div>
      <div className={`mt-1 text-2xl font-semibold ${mono ? 'font-mono' : ''}`}>{value}</div>
    </div>
  )
}

function StructureStat({
  label,
  count,
  color,
}: {
  label: string
  count: number
  color: 'purple' | 'blue' | 'orange'
}) {
  const colors = {
    purple: 'bg-purple-100 text-purple-800',
    blue: 'bg-blue-100 text-blue-800',
    orange: 'bg-orange-100 text-orange-800',
  }

  return (
    <div className="text-center">
      <div className={`inline-flex items-center px-3 py-1 rounded-full text-sm font-medium ${colors[color]}`}>
        {label}
      </div>
      <div className="mt-2 text-3xl font-bold text-gray-900">{count}</div>
    </div>
  )
}
