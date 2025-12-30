import { useState } from 'react'
import { createFileRoute, Link } from '@tanstack/react-router'
import { useQuery } from '@tanstack/react-query'
import { client, unwrap } from '@/api/client'

export const Route = createFileRoute('/jobs')({
  component: JobsPage,
})

function JobsPage() {
  const [showFinished, setShowFinished] = useState(false)

  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ['jobs'],
    queryFn: async () => unwrap(await client.GET('/api/jobs')),
    refetchInterval: 5000,
  })

  if (isLoading) {
    return (
      <div className="text-center py-12">
        <div className="text-gray-500">Loading jobs...</div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="text-center py-12">
        <div className="text-red-500">Error loading jobs: {error.message}</div>
      </div>
    )
  }

  const allJobs = data?.jobs || []

  // Sort by created_at descending (most recent first)
  const sortedJobs = [...allJobs].sort((a, b) => {
    const dateA = a.created_at ? new Date(a.created_at).getTime() : 0
    const dateB = b.created_at ? new Date(b.created_at).getTime() : 0
    return dateB - dateA
  })

  // Filter out completed/failed jobs unless toggle is on
  const jobs = showFinished
    ? sortedJobs
    : sortedJobs.filter((job) => job.status !== 'completed' && job.status !== 'failed')

  const finishedCount = sortedJobs.filter(
    (job) => job.status === 'completed' || job.status === 'failed'
  ).length

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

  return (
    <div className="space-y-6">
      <div className="flex justify-between items-center">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Jobs</h1>
          <p className="text-gray-500">
            {jobs.length} active jobs
            {finishedCount > 0 && !showFinished && (
              <span className="text-gray-400"> ({finishedCount} finished hidden)</span>
            )}
          </p>
        </div>
        <div className="flex items-center space-x-4">
          <label className="flex items-center space-x-2 text-sm text-gray-600">
            <input
              type="checkbox"
              checked={showFinished}
              onChange={(e) => setShowFinished(e.target.checked)}
              className="rounded border-gray-300 text-blue-600 focus:ring-blue-500"
            />
            <span>Show finished</span>
          </label>
          <button
            onClick={() => refetch()}
            className="inline-flex items-center px-3 py-2 border border-gray-300 shadow-sm text-sm font-medium rounded-md text-gray-700 bg-white hover:bg-gray-50"
          >
            Refresh
          </button>
        </div>
      </div>

      {jobs.length === 0 ? (
        <div className="bg-white rounded-lg shadow p-12 text-center">
          <p className="text-gray-500">
            {showFinished ? 'No jobs yet.' : 'No active jobs.'}
          </p>
          <p className="text-sm text-gray-400 mt-2">
            {showFinished
              ? 'Start processing a book to create jobs.'
              : finishedCount > 0
              ? 'Toggle "Show finished" to see completed jobs.'
              : 'Start processing a book to create jobs.'}
          </p>
        </div>
      ) : (
        <div className="bg-white rounded-lg shadow overflow-hidden">
          <table className="min-w-full divide-y divide-gray-200">
            <thead className="bg-gray-50">
              <tr>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                  ID
                </th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                  Type
                </th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                  Status
                </th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                  Created
                </th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                  Actions
                </th>
              </tr>
            </thead>
            <tbody className="bg-white divide-y divide-gray-200">
              {jobs.map((job) => {
                const jobId = job._docID ?? ''
                return (
                  <tr key={jobId} className="hover:bg-gray-50">
                    <td className="px-6 py-4 whitespace-nowrap">
                      <Link
                        to="/jobs/$jobId"
                        params={{ jobId }}
                        className="text-blue-600 hover:text-blue-800 font-mono text-sm"
                      >
                        {jobId.slice(0, 8)}...
                      </Link>
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                      {job.job_type}
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap">
                      <span
                        className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${getStatusColor(job.status ?? '')}`}
                      >
                        {job.status}
                      </span>
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                      {job.created_at ? new Date(job.created_at).toLocaleString() : '-'}
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap text-sm">
                      <Link
                        to="/jobs/$jobId"
                        params={{ jobId }}
                        className="text-blue-600 hover:text-blue-800"
                      >
                        View
                      </Link>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
