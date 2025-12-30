import { createFileRoute, Link } from '@tanstack/react-router'
import { useQuery } from '@tanstack/react-query'
import { client, unwrap } from '@/api/client'
import type { components } from '@/api/types'

type ProviderProgress = components['schemas']['github_com_jackzampolin_shelf_internal_jobs.ProviderProgress']

export const Route = createFileRoute('/jobs/$jobId')({
  component: JobDetailPage,
})

function ProgressBar({ completed, total, failed }: { completed: number; total: number; failed: number }) {
  const percentage = total > 0 ? Math.round((completed / total) * 100) : 0
  const failedPercentage = total > 0 ? Math.round((failed / total) * 100) : 0

  return (
    <div className="w-full">
      <div className="flex justify-between text-sm mb-1">
        <span className="text-gray-600">
          {completed} / {total} completed
          {failed > 0 && <span className="text-red-600 ml-2">({failed} failed)</span>}
        </span>
        <span className="text-gray-600">{percentage}%</span>
      </div>
      <div className="w-full bg-gray-200 rounded-full h-3 overflow-hidden">
        <div className="h-full flex">
          <div
            className="bg-green-500 transition-all duration-300"
            style={{ width: `${percentage}%` }}
          />
          {failed > 0 && (
            <div
              className="bg-red-500 transition-all duration-300"
              style={{ width: `${failedPercentage}%` }}
            />
          )}
        </div>
      </div>
    </div>
  )
}

