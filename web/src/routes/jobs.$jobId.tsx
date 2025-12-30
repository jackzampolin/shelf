import { createFileRoute, Link } from '@tanstack/react-router'
import { useQuery } from '@tanstack/react-query'
import { client, unwrap } from '@/api/client'

export const Route = createFileRoute('/jobs/$jobId')({
  component: JobDetailPage,
})

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
      case 'pending':
        return 'bg-yellow-100 text-yellow-800'
      default:
        return 'bg-gray-100 text-gray-800'
    }
  }

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
        </dl>
      </div>

      {/* Error message */}
      {job.error && (
        <div className="bg-red-50 border border-red-200 rounded-lg p-4">
          <h3 className="text-sm font-medium text-red-800">Error</h3>
          <pre className="mt-2 text-sm text-red-700 whitespace-pre-wrap">{job.error}</pre>
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

      {/* Provider Progress */}
      {job.progress && Object.keys(job.progress).length > 0 && (
        <div className="bg-white rounded-lg shadow p-6">
          <h3 className="text-lg font-medium text-gray-900 mb-4">Provider Progress</h3>
          <div className="space-y-4">
            {Object.entries(job.progress).map(([provider, progress]) => (
              <div key={provider} className="border-b pb-4 last:border-0">
                <h4 className="font-medium text-gray-700">{provider}</h4>
                <dl className="mt-2 grid grid-cols-3 gap-2 text-sm">
                  <div>
                    <dt className="text-gray-500">Completed</dt>
                    <dd className="font-medium">{(progress as any).completed || 0}</dd>
                  </div>
                  <div>
                    <dt className="text-gray-500">Failed</dt>
                    <dd className="font-medium text-red-600">{(progress as any).failed || 0}</dd>
                  </div>
                  <div>
                    <dt className="text-gray-500">Total</dt>
                    <dd className="font-medium">{(progress as any).total || 0}</dd>
                  </div>
                </dl>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Worker Status */}
      {job.worker_status && Object.keys(job.worker_status).length > 0 && (
        <div className="bg-white rounded-lg shadow p-6">
          <h3 className="text-lg font-medium text-gray-900 mb-4">Worker Status</h3>
          <div className="space-y-4">
            {Object.entries(job.worker_status).map(([worker, status]) => (
              <div key={worker} className="border-b pb-4 last:border-0">
                <h4 className="font-medium text-gray-700">{worker}</h4>
                <dl className="mt-2 grid grid-cols-2 gap-2 text-sm">
                  <div>
                    <dt className="text-gray-500">Queue Depth</dt>
                    <dd className="font-medium">{(status as any).queue_depth || 0}</dd>
                  </div>
                  <div>
                    <dt className="text-gray-500">Active Workers</dt>
                    <dd className="font-medium">{(status as any).active_workers || 0}</dd>
                  </div>
                </dl>
              </div>
            ))}
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
