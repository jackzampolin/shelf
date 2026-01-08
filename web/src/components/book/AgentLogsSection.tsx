import { useState } from 'react'
import type { AgentLogSummary } from './types'
import { AGENT_CATEGORIES, getAgentCategory, getAgentDisplayName } from './types'

interface AgentLogsSectionProps {
  logs: AgentLogSummary[]
  onViewLog: (id: string) => void
}

export function AgentLogsSection({ logs, onViewLog }: AgentLogsSectionProps) {
  const [expanded, setExpanded] = useState(false)

  const grouped = logs.reduce((acc, log) => {
    const category = getAgentCategory(log.agent_type || '')
    if (!acc[category]) acc[category] = []
    acc[category].push(log)
    return acc
  }, {} as Record<string, AgentLogSummary[]>)

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
