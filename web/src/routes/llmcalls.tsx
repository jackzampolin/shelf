import { useState } from 'react'
import { createFileRoute, Link } from '@tanstack/react-router'
import { useQuery } from '@tanstack/react-query'

interface LLMCall {
  id: string
  timestamp: string
  latency_ms: number
  book_id?: string
  page_id?: string
  job_id?: string
  prompt_key: string
  prompt_cid?: string
  provider: string
  model: string
  temperature?: number
  input_tokens: number
  output_tokens: number
  response: string
  tool_calls?: Record<string, unknown>
  success: boolean
  error_message?: string
}

interface LLMCallsResponse {
  calls: LLMCall[]
  total: number
}

export const Route = createFileRoute('/llmcalls')({
  component: LLMCallsPage,
})

function LLMCallsPage() {
  const [filters, setFilters] = useState({
    book_id: '',
    job_id: '',
    prompt_key: '',
    provider: '',
    success: '',
    limit: 50,
  })
  const [selectedCall, setSelectedCall] = useState<LLMCall | null>(null)

  // Build query params
  const queryParams = new URLSearchParams()
  if (filters.book_id) queryParams.set('book_id', filters.book_id)
  if (filters.job_id) queryParams.set('job_id', filters.job_id)
  if (filters.prompt_key) queryParams.set('prompt_key', filters.prompt_key)
  if (filters.provider) queryParams.set('provider', filters.provider)
  if (filters.success) queryParams.set('success', filters.success)
  queryParams.set('limit', filters.limit.toString())

  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ['llmcalls', filters],
    queryFn: async (): Promise<LLMCallsResponse> => {
      const res = await fetch(`/api/llmcalls?${queryParams.toString()}`)
      if (!res.ok) throw new Error('Failed to load LLM calls')
      return res.json()
    },
  })

  if (isLoading) {
    return (
      <div className="text-center py-12">
        <div className="text-gray-500">Loading LLM calls...</div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="bg-red-50 border border-red-200 rounded-lg p-4">
        <p className="text-red-700">Error loading LLM calls: {(error as Error).message}</p>
        <button
          onClick={() => refetch()}
          className="mt-2 text-red-600 hover:text-red-800 text-sm underline"
        >
          Retry
        </button>
      </div>
    )
  }

  const calls = data?.calls || []

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex justify-between items-center">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">LLM Call History</h1>
          <p className="text-gray-600 text-sm mt-1">
            {data?.total || 0} calls recorded
          </p>
        </div>
        <button
          onClick={() => refetch()}
          className="px-4 py-2 text-sm font-medium text-gray-700 bg-white border border-gray-300 rounded-lg hover:bg-gray-50"
        >
          Refresh
        </button>
      </div>

      {/* Filters */}
      <div className="bg-white border rounded-lg p-4">
        <div className="grid grid-cols-2 md:grid-cols-6 gap-4">
          <div>
            <label className="block text-xs font-medium text-gray-500 mb-1">Book ID</label>
            <input
              type="text"
              value={filters.book_id}
              onChange={(e) => setFilters({ ...filters, book_id: e.target.value })}
              placeholder="Filter by book"
              className="w-full px-3 py-1.5 text-sm border rounded-md"
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-500 mb-1">Job ID</label>
            <input
              type="text"
              value={filters.job_id}
              onChange={(e) => setFilters({ ...filters, job_id: e.target.value })}
              placeholder="Filter by job"
              className="w-full px-3 py-1.5 text-sm border rounded-md"
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-500 mb-1">Prompt Key</label>
            <input
              type="text"
              value={filters.prompt_key}
              onChange={(e) => setFilters({ ...filters, prompt_key: e.target.value })}
              placeholder="e.g., stages.blend"
              className="w-full px-3 py-1.5 text-sm border rounded-md"
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-500 mb-1">Provider</label>
            <input
              type="text"
              value={filters.provider}
              onChange={(e) => setFilters({ ...filters, provider: e.target.value })}
              placeholder="e.g., openrouter"
              className="w-full px-3 py-1.5 text-sm border rounded-md"
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-500 mb-1">Status</label>
            <select
              value={filters.success}
              onChange={(e) => setFilters({ ...filters, success: e.target.value })}
              className="w-full px-3 py-1.5 text-sm border rounded-md"
            >
              <option value="">All</option>
              <option value="true">Success</option>
              <option value="false">Failed</option>
            </select>
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-500 mb-1">Limit</label>
            <select
              value={filters.limit}
              onChange={(e) => setFilters({ ...filters, limit: parseInt(e.target.value) })}
              className="w-full px-3 py-1.5 text-sm border rounded-md"
            >
              <option value={25}>25</option>
              <option value={50}>50</option>
              <option value={100}>100</option>
              <option value={200}>200</option>
            </select>
          </div>
        </div>
      </div>

      {/* Calls Table */}
      <div className="bg-white border rounded-lg overflow-hidden">
        <table className="min-w-full divide-y divide-gray-200">
          <thead className="bg-gray-50">
            <tr>
              <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Timestamp</th>
              <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Prompt Key</th>
              <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Provider</th>
              <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Model</th>
              <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">Tokens</th>
              <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">Latency</th>
              <th className="px-4 py-3 text-center text-xs font-medium text-gray-500 uppercase">Status</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-200">
            {calls.map((call) => (
              <tr
                key={call.id}
                onClick={() => setSelectedCall(call)}
                className="hover:bg-gray-50 cursor-pointer"
              >
                <td className="px-4 py-3 text-sm text-gray-900">
                  {new Date(call.timestamp).toLocaleString()}
                </td>
                <td className="px-4 py-3">
                  <span className="text-sm font-mono text-blue-600">{call.prompt_key || '-'}</span>
                </td>
                <td className="px-4 py-3 text-sm text-gray-600">{call.provider}</td>
                <td className="px-4 py-3 text-sm text-gray-600 font-mono text-xs">{call.model}</td>
                <td className="px-4 py-3 text-sm text-gray-600 text-right">
                  {call.input_tokens + call.output_tokens}
                  <span className="text-gray-400 text-xs ml-1">
                    ({call.input_tokens}+{call.output_tokens})
                  </span>
                </td>
                <td className="px-4 py-3 text-sm text-gray-600 text-right">
                  {(call.latency_ms / 1000).toFixed(2)}s
                </td>
                <td className="px-4 py-3 text-center">
                  {call.success ? (
                    <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-green-100 text-green-800">
                      OK
                    </span>
                  ) : (
                    <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-red-100 text-red-800">
                      Error
                    </span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>

        {calls.length === 0 && (
          <div className="text-center py-12 text-gray-500">
            No LLM calls found matching the filters
          </div>
        )}
      </div>

      {/* Detail Modal */}
      {selectedCall && (
        <div className="fixed inset-0 z-50 overflow-y-auto">
          <div className="flex items-center justify-center min-h-screen px-4">
            <div
              className="fixed inset-0 bg-gray-500 bg-opacity-75"
              onClick={() => setSelectedCall(null)}
            />
            <div className="relative bg-white rounded-lg max-w-4xl w-full max-h-[90vh] overflow-hidden shadow-xl">
              <div className="sticky top-0 bg-white border-b px-6 py-4 flex justify-between items-center">
                <h2 className="text-lg font-semibold">LLM Call Details</h2>
                <button
                  onClick={() => setSelectedCall(null)}
                  className="text-gray-400 hover:text-gray-600"
                >
                  <svg className="w-6 h-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                  </svg>
                </button>
              </div>
              <div className="overflow-y-auto max-h-[calc(90vh-120px)] p-6 space-y-6">
                {/* Metadata */}
                <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                  <div>
                    <dt className="text-xs font-medium text-gray-500">Timestamp</dt>
                    <dd className="text-sm">{new Date(selectedCall.timestamp).toLocaleString()}</dd>
                  </div>
                  <div>
                    <dt className="text-xs font-medium text-gray-500">Prompt Key</dt>
                    <dd className="text-sm font-mono text-blue-600">{selectedCall.prompt_key || '-'}</dd>
                  </div>
                  <div>
                    <dt className="text-xs font-medium text-gray-500">Provider</dt>
                    <dd className="text-sm">{selectedCall.provider}</dd>
                  </div>
                  <div>
                    <dt className="text-xs font-medium text-gray-500">Model</dt>
                    <dd className="text-sm font-mono">{selectedCall.model}</dd>
                  </div>
                  <div>
                    <dt className="text-xs font-medium text-gray-500">Input Tokens</dt>
                    <dd className="text-sm">{selectedCall.input_tokens}</dd>
                  </div>
                  <div>
                    <dt className="text-xs font-medium text-gray-500">Output Tokens</dt>
                    <dd className="text-sm">{selectedCall.output_tokens}</dd>
                  </div>
                  <div>
                    <dt className="text-xs font-medium text-gray-500">Latency</dt>
                    <dd className="text-sm">{(selectedCall.latency_ms / 1000).toFixed(2)}s</dd>
                  </div>
                  <div>
                    <dt className="text-xs font-medium text-gray-500">Status</dt>
                    <dd className="text-sm">
                      {selectedCall.success ? (
                        <span className="text-green-600">Success</span>
                      ) : (
                        <span className="text-red-600">Error</span>
                      )}
                    </dd>
                  </div>
                </div>

                {/* Links */}
                {(selectedCall.book_id || selectedCall.job_id) && (
                  <div className="flex gap-4">
                    {selectedCall.book_id && (
                      <Link
                        to="/books/$bookId"
                        params={{ bookId: selectedCall.book_id }}
                        className="text-sm text-blue-600 hover:underline"
                        onClick={() => setSelectedCall(null)}
                      >
                        View Book
                      </Link>
                    )}
                    {selectedCall.job_id && (
                      <Link
                        to="/jobs/$jobId"
                        params={{ jobId: selectedCall.job_id }}
                        className="text-sm text-blue-600 hover:underline"
                        onClick={() => setSelectedCall(null)}
                      >
                        View Job
                      </Link>
                    )}
                  </div>
                )}

                {selectedCall.error_message ? (
                  <div className="bg-red-50 border border-red-200 rounded-lg p-4">
                    <h3 className="text-sm font-medium text-red-800 mb-2">Error</h3>
                    <pre className="text-sm text-red-700 whitespace-pre-wrap">{selectedCall.error_message}</pre>
                  </div>
                ) : null}

                {/* Response */}
                <div>
                  <h3 className="text-sm font-medium text-gray-700 mb-2">Response</h3>
                  <pre className="bg-gray-50 border rounded-lg p-4 text-sm whitespace-pre-wrap overflow-x-auto max-h-96">
                    {selectedCall.response}
                  </pre>
                </div>

                {/* Tool Calls */}
                {selectedCall.tool_calls && (
                  <div>
                    <h3 className="text-sm font-medium text-gray-700 mb-2">Tool Calls</h3>
                    <pre className="bg-gray-50 border rounded-lg p-4 text-sm whitespace-pre-wrap overflow-x-auto">
                      {JSON.stringify(selectedCall.tool_calls, null, 2)}
                    </pre>
                  </div>
                )}
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
