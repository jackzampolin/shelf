import { useState, ReactNode } from 'react'
import { formatNumber } from '@/lib/format'
import type { StageMetrics } from './types'

interface CollapsibleSectionProps {
  title: string
  current: number
  total: number
  cost?: number
  metrics?: StageMetrics
  children: ReactNode
}

export function CollapsibleSection({
  title,
  current,
  total,
  cost,
  metrics,
  children,
}: CollapsibleSectionProps) {
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
