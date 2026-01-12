import { useState } from 'react'
import { Link } from '@tanstack/react-router'
import { useQuery } from '@tanstack/react-query'

interface JobRecord {
  _docID?: string
  job_type?: string
  book_id?: string
  status?: string
  created_at?: string
  started_at?: string
  completed_at?: string
  error?: string
}

interface JobHistorySectionProps {
  bookId: string
}

export function JobHistorySection({ bookId }: JobHistorySectionProps) {
  const [expanded, setExpanded] = useState(false)

  const { data: jobs, isLoading } = useQuery({
    queryKey: ['jobs', 'book', bookId],
    queryFn: async () => {
      const resp = await fetch(`/api/jobs?book_id=${encodeURIComponent(bookId)}`)
      if (!resp.ok) throw new Error('Failed to fetch jobs')
      const data = await resp.json() as { jobs: JobRecord[] }
      return data.jobs || []
    },
    refetchInterval: 10000,
  })

  if (isLoading || !jobs || jobs.length === 0) {
    return null
  }

  // Sort by created_at descending (most recent first)
  const sortedJobs = [...jobs].sort((a, b) => {
    const dateA = a.created_at ? new Date(a.created_at).getTime() : 0
    const dateB = b.created_at ? new Date(b.created_at).getTime() : 0
    return dateB - dateA
  })

  return (
    <div className="bg-white rounded-lg shadow p-6">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-lg font-medium text-gray-900">Job History</h3>
        <button
          onClick={() => setExpanded(!expanded)}
          className="text-sm text-blue-600 hover:text-blue-800 flex items-center space-x-1"
        >
          <span>{expanded ? 'Collapse' : 'Show All'}</span>
          <span className={`transition-transform ${expanded ? 'rotate-180' : ''}`}>
            &#9660;
          </span>
        </button>
      </div>

      <div className="space-y-2">
        {(expanded ? sortedJobs : sortedJobs.slice(0, 5)).map((job) => (
          <JobRow key={job._docID} job={job} />
        ))}
      </div>

      {!expanded && sortedJobs.length > 5 && (
        <div className="mt-2 text-sm text-gray-500 text-center">
          ... and {sortedJobs.length - 5} more jobs
        </div>
      )}
    </div>
  )
}

function JobRow({ job }: { job: JobRecord }) {
  const statusColors: Record<string, string> = {
    queued: 'bg-gray-100 text-gray-700',
    running: 'bg-blue-100 text-blue-700',
    completed: 'bg-green-100 text-green-700',
    failed: 'bg-red-100 text-red-700',
    cancelled: 'bg-orange-100 text-orange-700',
  }

  const duration = calculateDuration(job.started_at, job.completed_at)
  const createdAt = job.created_at ? formatTimestamp(job.created_at) : '-'

  return (
    <div className="flex items-center justify-between py-2 px-3 bg-gray-50 rounded">
      <div className="flex items-center space-x-3">
        <span className={`px-2 py-0.5 rounded text-xs font-medium ${statusColors[job.status || 'queued']}`}>
          {job.status || 'unknown'}
        </span>
        <span className="text-sm font-medium text-gray-700">
          {formatJobType(job.job_type || '')}
        </span>
      </div>
      <div className="flex items-center space-x-4 text-sm text-gray-500">
        {duration && (
          <span className="font-mono" title="Duration">
            {duration}
          </span>
        )}
        <span className="text-xs" title="Created at">
          {createdAt}
        </span>
        {job._docID && (
          <Link
            to="/jobs/$jobId"
            params={{ jobId: job._docID }}
            className="text-blue-600 hover:text-blue-800 text-xs"
          >
            View
          </Link>
        )}
      </div>
    </div>
  )
}

function formatJobType(jobType: string): string {
  const labels: Record<string, string> = {
    'process-book': 'Full Pipeline',
    'ocr-book': 'OCR + Blend',
    'label-book': 'Label Pages',
    'metadata-book': 'Metadata',
    'toc-book': 'ToC Extract',
    'link-toc': 'Link ToC',
    'finalize-toc': 'Finalize ToC',
    'common-structure': 'Structure',
  }
  return labels[jobType] || jobType
}

function calculateDuration(startedAt?: string, completedAt?: string): string | null {
  if (!startedAt) return null

  const start = new Date(startedAt)
  const end = completedAt ? new Date(completedAt) : new Date()
  const durationMs = end.getTime() - start.getTime()

  if (durationMs < 0) return null

  const seconds = Math.floor(durationMs / 1000)
  const minutes = Math.floor(seconds / 60)
  const hours = Math.floor(minutes / 60)

  if (hours > 0) {
    return `${hours}h ${minutes % 60}m`
  } else if (minutes > 0) {
    return `${minutes}m ${seconds % 60}s`
  } else {
    return `${seconds}s`
  }
}

function formatTimestamp(timestamp: string): string {
  const date = new Date(timestamp)
  const now = new Date()
  const diffMs = now.getTime() - date.getTime()
  const diffMins = Math.floor(diffMs / 60000)
  const diffHours = Math.floor(diffMins / 60)
  const diffDays = Math.floor(diffHours / 24)

  if (diffMins < 1) return 'just now'
  if (diffMins < 60) return `${diffMins}m ago`
  if (diffHours < 24) return `${diffHours}h ago`
  if (diffDays < 7) return `${diffDays}d ago`

  return date.toLocaleDateString()
}
