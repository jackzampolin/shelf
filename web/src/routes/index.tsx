import { createFileRoute } from '@tanstack/react-router'
import { useQuery } from '@tanstack/react-query'
import { client, unwrap } from '@/api/client'

export const Route = createFileRoute('/')({
  component: Dashboard,
})

function Dashboard() {
  const {
    data: health,
    isLoading: healthLoading,
    error: healthError,
  } = useQuery({
    queryKey: ['health'],
    queryFn: async () => unwrap(await client.GET('/health')),
    refetchInterval: 30000,
  })

  const {
    data: status,
    isLoading: statusLoading,
    error: statusError,
  } = useQuery({
    queryKey: ['status'],
    queryFn: async () => unwrap(await client.GET('/status')),
    refetchInterval: 30000,
  })

  const connectionError = healthError || statusError

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Dashboard</h1>
        <p className="text-gray-500">Book digitization pipeline status</p>
      </div>

      {connectionError && (
        <div className="bg-red-50 border border-red-200 rounded-lg p-4">
          <p className="text-red-700">
            Cannot connect to server: {connectionError.message}
          </p>
        </div>
      )}

      {/* Status Cards */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        {/* Server Status */}
        <div className="bg-white rounded-lg shadow p-6">
          <h3 className="text-sm font-medium text-gray-500">Server</h3>
          {healthLoading ? (
            <div className="mt-2 text-gray-400">Loading...</div>
          ) : (
            <div className="mt-2">
              <span
                className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${
                  health?.status === 'ok'
                    ? 'bg-green-100 text-green-800'
                    : 'bg-red-100 text-red-800'
                }`}
              >
                {health?.status || 'unknown'}
              </span>
            </div>
          )}
        </div>

        {/* DefraDB Status */}
        <div className="bg-white rounded-lg shadow p-6">
          <h3 className="text-sm font-medium text-gray-500">DefraDB</h3>
          {statusLoading ? (
            <div className="mt-2 text-gray-400">Loading...</div>
          ) : (
            <div className="mt-2 space-y-1">
              <div>
                <span className="text-xs text-gray-500">Container: </span>
                <span
                  className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${
                    status?.defra?.container === 'running'
                      ? 'bg-green-100 text-green-800'
                      : 'bg-yellow-100 text-yellow-800'
                  }`}
                >
                  {status?.defra?.container || 'unknown'}
                </span>
              </div>
              <div>
                <span className="text-xs text-gray-500">Health: </span>
                <span
                  className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${
                    status?.defra?.health === 'healthy'
                      ? 'bg-green-100 text-green-800'
                      : 'bg-red-100 text-red-800'
                  }`}
                >
                  {status?.defra?.health || 'unknown'}
                </span>
              </div>
            </div>
          )}
        </div>

        {/* Providers */}
        <div className="bg-white rounded-lg shadow p-6">
          <h3 className="text-sm font-medium text-gray-500">Providers</h3>
          {statusLoading ? (
            <div className="mt-2 text-gray-400">Loading...</div>
          ) : (
            <div className="mt-2 space-y-2">
              <div>
                <span className="text-xs text-gray-500">OCR: </span>
                <span className="text-sm text-gray-700">
                  {status?.providers?.ocr?.join(', ') || 'none'}
                </span>
              </div>
              <div>
                <span className="text-xs text-gray-500">LLM: </span>
                <span className="text-sm text-gray-700">
                  {status?.providers?.llm?.join(', ') || 'none'}
                </span>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Quick Actions */}
      <div className="bg-white rounded-lg shadow p-6">
        <h3 className="text-lg font-medium text-gray-900 mb-4">Quick Actions</h3>
        <div className="flex space-x-4">
          <a
            href="/books"
            className="inline-flex items-center px-4 py-2 border border-transparent text-sm font-medium rounded-md shadow-sm text-white bg-blue-600 hover:bg-blue-700"
          >
            View Library
          </a>
          <a
            href="/jobs"
            className="inline-flex items-center px-4 py-2 border border-gray-300 text-sm font-medium rounded-md shadow-sm text-gray-700 bg-white hover:bg-gray-50"
          >
            View Jobs
          </a>
        </div>
      </div>
    </div>
  )
}
