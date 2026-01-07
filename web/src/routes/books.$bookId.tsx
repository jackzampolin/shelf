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
  // Check if we're on a child route (pages list, page viewer, or prompts)
  const isChildRoute = pathname.includes('/pages') || pathname.includes('/prompts')

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
  const [tocModalOpen, setTocModalOpen] = useState(false)
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
            >
              {detailedStatus.ocr_progress && Object.entries(detailedStatus.ocr_progress).length > 0 ? (
                <div className="space-y-2 mt-2 pl-4 border-l-2 border-gray-200">
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
                <p className="text-sm text-gray-400 mt-2 pl-4">No OCR results yet</p>
              )}
            </CollapsibleSection>

            {/* Blend Section */}
            <CollapsibleSection
              title="Blend"
              current={detailedStatus.stages?.blend?.complete || 0}
              total={detailedStatus.stages?.blend?.total || 0}
              cost={detailedStatus.stages?.blend?.cost_usd}
            >
              <div className="mt-2 pl-4 border-l-2 border-gray-200">
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
            >
              <div className="mt-2 pl-4 border-l-2 border-gray-200">
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
            <div className="border-t pt-4">
              <div className="flex items-center justify-between">
                <span className="text-sm font-medium text-gray-700">Table of Contents</span>
                <div className="flex items-center space-x-2">
                  {detailedStatus.toc?.cost_usd !== undefined && (
                    <span className="font-mono text-sm text-gray-500">
                      ${detailedStatus.toc.cost_usd.toFixed(4)}
                    </span>
                  )}
                </div>
              </div>
              <div className="mt-2 pl-4 space-y-1 text-sm">
                <div className="flex items-center space-x-2">
                  <span className="text-gray-500">Finder:</span>
                  <StatusBadge
                    status={
                      detailedStatus.toc?.finder_complete
                        ? 'complete'
                        : detailedStatus.toc?.finder_failed
                        ? 'failed'
                        : detailedStatus.toc?.finder_started
                        ? 'in_progress'
                        : 'pending'
                    }
                  />
                  {detailedStatus.toc?.found && (
                    <span className="text-green-600">
                      Found (pages {detailedStatus.toc.start_page}-{detailedStatus.toc.end_page})
                    </span>
                  )}
                </div>
                <div className="flex items-center space-x-2">
                  <span className="text-gray-500">Extract:</span>
                  <StatusBadge
                    status={
                      detailedStatus.toc?.extract_complete
                        ? 'complete'
                        : detailedStatus.toc?.extract_failed
                        ? 'failed'
                        : detailedStatus.toc?.extract_started
                        ? 'in_progress'
                        : 'pending'
                    }
                  />
                  {detailedStatus.toc?.entry_count !== undefined && detailedStatus.toc.entry_count > 0 && (
                    <span className="text-gray-600">
                      {detailedStatus.toc.entry_count} entries
                    </span>
                  )}
                </div>
                <div className="flex items-center space-x-2">
                  <span className="text-gray-500">Link:</span>
                  <StatusBadge
                    status={
                      detailedStatus.toc?.link_complete
                        ? 'complete'
                        : detailedStatus.toc?.link_failed
                        ? 'failed'
                        : detailedStatus.toc?.link_started
                        ? 'in_progress'
                        : 'pending'
                    }
                  />
                  {detailedStatus.toc?.entry_count !== undefined && detailedStatus.toc.entry_count > 0 && (
                    <span className="text-gray-600">
                      {detailedStatus.toc.entries_linked ?? 0} of {detailedStatus.toc.entry_count} linked
                    </span>
                  )}
                </div>
                <div className="flex items-center space-x-4">
                  {detailedStatus.toc?.found && detailedStatus.toc?.start_page && (
                    <Link
                      to="/books/$bookId/pages/$pageNum"
                      params={{ bookId, pageNum: String(detailedStatus.toc.start_page) }}
                      className="text-blue-600 hover:text-blue-800"
                    >
                      View ToC Pages
                    </Link>
                  )}
                  {detailedStatus.toc?.extract_complete && detailedStatus.toc?.entries && detailedStatus.toc.entries.length > 0 && (
                    <button
                      onClick={() => setTocModalOpen(true)}
                      className="text-blue-600 hover:text-blue-800"
                    >
                      View Entries
                    </button>
                  )}
                </div>
              </div>
            </div>

            {/* Agent Logs Section */}
            {detailedStatus.agent_logs && detailedStatus.agent_logs.length > 0 && (
              <div className="border-t pt-4">
                <div className="flex items-center justify-between mb-2">
                  <span className="text-sm font-medium text-gray-700">Agent Logs</span>
                </div>
                <div className="space-y-2 pl-4">
                  {detailedStatus.agent_logs.map((log) => (
                    <div key={log.id} className="flex items-center justify-between text-sm">
                      <div className="flex items-center space-x-2">
                        <span className="font-medium">{log.agent_type}</span>
                        <StatusBadge status={log.success ? 'complete' : 'failed'} />
                        <span className="text-gray-400">
                          {log.iterations} iteration{log.iterations !== 1 ? 's' : ''}
                        </span>
                      </div>
                      <button
                        onClick={() => {
                          setSelectedAgentLogId(log.id || null)
                          setAgentLogModalOpen(true)
                        }}
                        className="text-blue-600 hover:text-blue-800"
                      >
                        View Log
                      </button>
                    </div>
                  ))}
                </div>
              </div>
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

      {/* ToC Modal */}
      {tocModalOpen && detailedStatus?.toc?.entries && (
        <Modal title="Table of Contents" onClose={() => setTocModalOpen(false)}>
          <div className="space-y-2 max-h-96 overflow-y-auto">
            {detailedStatus.toc.entries.map((entry, idx) => (
              <div
                key={idx}
                className="flex items-center justify-between text-sm py-1"
                style={{ paddingLeft: `${(entry.level || 0) * 16}px` }}
              >
                <div className="flex items-center space-x-2">
                  {entry.entry_number && (
                    <span className="text-gray-400 font-mono text-xs">{entry.entry_number}</span>
                  )}
                  <span className={entry.level === 0 ? 'font-medium' : ''}>{entry.title}</span>
                  {entry.level_name && (
                    <span className="text-xs text-gray-400">({entry.level_name})</span>
                  )}
                </div>
                <div className="flex items-center space-x-2">
                  {entry.printed_page_number && (
                    <span className="text-gray-500 font-mono">{entry.printed_page_number}</span>
                  )}
                  {entry.is_linked && entry.actual_page_num ? (
                    <Link
                      to="/books/$bookId/pages/$pageNum"
                      params={{ bookId, pageNum: String(entry.actual_page_num) }}
                      className="text-blue-600 hover:text-blue-800 font-mono text-xs"
                    >
                      → p.{entry.actual_page_num}
                    </Link>
                  ) : (
                    <span className="text-gray-300 font-mono text-xs">—</span>
                  )}
                </div>
              </div>
            ))}
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

function CollapsibleSection({
  title,
  current,
  total,
  cost,
  children,
}: {
  title: string
  current: number
  total: number
  cost?: number
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
      {isOpen && children}
    </div>
  )
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