function JobDetailPage() {
  const { jobId } = Route.useParams()

  const { data: job, isLoading, error } = useQuery({
    queryKey: ['jobs', jobId],
    queryFn: async () =>
      unwrap(
        await client.GET('/api/jobs/{id}', {
          params: { path: { id: jobId } },
        })
      ),
    refetchInterval: (query) =>
      query.state.data?.status === 'running' ? 2000 : false,
  })

  if (isLoading) {
    return (
      <div className="text-center py-12">
        <div className="text-gray-500">Loading job...</div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="text-center py-12">
        <div className="text-red-500">Error loading job: {error.message}</div>
      </div>
    )
  }

  if (!job) {
    return (
      <div className="text-center py-12">
        <div className="text-gray-500">Job not found</div>
      </div>
    )
  }

  const getStatusColor = (status: string) => {
    switch (status) {
      case 'completed':
        return 'bg-green-100 text-green-800'
      case 'running':
        return 'bg-blue-100 text-blue-800'
      case 'failed':
        return 'bg-red-100 text-red-800'
      case 'queued':
        return 'bg-yellow-100 text-yellow-800'
      default:
        return 'bg-gray-100 text-gray-800'
    }
  }

  // Calculate overall progress from provider progress
  const calculateOverallProgress = () => {
    if (!job.progress) return null

    let totalCompleted = 0
    let totalExpected = 0
    let totalFailed = 0

    Object.values(job.progress).forEach((p: ProviderProgress) => {
      totalCompleted += (p.completed ?? 0) + (p.completedAtStart ?? 0)
      totalExpected += p.totalExpected ?? 0
      totalFailed += p.failed ?? 0
    })

    if (totalExpected === 0) return null

    return {
      completed: totalCompleted,
      total: totalExpected,
      failed: totalFailed,
      percentage: Math.round((totalCompleted / totalExpected) * 100),
    }
  }

  const overallProgress = calculateOverallProgress()

  return (
    <div className="space-y-6">
      {/* Breadcrumb */}
      <nav className="text-sm">
        <Link to="/jobs" className="text-blue-600 hover:text-blue-800">
          Jobs
        </Link>
        <span className="mx-2 text-gray-400">/</span>
        <span className="text-gray-600 font-mono">{jobId.slice(0, 8)}...</span>
      </nav>

      {/* Header */}
      <div className="flex items-center space-x-4">
        <h1 className="text-2xl font-bold text-gray-900">Job Details</h1>
        <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-sm font-medium ${getStatusColor(job.status ?? '')}`}>
          {job.status}
        </span>
      </div>

      {/* Overall Progress (for running jobs) */}
      {overallProgress && job.status === 'running' && (
        <div className="bg-blue-50 border border-blue-200 rounded-lg p-4">
          <h3 className="text-sm font-medium text-blue-800 mb-2">Overall Progress</h3>
          <ProgressBar
            completed={overallProgress.completed}
            total={overallProgress.total}
            failed={overallProgress.failed}
          />
        </div>
      )}

      {/* Job Info */}
      <div className="bg-white rounded-lg shadow p-6">
        <dl className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div>
            <dt className="text-sm font-medium text-gray-500">ID</dt>
            <dd className="mt-1 text-sm text-gray-900 font-mono">{job._docID}</dd>
          </div>
          <div>
            <dt className="text-sm font-medium text-gray-500">Type</dt>
            <dd className="mt-1 text-sm text-gray-900">{job.job_type}</dd>
          </div>
          <div>
            <dt className="text-sm font-medium text-gray-500">Created</dt>
            <dd className="mt-1 text-sm text-gray-900">
              {job.created_at ? new Date(job.created_at).toLocaleString() : '-'}
            </dd>
          </div>
          <div>
            <dt className="text-sm font-medium text-gray-500">Started</dt>
            <dd className="mt-1 text-sm text-gray-900">
              {job.started_at ? new Date(job.started_at).toLocaleString() : '-'}
            </dd>
          </div>
          {job.completed_at && (
            <div>
              <dt className="text-sm font-medium text-gray-500">Completed</dt>
              <dd className="mt-1 text-sm text-gray-900">
                {new Date(job.completed_at).toLocaleString()}
              </dd>
            </div>
          )}
        </dl>
      </div>

      {/* Error message */}
      {job.error && (
        <div className="bg-red-50 border border-red-200 rounded-lg p-4">
          <h3 className="text-sm font-medium text-red-800">Error</h3>
          <pre className="mt-2 text-sm text-red-700 whitespace-pre-wrap">{job.error}</pre>
        </div>
      )}

      {/* Provider Progress with progress bars */}
      {job.progress && Object.keys(job.progress).length > 0 && (
        <div className="bg-white rounded-lg shadow p-6">
          <h3 className="text-lg font-medium text-gray-900 mb-4">Provider Progress</h3>
          <div className="space-y-6">
            {Object.entries(job.progress).map(([provider, progress]) => {
              const p = progress as ProviderProgress
              const completed = (p.completed ?? 0) + (p.completedAtStart ?? 0)
              const total = p.totalExpected ?? 0
              const failed = p.failed ?? 0
              const queued = p.queued ?? 0

              return (
                <div key={provider} className="border-b pb-4 last:border-0 last:pb-0">
                  <div className="flex justify-between items-center mb-2">
                    <h4 className="font-medium text-gray-700">{provider}</h4>
                    {queued > 0 && (
                      <span className="text-sm text-yellow-600">{queued} queued</span>
                    )}
                  </div>
                  <ProgressBar completed={completed} total={total} failed={failed} />
                </div>
              )
            })}
          </div>
        </div>
      )}

      {/* Live Status (for running jobs) */}
      {job.live_status && Object.keys(job.live_status).length > 0 && (
        <div className="bg-white rounded-lg shadow p-6">
          <h3 className="text-lg font-medium text-gray-900 mb-4">Live Status</h3>
          <dl className="grid grid-cols-2 md:grid-cols-4 gap-4">
            {Object.entries(job.live_status).map(([key, value]) => (
              <div key={key}>
                <dt className="text-sm font-medium text-gray-500">{key}</dt>
                <dd className="mt-1 text-sm text-gray-900">{value}</dd>
              </div>
            ))}
          </dl>
        </div>
      )}

      {/* Worker Status */}
      {job.worker_status && Object.keys(job.worker_status).length > 0 && (
        <div className="bg-white rounded-lg shadow p-6">
          <h3 className="text-lg font-medium text-gray-900 mb-4">Worker Status</h3>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {Object.entries(job.worker_status).map(([worker, status]) => {
              const s = status as { queue_depth?: number; type?: string }
              return (
                <div key={worker} className="bg-gray-50 rounded-lg p-4">
                  <h4 className="font-medium text-gray-700 text-sm">{worker}</h4>
                  <div className="mt-2 text-sm">
                    <span className="text-gray-500">Queue: </span>
                    <span className="font-medium">{s.queue_depth ?? 0}</span>
                  </div>
                </div>
              )
            })}
          </div>
        </div>
      )}

      {/* Metadata */}
      {job.metadata && Object.keys(job.metadata).length > 0 && (
        <div className="bg-white rounded-lg shadow p-6">
          <h3 className="text-lg font-medium text-gray-900 mb-4">Metadata</h3>
          <pre className="text-sm bg-gray-50 p-4 rounded overflow-auto">
            {JSON.stringify(job.metadata, null, 2)}
          </pre>
        </div>
      )}
    </div>
  )
}
