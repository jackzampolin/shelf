import { useState } from 'react'
import { createFileRoute, Link, useNavigate, Outlet, useRouterState } from '@tanstack/react-router'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Disclosure, DisclosureButton, DisclosurePanel, Menu, MenuButton, MenuItem, MenuItems } from '@headlessui/react'
import { client, unwrap } from '@/api/client'

export const Route = createFileRoute('/books/$bookId')({
  component: BookDetailLayout,
})

function BookDetailLayout() {
  const routerState = useRouterState()
  const pathname = routerState.location.pathname
  // Check if we're on a child route (pages list, page viewer, prompts, or chapters)
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
      console.log('Starting job:', { bookId, jobType: jobType || 'process-book', force })
      const result = await client.POST('/api/jobs/start/{book_id}', {
        params: { path: { book_id: bookId } },
        body: { job_type: jobType || 'process-book', force: force || false },
      })
      console.log('Job start result:', result)
      return unwrap(result)
    },
    onSuccess: (data) => {
      console.log('Job started successfully:', data)
      queryClient.invalidateQueries({ queryKey: ['jobs', 'status', bookId] })
      queryClient.invalidateQueries({ queryKey: ['books', bookId] })
      if (data?.job_id) {
        navigate({ to: '/jobs/$jobId', params: { jobId: data.job_id } })
      }
    },
    onError: (error) => {
      console.error('Failed to start job:', error)
    },
  })

  // Available job types for the dropdown
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

  // Use the detailed status endpoint for comprehensive progress
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

  // Fetch detailed metrics with latency percentiles and token stats
  const { data: detailedMetrics } = useQuery({
    queryKey: ['books', bookId, 'metrics', 'detailed'],
    queryFn: async () => {
      // Use fetch directly since this endpoint isn't in the generated types yet
      const resp = await fetch(`/api/books/${bookId}/metrics/detailed`)
      if (!resp.ok) throw new Error('Failed to fetch detailed metrics')
      return resp.json() as Promise<{
        book_id: string
        stages: Record<string, StageMetrics>
      }>
    },
    refetchInterval: 10000, // Less frequent than status
  })

  // Fetch agent log detail when selected
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
            className="inline-flex items-center px-4 py-2 border border-gray-300 text-sm font-medium rounded-md text-gray-700 bg-white hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500"
          >
            View Pages
          </Link>
          <Link
            to="/books/$bookId/chapters"
            params={{ bookId }}
            className="inline-flex items-center px-4 py-2 border border-gray-300 text-sm font-medium rounded-md text-gray-700 bg-white hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500"
          >
            Chapters
          </Link>
          <Link
            to="/books/$bookId/prompts"
            params={{ bookId }}
            className="inline-flex items-center px-4 py-2 border border-gray-300 text-sm font-medium rounded-md text-gray-700 bg-white hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500"
          >
            Prompts
          </Link>
          {/* Job buttons - always show so users can run different job types */}
          {(book.status !== 'error') && (
            <div className="flex items-center">
              {/* Main Start Processing button */}
              <button
                onClick={() => startJobMutation.mutate({ jobType: 'process-book' })}
                disabled={startJobMutation.isPending}
                className="inline-flex items-center px-4 py-2 border border-transparent text-sm font-medium rounded-l-md shadow-sm text-white bg-blue-600 hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500 disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {startJobMutation.isPending ? 'Starting...' : 'Start Processing'}
              </button>
              {/* Dropdown for other job types */}
              <Menu as="div" className="relative">
                <MenuButton
                  disabled={startJobMutation.isPending}
                  className="inline-flex items-center px-2 py-2 border border-transparent text-sm font-medium rounded-r-md shadow-sm text-white bg-blue-600 hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500 disabled:opacity-50 disabled:cursor-not-allowed border-l border-blue-500"
                >
                  <svg className="h-5 w-5" viewBox="0 0 20 20" fill="currentColor">
                    <path fillRule="evenodd" d="M5.293 7.293a1 1 0 011.414 0L10 10.586l3.293-3.293a1 1 0 111.414 1.414l-4 4a1 1 0 01-1.414 0l-4-4a1 1 0 010-1.414z" clipRule="evenodd" />
                  </svg>
                </MenuButton>
                <MenuItems className="absolute right-0 z-10 mt-2 w-56 origin-top-right rounded-md bg-white shadow-lg ring-1 ring-black ring-opacity-5 focus:outline-none">
                  <div className="py-1">
                    {jobTypes.map((job, index) => (
                      <MenuItem key={`${job.id}-${index}`}>
                        {({ active }) => (
                          <button
                            onClick={() => startJobMutation.mutate({ jobType: job.id, force: job.force })}
                            className={`${
                              active ? 'bg-gray-100 text-gray-900' : 'text-gray-700'
                            } block w-full text-left px-4 py-2 text-sm`}
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

      {/* Enhanced Processing Progress */}
      {detailedStatus && (
        <div className="bg-white rounded-lg shadow p-6">
          <h3 className="text-lg font-medium text-gray-900 mb-4">Processing Progress</h3>
          <div className="space-y-4">
            {/* OCR Section with per-provider breakdown */}
            <CollapsibleSection
              title="OCR"
              current={detailedStatus.stages?.ocr?.complete || 0}
              total={detailedStatus.stages?.ocr?.total || 0}
              cost={detailedStatus.stages?.ocr?.total_cost_usd}
              metrics={detailedMetrics?.stages?.['ocr-book']}
            >
              {detailedStatus.ocr_progress && Object.entries(detailedStatus.ocr_progress).length > 0 ? (
                <div className="space-y-2 pl-4 border-l-2 border-gray-200">
                  {Object.entries(detailedStatus.ocr_progress).map(([provider, progress]) => (
                    <div key={provider} className="flex items-center justify-between text-sm">
                      <div className="flex-1">
                        <ProgressBar
                          label={provider}
                          current={progress.complete || 0}
                          total={progress.total || 0}
                        />
                      </div>
                      <span className="ml-4 font-mono text-gray-500">
                        ${(progress.cost_usd || 0).toFixed(4)}
                      </span>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="text-sm text-gray-400 pl-4">No OCR results yet</p>
              )}
            </CollapsibleSection>

            {/* Blend Section */}
            <CollapsibleSection
              title="Blend"
              current={detailedStatus.stages?.blend?.complete || 0}
              total={detailedStatus.stages?.blend?.total || 0}
              cost={detailedStatus.stages?.blend?.cost_usd}
              metrics={detailedMetrics?.stages?.['process-book'] || detailedMetrics?.stages?.['blend']}
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
              metrics={detailedMetrics?.stages?.['label-book'] || detailedMetrics?.stages?.['label']}
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

            {/* ToC Section - Enhanced with expandable entries */}
            <TocSection
              toc={detailedStatus.toc}
              bookId={bookId}
            />

            {/* Structure Section - Enhanced */}
            <StructureSection
              structure={detailedStatus.structure}
              bookId={bookId}
            />

            {/* Agent Logs Section - Grouped by operation */}
            {detailedStatus.agent_logs && detailedStatus.agent_logs.length > 0 && (
              <AgentLogsSection
                logs={detailedStatus.agent_logs}
                onViewLog={(id) => {
                  setSelectedAgentLogId(id)
                  setAgentLogModalOpen(true)
                }}
              />
            )}
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

      {/* Metadata Modal */}
      {metadataModalOpen && detailedStatus?.metadata?.data && (
        <Modal title="Book Metadata" onClose={() => setMetadataModalOpen(false)}>
          <div className="space-y-4">
            <MetadataRow label="Title" value={detailedStatus.metadata.data.title} />
            <MetadataRow label="Author" value={detailedStatus.metadata.data.author} />
            {detailedStatus.metadata.data.authors && detailedStatus.metadata.data.authors.length > 0 && (
              <MetadataRow label="Authors" value={detailedStatus.metadata.data.authors.join(', ')} />
            )}
            <MetadataRow label="ISBN" value={detailedStatus.metadata.data.isbn} />
            <MetadataRow label="LCCN" value={detailedStatus.metadata.data.lccn} />
            <MetadataRow label="Publisher" value={detailedStatus.metadata.data.publisher} />
            <MetadataRow
              label="Publication Year"
              value={detailedStatus.metadata.data.publication_year?.toString()}
            />
            <MetadataRow label="Language" value={detailedStatus.metadata.data.language} />
            {detailedStatus.metadata.data.description && (
              <div>
                <dt className="text-sm font-medium text-gray-500">Description</dt>
                <dd className="mt-1 text-sm text-gray-900 whitespace-pre-wrap">
                  {detailedStatus.metadata.data.description}
                </dd>
              </div>
            )}
            {detailedStatus.metadata.data.subjects && detailedStatus.metadata.data.subjects.length > 0 && (
              <div>
                <dt className="text-sm font-medium text-gray-500">Subjects</dt>
                <dd className="mt-1 flex flex-wrap gap-1">
                  {detailedStatus.metadata.data.subjects.map((subject, idx) => (
                    <span
                      key={idx}
                      className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-gray-100 text-gray-800"
                    >
                      {subject}
                    </span>
                  ))}
                </dd>
              </div>
            )}
          </div>
        </Modal>
      )}

      {/* Agent Log Modal */}
      {agentLogModalOpen && (
        <Modal
          title={`Agent Log: ${agentLogDetail?.agent_type || 'Loading...'}`}
          onClose={() => {
            setAgentLogModalOpen(false)
            setSelectedAgentLogId(null)
          }}
          wide
        >
          {agentLogDetail ? (
            <div className="space-y-4">
              <div className="grid grid-cols-2 gap-4 text-sm">
                <div>
                  <span className="text-gray-500">Agent Type:</span>{' '}
                  <span className="font-medium">{agentLogDetail.agent_type}</span>
                </div>
                <div>
                  <span className="text-gray-500">Iterations:</span>{' '}
                  <span className="font-medium">{agentLogDetail.iterations}</span>
                </div>
                <div>
                  <span className="text-gray-500">Status:</span>{' '}
                  <StatusBadge status={agentLogDetail.success ? 'complete' : 'failed'} />
                </div>
                <div>
                  <span className="text-gray-500">Started:</span>{' '}
                  <span className="font-mono text-xs">
                    {agentLogDetail.started_at ? new Date(agentLogDetail.started_at).toLocaleString() : '-'}
                  </span>
                </div>
              </div>
              {agentLogDetail.error && (
                <div className="bg-red-50 border border-red-200 rounded p-3">
                  <div className="text-sm font-medium text-red-800">Error</div>
                  <div className="text-sm text-red-700 mt-1">{agentLogDetail.error}</div>
                </div>
              )}
              {agentLogDetail.result && (
                <div>
                  <div className="text-sm font-medium text-gray-700 mb-2">Result</div>
                  <div className="bg-gray-50 rounded p-3">
                    <KeyValueDisplay data={agentLogDetail.result} />
                  </div>
                </div>
              )}
              <MessagesSection messages={agentLogDetail.messages} />
              <ToolCallsSection toolCalls={agentLogDetail.tool_calls} />
            </div>
          ) : (
            <div className="text-center py-4 text-gray-500">Loading...</div>
          )}
        </Modal>
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

// Detailed metrics for a stage
interface StageMetrics {
  count: number
  success_count: number
  error_count: number
  total_cost_usd: number
  avg_cost_usd: number
  latency_p50: number
  latency_p95: number
  latency_p99: number
  latency_avg: number
  latency_min: number
  latency_max: number
  total_prompt_tokens: number
  total_completion_tokens: number
  total_reasoning_tokens: number
  total_tokens: number
  avg_prompt_tokens: number
  avg_completion_tokens: number
  avg_reasoning_tokens: number
  avg_total_tokens: number
}

function CollapsibleSection({
  title,
  current,
  total,
  cost,
  metrics,
  children,
}: {
  title: string
  current: number
  total: number
  cost?: number
  metrics?: StageMetrics
  children: React.ReactNode
}) {
  const [isOpen, setIsOpen] = useState(false)
  const percentage = total > 0 ? (current / total) * 100 : 0

  return (
    <div className="border-b pb-4">
      <button
        onClick={() => setIsOpen(!isOpen)}
        className="w-full flex items-center justify-between text-left"
      >
        <div className="flex items-center space-x-2">
          <span className={`transition-transform ${isOpen ? 'rotate-90' : ''}`}>
            ▶
          </span>
          <span className="text-sm font-medium text-gray-700">{title}</span>
          <span className="text-sm text-gray-500">
            ({current}/{total})
          </span>
        </div>
        <div className="flex items-center space-x-4">
          <div className="w-24 bg-gray-200 rounded-full h-2">
            <div
              className="bg-blue-600 h-2 rounded-full transition-all"
              style={{ width: `${percentage}%` }}
            />
          </div>
          {cost !== undefined && (
            <span className="font-mono text-sm text-gray-500">${cost.toFixed(4)}</span>
          )}
        </div>
      </button>
      {isOpen && (
        <div className="mt-2">
          {/* Metrics summary row */}
          {metrics && metrics.count > 0 && (
            <div className="bg-gray-50 rounded px-3 py-2 mb-2 text-xs">
              <div className="flex items-center justify-between">
                <div className="flex items-center space-x-4">
                  <span className="text-gray-600">
                    <strong>{metrics.count}</strong> calls
                    {metrics.error_count > 0 && (
                      <span className="text-red-500 ml-1">({metrics.error_count} errors)</span>
                    )}
                  </span>
                  <span className="text-gray-600">
                    Latency: <strong>{metrics.latency_p50.toFixed(1)}s</strong> p50
                    <span className="text-gray-400 mx-1">/</span>
                    <strong>{metrics.latency_p95.toFixed(1)}s</strong> p95
                  </span>
                </div>
                <div className="flex items-center space-x-4">
                  <span className="text-gray-600">
                    Tokens: <strong>{formatNumber(metrics.avg_prompt_tokens)}</strong> in
                    <span className="text-gray-400 mx-1">→</span>
                    <strong>{formatNumber(metrics.avg_completion_tokens)}</strong> out
                    {metrics.avg_reasoning_tokens > 0 && (
                      <span className="text-purple-600 ml-1">
                        (+{formatNumber(metrics.avg_reasoning_tokens)} reason)
                      </span>
                    )}
                  </span>
                </div>
              </div>
            </div>
          )}
          {children}
        </div>
      )}
    </div>
  )
}

// Format large numbers with K/M suffix
function formatNumber(n: number): string {
  if (n >= 1000000) return (n / 1000000).toFixed(1) + 'M'
  if (n >= 1000) return (n / 1000).toFixed(1) + 'K'
  return Math.round(n).toString()
}

function StatusBadge({ status }: { status: 'pending' | 'in_progress' | 'complete' | 'failed' }) {
  const styles = {
    pending: 'bg-gray-100 text-gray-600',
    in_progress: 'bg-blue-100 text-blue-700',
    complete: 'bg-green-100 text-green-700',
    failed: 'bg-red-100 text-red-700',
  }

  const labels = {
    pending: 'Pending',
    in_progress: 'In Progress',
    complete: 'Complete',
    failed: 'Failed',
  }

  return (
    <span className={`px-2 py-0.5 rounded text-xs font-medium ${styles[status]}`}>
      {labels[status]}
    </span>
  )
}

function MetadataRow({ label, value }: { label: string; value?: string }) {
  if (!value) return null
  return (
    <div className="flex">
      <dt className="text-sm font-medium text-gray-500 w-32 flex-shrink-0">{label}</dt>
      <dd className="text-sm text-gray-900">{value}</dd>
    </div>
  )
}

function Modal({
  title,
  onClose,
  children,
  wide = false,
}: {
  title: string
  onClose: () => void
  children: React.ReactNode
  wide?: boolean
}) {
  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
      <div className={`bg-white rounded-lg shadow-xl ${wide ? 'max-w-4xl' : 'max-w-2xl'} w-full mx-4 max-h-[90vh] flex flex-col`}>
        <div className="flex items-center justify-between px-6 py-4 border-b">
          <h2 className="text-lg font-semibold text-gray-900">{title}</h2>
          <button
            onClick={onClose}
            className="text-gray-400 hover:text-gray-600 text-2xl leading-none"
          >
            &times;
          </button>
        </div>
        <div className="p-6 overflow-y-auto">{children}</div>
      </div>
    </div>
  )
}

function RoleBadge({ role }: { role: string }) {
  const styles: Record<string, string> = {
    system: 'bg-purple-100 text-purple-700',
    user: 'bg-blue-100 text-blue-700',
    assistant: 'bg-green-100 text-green-700',
    tool: 'bg-orange-100 text-orange-700',
  }

  return (
    <span className={`px-2 py-0.5 rounded text-xs font-medium ${styles[role] || 'bg-gray-100 text-gray-700'}`}>
      {role}
    </span>
  )
}

function formatJSON(jsonString: string): string {
  try {
    return JSON.stringify(JSON.parse(jsonString), null, 2)
  } catch {
    return jsonString
  }
}

function KeyValueDisplay({ data, depth = 0 }: { data: unknown; depth?: number }) {
  if (data === null || data === undefined) {
    return <span className="text-gray-400 italic">null</span>
  }

  if (typeof data === 'boolean') {
    return (
      <span className={data ? 'text-green-600' : 'text-red-600'}>
        {data ? '✓ true' : '✗ false'}
      </span>
    )
  }

  if (typeof data === 'number') {
    // Special case for confidence scores (0-1 range)
    if (data >= 0 && data <= 1) {
      const percent = Math.round(data * 100)
      return (
        <span className="inline-flex items-center gap-2">
          <span className="font-mono">{data.toFixed(2)}</span>
          <span className="text-xs text-gray-500">({percent}%)</span>
        </span>
      )
    }
    return <span className="font-mono text-blue-600">{data}</span>
  }

  if (typeof data === 'string') {
    if (data.length > 200) {
      return <span className="text-gray-700">{data.slice(0, 200)}...</span>
    }
    return <span className="text-gray-700">{data}</span>
  }

  if (Array.isArray(data)) {
    if (data.length === 0) {
      return <span className="text-gray-400 italic">empty array</span>
    }
    return (
      <div className="space-y-1">
        {data.map((item, idx) => (
          <div key={idx} className="flex gap-2">
            <span className="text-gray-400 text-xs">{idx}.</span>
            <KeyValueDisplay data={item} depth={depth + 1} />
          </div>
        ))}
      </div>
    )
  }

  if (typeof data === 'object') {
    const entries = Object.entries(data)
    if (entries.length === 0) {
      return <span className="text-gray-400 italic">empty object</span>
    }
    return (
      <div className={`space-y-2 ${depth > 0 ? 'pl-3 border-l border-gray-200' : ''}`}>
        {entries.map(([key, value]) => (
          <div key={key} className="text-sm">
            <span className="font-medium text-gray-600">{formatKey(key)}:</span>{' '}
            {isSimpleValue(value) ? (
              <KeyValueDisplay data={value} depth={depth + 1} />
            ) : (
              <div className="mt-1">
                <KeyValueDisplay data={value} depth={depth + 1} />
              </div>
            )}
          </div>
        ))}
      </div>
    )
  }

  return <span>{String(data)}</span>
}

function formatKey(key: string): string {
  return key
    .replace(/_/g, ' ')
    .replace(/([a-z])([A-Z])/g, '$1 $2')
    .replace(/^./, (s) => s.toUpperCase())
}

function isSimpleValue(value: unknown): boolean {
  return (
    value === null ||
    value === undefined ||
    typeof value === 'boolean' ||
    typeof value === 'number' ||
    typeof value === 'string'
  )
}

interface Message {
  role?: string
  content?: string
  tool_call_id?: string
}

interface ToolCall {
  tool_name?: string
  timestamp?: string
  iteration?: number
  args_json?: string
  result_len?: number
  error?: string
}

function MessagesSection({ messages }: { messages?: unknown }) {
  if (!messages || !Array.isArray(messages) || messages.length === 0) {
    return null
  }

  // Type guard: check if first item looks like a message object
  const firstItem = messages[0]
  if (typeof firstItem !== 'object' || firstItem === null) {
    return null
  }

  const typedMessages = messages as Message[]

  return (
    <div>
      <div className="text-sm font-medium text-gray-700 mb-2">
        Messages ({typedMessages.length})
      </div>
      <div className="space-y-2 max-h-80 overflow-y-auto">
        {typedMessages.map((msg, idx) => (
          <div key={idx} className="bg-gray-50 rounded p-3 text-sm">
            <div className="flex items-center gap-2 mb-1">
              <RoleBadge role={msg.role || 'unknown'} />
              {msg.tool_call_id && (
                <span className="text-xs text-gray-400 font-mono">
                  {msg.tool_call_id}
                </span>
              )}
            </div>
            <div className="text-gray-700 whitespace-pre-wrap text-xs">
              {msg.content || <span className="text-gray-400 italic">No content</span>}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

function ToolCallsSection({ toolCalls }: { toolCalls?: unknown }) {
  if (!toolCalls || !Array.isArray(toolCalls) || toolCalls.length === 0) {
    return null
  }

  // Type guard: check if first item looks like a tool call object
  const firstItem = toolCalls[0]
  if (typeof firstItem !== 'object' || firstItem === null) {
    return null
  }

  const typedCalls = toolCalls as ToolCall[]

  return (
    <div>
      <div className="text-sm font-medium text-gray-700 mb-2">
        Tool Calls ({typedCalls.length})
      </div>
      <div className="space-y-2 max-h-80 overflow-y-auto">
        {typedCalls.map((call, idx) => (
          <Disclosure key={idx}>
            {({ open }) => (
              <div className="border rounded">
                <DisclosureButton className="w-full flex items-center justify-between p-3 text-left bg-gray-50 hover:bg-gray-100">
                  <div className="flex items-center gap-2">
                    <span className={`text-xs transition-transform ${open ? 'rotate-90' : ''}`}>
                      ▶
                    </span>
                    <span className="font-mono text-sm text-blue-600">
                      {call.tool_name}
                    </span>
                    {call.iteration !== undefined && (
                      <span className="text-xs text-gray-400">
                        iter {call.iteration}
                      </span>
                    )}
                  </div>
                  <div className="flex items-center gap-2 text-xs text-gray-500">
                    {call.result_len !== undefined && (
                      <span>{call.result_len} chars</span>
                    )}
                    {call.error && (
                      <span className="text-red-500">error</span>
                    )}
                  </div>
                </DisclosureButton>
                <DisclosurePanel className="p-3 border-t bg-white">
                  {call.args_json && (
                    <div className="mb-2">
                      <div className="text-xs font-medium text-gray-500 mb-1">Arguments</div>
                      <pre className="text-xs bg-gray-50 p-2 rounded overflow-x-auto">
                        {formatJSON(call.args_json)}
                      </pre>
                    </div>
                  )}
                  {call.error && (
                    <div className="text-xs text-red-600 bg-red-50 p-2 rounded">
                      {call.error}
                    </div>
                  )}
                  {call.timestamp && (
                    <div className="text-xs text-gray-400 mt-2">
                      {new Date(call.timestamp).toLocaleString()}
                    </div>
                  )}
                </DisclosurePanel>
              </div>
            )}
          </Disclosure>
        ))}
      </div>
    </div>
  )
}

// ToC Entry type for the ToC section
interface TocEntry {
  entry_number?: string
  title?: string
  level?: number
  level_name?: string
  printed_page_number?: string
  sort_order?: number
  actual_page_num?: number
  is_linked?: boolean
  source?: string
}

// ToC Status type
interface TocStatus {
  finder_started?: boolean
  finder_complete?: boolean
  finder_failed?: boolean
  found?: boolean
  start_page?: number
  end_page?: number
  extract_started?: boolean
  extract_complete?: boolean
  extract_failed?: boolean
  link_started?: boolean
  link_complete?: boolean
  link_failed?: boolean
  link_retries?: number
  finalize_started?: boolean
  finalize_complete?: boolean
  finalize_failed?: boolean
  finalize_retries?: number
  entry_count?: number
  entries_linked?: number
  entries_discovered?: number
  entries?: TocEntry[]
  cost_usd?: number
}

// Enhanced ToC Section Component
function TocSection({ toc, bookId }: { toc?: TocStatus; bookId: string }) {
  const [entriesExpanded, setEntriesExpanded] = useState(false)

  if (!toc) return null

  // Calculate stage statuses
  const finderStatus = toc.finder_complete ? 'complete' : toc.finder_failed ? 'failed' : toc.finder_started ? 'in_progress' : 'pending'
  const extractStatus = toc.extract_complete ? 'complete' : toc.extract_failed ? 'failed' : toc.extract_started ? 'in_progress' : 'pending'
  const linkStatus = toc.link_complete ? 'complete' : toc.link_failed ? 'failed' : toc.link_started ? 'in_progress' : 'pending'
  const finalizeStatus = toc.finalize_complete ? 'complete' : toc.finalize_failed ? 'failed' : toc.finalize_started ? 'in_progress' : 'pending'

  // Count entries by source
  const extractedCount = (toc.entries || []).filter(e => e.source !== 'discovered').length
  const discoveredCount = toc.entries_discovered || 0
  const linkedCount = toc.entries_linked || 0
  const totalCount = toc.entry_count || 0

  return (
    <div className="border-t pt-4">
      {/* Header row */}
      <div className="flex items-center justify-between mb-3">
        <span className="text-sm font-medium text-gray-700">Table of Contents</span>
        <div className="flex items-center space-x-3">
          {toc.cost_usd !== undefined && (
            <span className="font-mono text-sm text-gray-500">
              ${toc.cost_usd.toFixed(4)}
            </span>
          )}
          {toc.found && toc.start_page && (
            <Link
              to="/books/$bookId/pages/$pageNum"
              params={{ bookId, pageNum: String(toc.start_page) }}
              className="text-sm text-blue-600 hover:text-blue-800"
            >
              View ToC Pages
            </Link>
          )}
        </div>
      </div>

      {/* Pipeline Status - horizontal flow */}
      <div className="flex items-center space-x-1 text-xs mb-3">
        <TocStageChip label="Find" status={finderStatus} detail={toc.found ? `p${toc.start_page}-${toc.end_page}` : undefined} />
        <span className="text-gray-300">→</span>
        <TocStageChip label="Extract" status={extractStatus} detail={extractedCount > 0 ? `${extractedCount}` : undefined} />
        <span className="text-gray-300">→</span>
        <TocStageChip label="Link" status={linkStatus} detail={totalCount > 0 ? `${linkedCount}/${totalCount}` : undefined} />
        <span className="text-gray-300">→</span>
        <TocStageChip label="Finalize" status={finalizeStatus} detail={discoveredCount > 0 ? `+${discoveredCount}` : undefined} />
      </div>

      {/* Summary stats */}
      {totalCount > 0 && (
        <div className="flex items-center justify-between bg-gray-50 rounded px-3 py-2 mb-3">
          <div className="flex items-center space-x-4 text-sm">
            <span className="text-gray-600">
              <strong>{totalCount}</strong> entries
            </span>
            <span className="text-gray-600">
              <strong>{linkedCount}</strong> linked ({totalCount > 0 ? Math.round((linkedCount / totalCount) * 100) : 0}%)
            </span>
            {discoveredCount > 0 && (
              <span className="text-green-600">
                <strong>+{discoveredCount}</strong> discovered
              </span>
            )}
          </div>
          <button
            onClick={() => setEntriesExpanded(!entriesExpanded)}
            className="text-sm text-blue-600 hover:text-blue-800 flex items-center space-x-1"
          >
            <span>{entriesExpanded ? 'Hide' : 'Show'} Entries</span>
            <span className={`transition-transform ${entriesExpanded ? 'rotate-180' : ''}`}>▼</span>
          </button>
        </div>
      )}

      {/* Expandable entries list */}
      {entriesExpanded && toc.entries && toc.entries.length > 0 && (
        <div className="border rounded-lg overflow-hidden">
          {/* Table header */}
          <div className="grid grid-cols-12 gap-2 bg-gray-100 px-3 py-2 text-xs font-medium text-gray-600 border-b">
            <div className="col-span-1">#</div>
            <div className="col-span-6">Title</div>
            <div className="col-span-2">Type</div>
            <div className="col-span-1 text-right">Print</div>
            <div className="col-span-2 text-right">Scan Page</div>
          </div>
          {/* Entries */}
          <div className="max-h-96 overflow-y-auto">
            {toc.entries.map((entry, idx) => (
              <TocEntryRow key={idx} entry={entry} bookId={bookId} />
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

// ToC Stage Chip component
function TocStageChip({ label, status, detail }: { label: string; status: 'pending' | 'in_progress' | 'complete' | 'failed'; detail?: string }) {
  const statusStyles = {
    pending: 'bg-gray-100 text-gray-500 border-gray-200',
    in_progress: 'bg-blue-50 text-blue-700 border-blue-200',
    complete: 'bg-green-50 text-green-700 border-green-200',
    failed: 'bg-red-50 text-red-700 border-red-200',
  }

  const statusIcons = {
    pending: '○',
    in_progress: '◐',
    complete: '●',
    failed: '✕',
  }

  return (
    <div className={`px-2 py-1 rounded border ${statusStyles[status]} flex items-center space-x-1`}>
      <span>{statusIcons[status]}</span>
      <span className="font-medium">{label}</span>
      {detail && <span className="text-xs opacity-75">({detail})</span>}
    </div>
  )
}

// Structure Status type
interface StructureStatus {
  started?: boolean
  complete?: boolean
  failed?: boolean
  retries?: number
  cost_usd?: number
  chapter_count?: number
}

// Enhanced Structure Section Component
function StructureSection({ structure, bookId }: { structure?: StructureStatus; bookId: string }) {
  const [expanded, setExpanded] = useState(false)

  // Fetch chapter details when structure is complete
  const { data: chapters } = useQuery({
    queryKey: ['books', bookId, 'chapters'],
    queryFn: async () =>
      unwrap(
        await client.GET('/api/books/{id}/chapters', {
          params: { path: { id: bookId } },
        })
      ),
    enabled: !!structure?.complete,
  })

  if (!structure) return null

  const status = structure.complete
    ? 'complete'
    : structure.failed
    ? 'failed'
    : structure.started
    ? 'in_progress'
    : 'pending'

  // Calculate matter type breakdown from chapters
  const matterBreakdown = chapters?.chapters?.reduce((acc, ch) => {
    const matter = ch.matter_type || 'unknown'
    acc[matter] = (acc[matter] || 0) + 1
    return acc
  }, {} as Record<string, number>) || {}

  // Calculate polish progress
  const polishStats = chapters?.chapters?.reduce(
    (acc, ch) => {
      if (ch.polish_complete) acc.complete++
      else if (ch.polish_failed) acc.failed++
      else acc.pending++
      acc.total++
      return acc
    },
    { complete: 0, failed: 0, pending: 0, total: 0 }
  ) || { complete: 0, failed: 0, pending: 0, total: 0 }

  const hasDetails = chapters && chapters.chapters && chapters.chapters.length > 0

  return (
    <div className="border-t pt-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center space-x-2">
          <span className="text-sm font-medium text-gray-700">Structure</span>
          <StatusBadge status={status} />
        </div>
        <div className="flex items-center space-x-2">
          {structure.chapter_count !== undefined && structure.chapter_count > 0 && (
            <span className="text-gray-600 text-sm">
              {structure.chapter_count} chapters
            </span>
          )}
          {structure.cost_usd !== undefined && structure.cost_usd > 0 && (
            <span className="font-mono text-sm text-gray-500">
              ${structure.cost_usd.toFixed(4)}
            </span>
          )}
          {structure.complete && (
            <Link
              to="/books/$bookId/chapters"
              params={{ bookId }}
              className="text-sm text-blue-600 hover:text-blue-800"
            >
              View Chapters
            </Link>
          )}
        </div>
      </div>

      {/* In-progress message */}
      {structure.started && !structure.complete && !structure.failed && (
        <div className="mt-2 pl-4 text-sm text-gray-500">
          Building unified book structure...
        </div>
      )}

      {/* Completed - show summary */}
      {hasDetails && (
        <div className="mt-3">
          {/* Summary row */}
          <div className="flex items-center justify-between bg-gray-50 rounded px-3 py-2">
            <div className="flex items-center space-x-4 text-sm">
              {/* Matter type breakdown */}
              {Object.entries(matterBreakdown).map(([matter, count]) => (
                <span key={matter} className="flex items-center space-x-1">
                  <MatterTypeBadge type={matter} />
                  <span className="text-gray-600">{count}</span>
                </span>
              ))}
            </div>
            {/* Polish progress */}
            {polishStats.total > 0 && (
              <div className="flex items-center space-x-2 text-sm">
                <span className="text-gray-500">Polish:</span>
                <span className={polishStats.complete === polishStats.total ? 'text-green-600' : 'text-gray-600'}>
                  {polishStats.complete}/{polishStats.total}
                </span>
                {polishStats.failed > 0 && (
                  <span className="text-red-500">({polishStats.failed} failed)</span>
                )}
              </div>
            )}
            <button
              onClick={() => setExpanded(!expanded)}
              className="text-sm text-blue-600 hover:text-blue-800 flex items-center space-x-1"
            >
              <span>{expanded ? 'Hide' : 'Show'} Details</span>
              <span className={`transition-transform ${expanded ? 'rotate-180' : ''}`}>▼</span>
            </button>
          </div>

          {/* Expanded chapter list */}
          {expanded && chapters?.chapters && (
            <div className="border rounded-lg overflow-hidden mt-2">
              <div className="grid grid-cols-12 gap-2 bg-gray-100 px-3 py-2 text-xs font-medium text-gray-600 border-b">
                <div className="col-span-1">#</div>
                <div className="col-span-5">Title</div>
                <div className="col-span-2">Type</div>
                <div className="col-span-2">Pages</div>
                <div className="col-span-2">Polish</div>
              </div>
              <div className="max-h-64 overflow-y-auto">
                {chapters.chapters.map((ch, idx) => (
                  <div
                    key={ch.entry_id || idx}
                    className="grid grid-cols-12 gap-2 px-3 py-2 text-sm border-b last:border-b-0 hover:bg-gray-50"
                  >
                    <div className="col-span-1 font-mono text-xs text-gray-400">
                      {ch.entry_number || idx + 1}
                    </div>
                    <div className="col-span-5 flex items-center">
                      <div style={{ width: `${(ch.level || 0) * 12}px` }} className="flex-shrink-0" />
                      <span className={ch.level === 0 || ch.level === 1 ? 'font-medium' : ''}>
                        {ch.title || 'Untitled'}
                      </span>
                    </div>
                    <div className="col-span-2">
                      <MatterTypeBadge type={ch.matter_type} />
                    </div>
                    <div className="col-span-2 font-mono text-xs text-gray-500">
                      {ch.start_page && ch.end_page ? `${ch.start_page}-${ch.end_page}` : '-'}
                    </div>
                    <div className="col-span-2">
                      {ch.polish_complete ? (
                        <span className="text-green-600 text-xs">● Complete</span>
                      ) : ch.polish_failed ? (
                        <span className="text-red-600 text-xs">✕ Failed</span>
                      ) : (
                        <span className="text-gray-400 text-xs">○ Pending</span>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// Matter type badge component
function MatterTypeBadge({ type }: { type?: string }) {
  const styles: Record<string, string> = {
    front_matter: 'bg-purple-100 text-purple-700',
    body: 'bg-blue-100 text-blue-700',
    back_matter: 'bg-orange-100 text-orange-700',
    unknown: 'bg-gray-100 text-gray-600',
  }
  const labels: Record<string, string> = {
    front_matter: 'Front',
    body: 'Body',
    back_matter: 'Back',
    unknown: '?',
  }
  const key = type || 'unknown'
  return (
    <span className={`text-xs px-1.5 py-0.5 rounded ${styles[key] || styles.unknown}`}>
      {labels[key] || key}
    </span>
  )
}

// Agent Log type
interface AgentLogSummary {
  id?: string
  agent_type?: string
  started_at?: string
  completed_at?: string
  iterations?: number
  success?: boolean
  error?: string
}

// Agent operation categories
const AGENT_CATEGORIES: Record<string, { label: string; agents: string[] }> = {
  toc: {
    label: 'Table of Contents',
    agents: ['toc_finder', 'toc_extract', 'toc_entry_finder'],
  },
  structure: {
    label: 'Structure',
    agents: ['chapter_classifier', 'chapter_polisher', 'common_structure'],
  },
  metadata: {
    label: 'Metadata',
    agents: ['metadata_extract'],
  },
}

function getAgentCategory(agentType: string): string {
  for (const [category, config] of Object.entries(AGENT_CATEGORIES)) {
    if (config.agents.some(a => agentType.toLowerCase().includes(a.toLowerCase()))) {
      return category
    }
  }
  return 'other'
}

function getAgentDisplayName(agentType: string): string {
  const names: Record<string, string> = {
    toc_finder: 'ToC Finder',
    toc_extract: 'ToC Extract',
    toc_entry_finder: 'Entry Finder',
    chapter_classifier: 'Classifier',
    chapter_polisher: 'Polisher',
    metadata_extract: 'Metadata',
    common_structure: 'Structure Build',
  }
  for (const [key, name] of Object.entries(names)) {
    if (agentType.toLowerCase().includes(key.toLowerCase())) {
      return name
    }
  }
  return agentType
}

// Grouped Agent Logs Section
function AgentLogsSection({ logs, onViewLog }: { logs: AgentLogSummary[]; onViewLog: (id: string) => void }) {
  const [expanded, setExpanded] = useState(false)

  // Group logs by category
  const grouped = logs.reduce((acc, log) => {
    const category = getAgentCategory(log.agent_type || '')
    if (!acc[category]) acc[category] = []
    acc[category].push(log)
    return acc
  }, {} as Record<string, AgentLogSummary[]>)

  // Calculate summary stats
  const totalLogs = logs.length
  const successCount = logs.filter(l => l.success).length
  const failCount = totalLogs - successCount
  const totalIterations = logs.reduce((sum, l) => sum + (l.iterations || 0), 0)

  return (
    <div className="border-t pt-4">
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center space-x-3">
          <span className="text-sm font-medium text-gray-700">Agent Operations</span>
          <span className="text-xs text-gray-500">
            {totalLogs} runs
            {failCount > 0 && <span className="text-red-500 ml-1">({failCount} failed)</span>}
          </span>
        </div>
        <button
          onClick={() => setExpanded(!expanded)}
          className="text-sm text-blue-600 hover:text-blue-800 flex items-center space-x-1"
        >
          <span>{expanded ? 'Hide' : 'Show'} Details</span>
          <span className={`transition-transform ${expanded ? 'rotate-180' : ''}`}>▼</span>
        </button>
      </div>

      {/* Summary row */}
      <div className="flex items-center space-x-4 text-xs text-gray-500 mb-2">
        {Object.entries(grouped).map(([category, categoryLogs]) => {
          const catSuccess = categoryLogs.filter(l => l.success).length
          const catTotal = categoryLogs.length
          const categoryConfig = AGENT_CATEGORIES[category]
          return (
            <span key={category} className="flex items-center space-x-1">
              <span className="font-medium">{categoryConfig?.label || category}:</span>
              <span className={catSuccess === catTotal ? 'text-green-600' : 'text-gray-600'}>
                {catSuccess}/{catTotal}
              </span>
            </span>
          )
        })}
        <span>
          <span className="font-medium">Total iterations:</span> {totalIterations}
        </span>
      </div>

      {/* Expanded details */}
      {expanded && (
        <div className="space-y-3">
          {Object.entries(grouped).map(([category, categoryLogs]) => {
            const categoryConfig = AGENT_CATEGORIES[category]
            return (
              <div key={category} className="bg-gray-50 rounded p-3">
                <div className="text-xs font-medium text-gray-600 mb-2">
                  {categoryConfig?.label || category}
                </div>
                <div className="space-y-1">
                  {categoryLogs.map((log) => (
                    <div key={log.id} className="flex items-center justify-between text-sm">
                      <div className="flex items-center space-x-2">
                        <span className={log.success ? 'text-green-600' : 'text-red-600'}>
                          {log.success ? '●' : '✕'}
                        </span>
                        <span className="font-medium">{getAgentDisplayName(log.agent_type || '')}</span>
                        <span className="text-gray-400 text-xs">
                          {log.iterations} iter{(log.iterations || 0) !== 1 ? 's' : ''}
                        </span>
                        {log.error && (
                          <span className="text-red-500 text-xs truncate max-w-xs" title={log.error}>
                            {log.error.slice(0, 30)}...
                          </span>
                        )}
                      </div>
                      <button
                        onClick={() => log.id && onViewLog(log.id)}
                        className="text-xs text-blue-600 hover:text-blue-800"
                      >
                        View
                      </button>
                    </div>
                  ))}
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

// ToC Entry Row component
function TocEntryRow({ entry, bookId }: { entry: TocEntry; bookId: string }) {
  const level = entry.level || 0
  const isDiscovered = entry.source === 'discovered'
  const isLinked = entry.is_linked && entry.actual_page_num

  return (
    <div
      className={`grid grid-cols-12 gap-2 px-3 py-2 text-sm border-b last:border-b-0 hover:bg-gray-50 ${
        isDiscovered ? 'bg-green-50/50' : ''
      }`}
    >
      {/* Entry number */}
      <div className="col-span-1 font-mono text-xs text-gray-400">
        {entry.entry_number || '-'}
      </div>
      {/* Title with indentation */}
      <div className="col-span-6 flex items-center">
        <div style={{ width: `${level * 16}px` }} className="flex-shrink-0" />
        <span className={level === 0 ? 'font-medium' : ''}>
          {entry.title || 'Untitled'}
        </span>
      </div>
      {/* Type badge */}
      <div className="col-span-2">
        <div className="flex items-center space-x-1">
          {entry.level_name && (
            <span className="text-xs text-gray-500">{entry.level_name}</span>
          )}
          {isDiscovered && (
            <span className="text-xs bg-green-100 text-green-700 px-1 rounded">new</span>
          )}
        </div>
      </div>
      {/* Printed page */}
      <div className="col-span-1 text-right font-mono text-gray-500">
        {entry.printed_page_number || '-'}
      </div>
      {/* Scan page */}
      <div className="col-span-2 text-right">
        {isLinked ? (
          <Link
            to="/books/$bookId/pages/$pageNum"
            params={{ bookId, pageNum: String(entry.actual_page_num) }}
            className="font-mono text-blue-600 hover:text-blue-800"
          >
            p.{entry.actual_page_num}
          </Link>
        ) : (
          <span className="text-gray-300">—</span>
        )}
      </div>
    </div>
  )
}
