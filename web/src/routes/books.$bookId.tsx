import { useState } from 'react'
import { createFileRoute, Link, useNavigate, Outlet, useRouterState } from '@tanstack/react-router'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Menu, MenuButton, MenuItem, MenuItems } from '@headlessui/react'
import { client, unwrap } from '@/api/client'
import { ProgressBar, StatusBadge } from '@/components/ui'
import {
  CollapsibleSection,
  TocSection,
  StructureSection,
  AgentLogModal,
  MetadataModal,
  JobHistorySection,
  type StageMetrics,
} from '@/components/book'

export const Route = createFileRoute('/books/$bookId')({
  component: BookDetailLayout,
})

function BookDetailLayout() {
  const routerState = useRouterState()
  const pathname = routerState.location.pathname
  const isChildRoute = pathname.includes('/pages') || pathname.includes('/prompts') || pathname.includes('/chapters')

  if (isChildRoute) {
    return <Outlet />
  }

  return <BookDetailPage />
}

function BookDetailPage() {
  const { bookId } = Route.useParams()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [metadataModalOpen, setMetadataModalOpen] = useState(false)
  const [agentLogModalOpen, setAgentLogModalOpen] = useState(false)
  const [selectedAgentLogId, setSelectedAgentLogId] = useState<string | null>(null)

  const startJobMutation = useMutation({
    mutationFn: async (params: { jobType?: string; force?: boolean }) => {
      const { jobType, force } = params
      const result = await client.POST('/api/jobs/start/{book_id}', {
        params: { path: { book_id: bookId } },
        body: { job_type: jobType || 'process-book', force: force || false },
      })
      return unwrap(result)
    },
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['jobs', 'status', bookId] })
      queryClient.invalidateQueries({ queryKey: ['books', bookId] })
      if (data?.job_id) {
        navigate({ to: '/jobs/$jobId', params: { jobId: data.job_id } })
      }
    },
  })

  const jobTypes = [
    { id: 'process-book', label: 'Full Pipeline', description: 'OCR → Blend → Label → Metadata → ToC → Link', force: false },
    { id: 'ocr-book', label: 'OCR + Blend Only', description: 'OCR and blend all pages (no labeling)', force: false },
    { id: 'label-book', label: 'Label Only', description: 'Label pages that have blend complete', force: false },
    { id: 'metadata-book', label: 'Metadata Only', description: 'Extract book metadata (title, author, etc.)', force: false },
    { id: 'toc-book', label: 'ToC Only', description: 'Find and extract table of contents', force: false },
    { id: 'link-toc', label: 'Link ToC Only', description: 'Link ToC entries to actual pages', force: false },
    { id: 'link-toc', label: 'Link ToC (Force)', description: 'Re-link ToC entries even if already complete', force: true },
  ]

  const { data: book, isLoading, error } = useQuery({
    queryKey: ['books', bookId],
    queryFn: async () =>
      unwrap(
        await client.GET('/api/books/{id}', {
          params: { path: { id: bookId } },
        })
      ),
  })

  const { data: cost, error: costError } = useQuery({
    queryKey: ['books', bookId, 'cost'],
    queryFn: async () =>
      unwrap(
        await client.GET('/api/books/{id}/cost', {
          params: { path: { id: bookId }, query: { by: 'stage' } },
        })
      ),
  })

  const { data: detailedStatus } = useQuery({
    queryKey: ['jobs', 'status', bookId, 'detailed'],
    queryFn: async () =>
      unwrap(
        await client.GET('/api/jobs/status/{book_id}/detailed', {
          params: { path: { book_id: bookId } },
        })
      ),
    refetchInterval: 5000,
  })

  const { data: detailedMetrics } = useQuery({
    queryKey: ['books', bookId, 'metrics', 'detailed'],
    queryFn: async () => {
      const resp = await fetch(`/api/books/${bookId}/metrics/detailed`)
      if (!resp.ok) throw new Error('Failed to fetch detailed metrics')
      return resp.json() as Promise<{
        book_id: string
        stages: Record<string, StageMetrics>
      }>
    },
    refetchInterval: 10000,
  })

  const { data: agentLogDetail } = useQuery({
    queryKey: ['agent-logs', selectedAgentLogId],
    queryFn: async () =>
      selectedAgentLogId
        ? unwrap(
            await client.GET('/api/agent-logs/{id}', {
              params: { path: { id: selectedAgentLogId } },
            })
          )
        : null,
    enabled: !!selectedAgentLogId,
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
      <div className="flex justify-between items-start">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">{book.title}</h1>
          {book.author && <p className="text-gray-500">{book.author}</p>}
        </div>
        <div className="flex items-center space-x-3">
          <Link
            to="/books/$bookId/pages/$pageNum"
            params={{ bookId, pageNum: '1' }}
            className="inline-flex items-center px-4 py-2 border border-gray-300 text-sm font-medium rounded-md text-gray-700 bg-white hover:bg-gray-50"
          >
            View Pages
          </Link>
          <Link
            to="/books/$bookId/chapters"
            params={{ bookId }}
            className="inline-flex items-center px-4 py-2 border border-gray-300 text-sm font-medium rounded-md text-gray-700 bg-white hover:bg-gray-50"
          >
            Chapters
          </Link>
          <Link
            to="/books/$bookId/prompts"
            params={{ bookId }}
            className="inline-flex items-center px-4 py-2 border border-gray-300 text-sm font-medium rounded-md text-gray-700 bg-white hover:bg-gray-50"
          >
            Prompts
          </Link>
          {book.status !== 'error' && (
            <div className="flex items-center">
              <button
                onClick={() => startJobMutation.mutate({ jobType: 'process-book' })}
                disabled={startJobMutation.isPending}
                className="inline-flex items-center px-4 py-2 border border-transparent text-sm font-medium rounded-l-md shadow-sm text-white bg-blue-600 hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {startJobMutation.isPending ? 'Starting...' : 'Start Processing'}
              </button>
              <Menu as="div" className="relative">
                <MenuButton
                  disabled={startJobMutation.isPending}
                  className="inline-flex items-center px-2 py-2 border border-transparent text-sm font-medium rounded-r-md shadow-sm text-white bg-blue-600 hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed border-l border-blue-500"
                >
                  <svg className="h-5 w-5" viewBox="0 0 20 20" fill="currentColor">
                    <path fillRule="evenodd" d="M5.293 7.293a1 1 0 011.414 0L10 10.586l3.293-3.293a1 1 0 111.414 1.414l-4 4a1 1 0 01-1.414 0l-4-4a1 1 0 010-1.414z" clipRule="evenodd" />
                  </svg>
                </MenuButton>
                <MenuItems className="absolute right-0 z-10 mt-2 w-56 origin-top-right rounded-md bg-white shadow-lg ring-1 ring-black ring-opacity-5">
                  <div className="py-1">
                    {jobTypes.map((job, index) => (
                      <MenuItem key={`${job.id}-${index}`}>
                        {({ active }) => (
                          <button
                            onClick={() => startJobMutation.mutate({ jobType: job.id, force: job.force })}
                            className={`${active ? 'bg-gray-100 text-gray-900' : 'text-gray-700'} block w-full text-left px-4 py-2 text-sm`}
                          >
                            <div className="font-medium">{job.label}</div>
                            <div className="text-xs text-gray-500">{job.description}</div>
                          </button>
                        )}
                      </MenuItem>
                    ))}
                  </div>
                </MenuItems>
              </Menu>
            </div>
          )}
        </div>
        {startJobMutation.isError && (
          <p className="text-sm text-red-600 mt-2">
            Error: {startJobMutation.error?.message || 'Failed to start job'}
          </p>
        )}
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
          {costError ? (
            <p className="mt-2 text-sm text-red-500">Failed to load</p>
          ) : cost?.total_cost_usd !== undefined ? (
            <p className="mt-2 text-2xl font-semibold">${cost.total_cost_usd.toFixed(4)}</p>
          ) : (
            <p className="mt-2 text-gray-400">--</p>
          )}
        </div>
      </div>

      {/* Processing Progress */}
      {detailedStatus && (
        <div className="bg-white rounded-lg shadow p-6">
          <h3 className="text-lg font-medium text-gray-900 mb-4">Processing Progress</h3>
          <div className="space-y-4">
            {/* OCR Section - show per-provider metrics */}
            {detailedStatus.ocr_progress && Object.entries(detailedStatus.ocr_progress).length > 0 ? (
              Object.entries(detailedStatus.ocr_progress).map(([provider, progress]) => (
                <CollapsibleSection
                  key={provider}
                  title={`OCR: ${provider}`}
                  current={progress.complete || 0}
                  total={progress.total || 0}
                  cost={progress.cost_usd}
                  metrics={detailedMetrics?.stages?.[`ocr:${provider}`]}
                  stageType="ocr"
                >
                  <div className="pl-4 border-l-2 border-gray-200">
                    <ProgressBar
                      label="Pages"
                      current={progress.complete || 0}
                      total={progress.total || 0}
                    />
                  </div>
                </CollapsibleSection>
              ))
            ) : (
              <CollapsibleSection
                title="OCR"
                current={detailedStatus.stages?.ocr?.complete || 0}
                total={detailedStatus.stages?.ocr?.total || 0}
                cost={detailedStatus.stages?.ocr?.total_cost_usd}
                stageType="ocr"
              >
                <p className="text-sm text-gray-400 pl-4">No OCR results yet</p>
              </CollapsibleSection>
            )}

            {/* Blend Section */}
            <CollapsibleSection
              title="Blend"
              current={detailedStatus.stages?.blend?.complete || 0}
              total={detailedStatus.stages?.blend?.total || 0}
              cost={detailedStatus.stages?.blend?.cost_usd}
              metrics={detailedMetrics?.stages?.['blend']}
              stageType="blend"
            >
              <div className="pl-4 border-l-2 border-gray-200">
                <ProgressBar
                  label="Pages"
                  current={detailedStatus.stages?.blend?.complete || 0}
                  total={detailedStatus.stages?.blend?.total || 0}
                />
              </div>
            </CollapsibleSection>

            {/* Label Section */}
            <CollapsibleSection
              title="Label"
              current={detailedStatus.stages?.label?.complete || 0}
              total={detailedStatus.stages?.label?.total || 0}
              cost={detailedStatus.stages?.label?.cost_usd}
              metrics={detailedMetrics?.stages?.['label']}
            >
              <div className="pl-4 border-l-2 border-gray-200">
                <ProgressBar
                  label="Pages"
                  current={detailedStatus.stages?.label?.complete || 0}
                  total={detailedStatus.stages?.label?.total || 0}
                />
              </div>
            </CollapsibleSection>

            {/* Metadata Section */}
            <div className="border-t pt-4">
              <div className="flex items-center justify-between">
                <div className="flex items-center space-x-2">
                  <span className="text-sm font-medium text-gray-700">Metadata</span>
                  <StatusBadge
                    status={
                      detailedStatus.metadata?.complete
                        ? 'complete'
                        : detailedStatus.metadata?.failed
                        ? 'failed'
                        : detailedStatus.metadata?.started
                        ? 'in_progress'
                        : 'pending'
                    }
                  />
                </div>
                <div className="flex items-center space-x-2">
                  {detailedStatus.metadata?.cost_usd !== undefined && (
                    <span className="font-mono text-sm text-gray-500">
                      ${detailedStatus.metadata.cost_usd.toFixed(4)}
                    </span>
                  )}
                  {detailedStatus.metadata?.complete && detailedStatus.metadata?.data && (
                    <button
                      onClick={() => setMetadataModalOpen(true)}
                      className="text-sm text-blue-600 hover:text-blue-800"
                    >
                      View Details
                    </button>
                  )}
                </div>
              </div>
              {detailedStatus.metadata?.complete && detailedStatus.metadata?.data && (
                <div className="mt-2 pl-4 text-sm text-gray-600">
                  <div>Title: {detailedStatus.metadata.data.title || '-'}</div>
                  <div>Author: {detailedStatus.metadata.data.author || '-'}</div>
                </div>
              )}
            </div>

            {/* ToC Section */}
            <TocSection
              toc={detailedStatus.toc}
              bookId={bookId}
              metrics={detailedMetrics?.stages}
              onViewAgentLog={(id) => {
                setSelectedAgentLogId(id)
                setAgentLogModalOpen(true)
              }}
            />

            {/* Structure Section */}
            <StructureSection structure={detailedStatus.structure} bookId={bookId} metrics={detailedMetrics?.stages} />
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

      {/* Job History */}
      <JobHistorySection bookId={bookId} />

      {/* Metadata Modal */}
      {metadataModalOpen && detailedStatus?.metadata?.data && (
        <MetadataModal
          data={detailedStatus.metadata.data}
          onClose={() => setMetadataModalOpen(false)}
        />
      )}

      {/* Agent Log Modal */}
      {agentLogModalOpen && (
        <AgentLogModal
          detail={agentLogDetail || null}
          onClose={() => {
            setAgentLogModalOpen(false)
            setSelectedAgentLogId(null)
          }}
        />
      )}
    </div>
  )
}
