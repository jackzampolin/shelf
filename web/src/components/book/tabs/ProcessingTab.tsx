import { useState } from 'react'
import { useMutation, useQueryClient, useQuery } from '@tanstack/react-query'
import { useNavigate } from '@tanstack/react-router'
import { Menu, MenuButton, MenuItem, MenuItems } from '@headlessui/react'
import { client, unwrap } from '@/api/client'
import { ProgressBar } from '@/components/ui'
import {
  CollapsibleSection,
  TocSection,
  StructureSection,
  AgentLogModal,
  MetadataModal,
  JobHistorySection,
} from '@/components/book'
import { useDetailedStatus, useDetailedMetrics, type BookData } from './useBookData'

interface ProcessingTabProps {
  bookId: string
  book: BookData
}

const JOB_TYPES = [
  { id: 'process-book', label: 'Full Pipeline', description: 'OCR → Metadata → ToC → Structure', force: false },
  { id: 'ocr-book', label: 'OCR Only', description: 'OCR all pages', force: false },
  { id: 'metadata-book', label: 'Metadata Only', description: 'Extract book metadata', force: false },
  { id: 'toc-book', label: 'ToC Only', description: 'Find and extract table of contents', force: false },
  { id: 'link-toc', label: 'Link ToC Only', description: 'Link ToC entries to actual pages', force: false },
  { id: 'link-toc', label: 'Link ToC (Force)', description: 'Re-link ToC entries', force: true },
]

interface AgentLogDetail {
  agent_type?: string
  iterations?: number
  success?: boolean
  started_at?: string
  error?: string
  result?: unknown
  messages?: unknown
  tool_calls?: unknown
}

export function ProcessingTab({ bookId, book }: ProcessingTabProps) {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [metadataModalOpen, setMetadataModalOpen] = useState(false)
  const [agentLogModalOpen, setAgentLogModalOpen] = useState(false)
  const [selectedAgentLogId, setSelectedAgentLogId] = useState<string | null>(null)

  const { data: detailedStatus } = useDetailedStatus(bookId)
  const { data: detailedMetrics } = useDetailedMetrics(bookId)

  const { data: agentLogDetail } = useQuery({
    queryKey: ['agent-logs', selectedAgentLogId],
    queryFn: async () =>
      selectedAgentLogId
        ? (unwrap(
            await client.GET('/api/agent-logs/{id}', {
              params: { path: { id: selectedAgentLogId } },
            })
          ) as AgentLogDetail)
        : null,
    enabled: !!selectedAgentLogId,
  })

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

  const handleViewAgentLog = (id: string) => {
    setSelectedAgentLogId(id)
    setAgentLogModalOpen(true)
  }

  return (
    <div className="space-y-6">
      {/* Actions Header */}
      <div className="bg-white border rounded-lg p-4">
        <div className="flex items-center justify-between">
          <div>
            <h3 className="text-lg font-medium text-gray-900">Processing Actions</h3>
            <p className="text-sm text-gray-500">Start or restart processing jobs for this book</p>
          </div>
          {book.status !== 'error' && (
            <div className="flex items-center">
              <button
                onClick={() => startJobMutation.mutate({ jobType: 'process-book' })}
                disabled={startJobMutation.isPending}
                className="inline-flex items-center px-4 py-2 border border-transparent text-sm font-medium rounded-l-md shadow-sm text-white bg-blue-600 hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {startJobMutation.isPending ? 'Starting...' : 'Start Full Pipeline'}
              </button>
              <Menu as="div" className="relative">
                <MenuButton
                  disabled={startJobMutation.isPending}
                  className="inline-flex items-center px-2 py-2 border border-transparent text-sm font-medium rounded-r-md shadow-sm text-white bg-blue-600 hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed border-l border-blue-500"
                >
                  <svg className="h-5 w-5" viewBox="0 0 20 20" fill="currentColor">
                    <path
                      fillRule="evenodd"
                      d="M5.293 7.293a1 1 0 011.414 0L10 10.586l3.293-3.293a1 1 0 111.414 1.414l-4 4a1 1 0 01-1.414 0l-4-4a1 1 0 010-1.414z"
                      clipRule="evenodd"
                    />
                  </svg>
                </MenuButton>
                <MenuItems className="absolute right-0 z-10 mt-2 w-64 origin-top-right rounded-md bg-white shadow-lg ring-1 ring-black ring-opacity-5">
                  <div className="py-1">
                    {JOB_TYPES.map((job, index) => (
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

      {/* Processing Pipeline */}
      {detailedStatus && (
        <div className="bg-white border rounded-lg p-6">
          <h3 className="text-lg font-medium text-gray-900 mb-4">Pipeline Status</h3>
          <div className="space-y-4">
            {/* OCR Section */}
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
                    <ProgressBar label="Pages" current={progress.complete || 0} total={progress.total || 0} />
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

            {/* Metadata Section */}
            <div className="border-t pt-4">
              <div className="flex items-center justify-between">
                <div className="flex items-center space-x-2">
                  <span className="text-sm font-medium text-gray-700">Metadata</span>
                  <StatusIndicator
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
              onViewAgentLog={handleViewAgentLog}
            />

            {/* Structure Section */}
            <StructureSection structure={detailedStatus.structure} bookId={bookId} metrics={detailedMetrics?.stages} />
          </div>
        </div>
      )}

      {/* Job History */}
      <JobHistorySection bookId={bookId} />

      {/* Metadata Modal */}
      {metadataModalOpen && detailedStatus?.metadata?.data && (
        <MetadataModal data={detailedStatus.metadata.data} onClose={() => setMetadataModalOpen(false)} />
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

function StatusIndicator({ status }: { status: 'pending' | 'in_progress' | 'complete' | 'failed' }) {
  const styles = {
    pending: 'bg-gray-100 text-gray-500',
    in_progress: 'bg-blue-100 text-blue-700',
    complete: 'bg-green-100 text-green-700',
    failed: 'bg-red-100 text-red-700',
  }

  const icons = {
    pending: '○',
    in_progress: '◐',
    complete: '●',
    failed: '✕',
  }

  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${styles[status]}`}>
      <span className="mr-1">{icons[status]}</span>
      {status.replace('_', ' ')}
    </span>
  )
}
