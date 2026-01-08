import { useState } from 'react'
import { Link } from '@tanstack/react-router'
import { useQuery } from '@tanstack/react-query'
import { client, unwrap } from '@/api/client'
import { StatusBadge, type StatusType } from '@/components/ui'
import type { StructureStatus, StageMetrics } from './types'

interface StructureSectionProps {
  structure?: StructureStatus
  bookId: string
  metrics?: Record<string, StageMetrics>
}

export function StructureSection({ structure, bookId, metrics }: StructureSectionProps) {
  const [expanded, setExpanded] = useState(false)
  const [metricsExpanded, setMetricsExpanded] = useState(false)

  const { data: chapters } = useQuery({
    queryKey: ['books', bookId, 'chapters'],
    queryFn: async () =>
      unwrap(
        await client.GET('/api/books/{id}/chapters', {
          params: { path: { id: bookId } },
        })
      ),
    enabled: !!structure?.complete,
  })

  if (!structure) return null

  const status: StatusType = structure.complete
    ? 'complete'
    : structure.failed
    ? 'failed'
    : structure.started
    ? 'in_progress'
    : 'pending'

  const matterBreakdown = chapters?.chapters?.reduce((acc, ch) => {
    const matter = ch.matter_type || 'unknown'
    acc[matter] = (acc[matter] || 0) + 1
    return acc
  }, {} as Record<string, number>) || {}

  const polishStats = chapters?.chapters?.reduce(
    (acc, ch) => {
      if (ch.polish_complete) acc.complete++
      else if (ch.polish_failed) acc.failed++
      else acc.pending++
      acc.total++
      return acc
    },
    { complete: 0, failed: 0, pending: 0, total: 0 }
  ) || { complete: 0, failed: 0, pending: 0, total: 0 }

  const hasDetails = chapters && chapters.chapters && chapters.chapters.length > 0

  return (
    <div className="border-t pt-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center space-x-2">
          <span className="text-sm font-medium text-gray-700">Structure</span>
          <StatusBadge status={status} />
        </div>
        <div className="flex items-center space-x-2">
          {structure.chapter_count !== undefined && structure.chapter_count > 0 && (
            <span className="text-gray-600 text-sm">
              {structure.chapter_count} chapters
            </span>
          )}
          {structure.cost_usd !== undefined && structure.cost_usd > 0 && (
            <span className="font-mono text-sm text-gray-500">
              ${structure.cost_usd.toFixed(4)}
            </span>
          )}
          {structure.complete && (
            <Link
              to="/books/$bookId/chapters"
              params={{ bookId }}
              className="text-sm text-blue-600 hover:text-blue-800"
            >
              View Chapters
            </Link>
          )}
        </div>
      </div>

      {structure.started && !structure.complete && !structure.failed && (
        <div className="mt-2 pl-4 text-sm text-gray-500">
          Building unified book structure...
        </div>
      )}

      {hasDetails && (
        <div className="mt-3">
          <div className="flex items-center justify-between bg-gray-50 rounded px-3 py-2">
            <div className="flex items-center space-x-4 text-sm">
              {Object.entries(matterBreakdown).map(([matter, count]) => (
                <span key={matter} className="flex items-center space-x-1">
                  <MatterTypeBadge type={matter} />
                  <span className="text-gray-600">{count}</span>
                </span>
              ))}
            </div>
            {polishStats.total > 0 && (
              <div className="flex items-center space-x-2 text-sm">
                <span className="text-gray-500">Polish:</span>
                <span className={polishStats.complete === polishStats.total ? 'text-green-600' : 'text-gray-600'}>
                  {polishStats.complete}/{polishStats.total}
                </span>
                {polishStats.failed > 0 && (
                  <span className="text-red-500">({polishStats.failed} failed)</span>
                )}
              </div>
            )}
            <button
              onClick={() => setExpanded(!expanded)}
              className="text-sm text-blue-600 hover:text-blue-800 flex items-center space-x-1"
            >
              <span>{expanded ? 'Hide' : 'Show'} Details</span>
              <span className={`transition-transform ${expanded ? 'rotate-180' : ''}`}>▼</span>
            </button>
          </div>

          {expanded && chapters?.chapters && (
            <div className="border rounded-lg overflow-hidden mt-2">
              <div className="grid grid-cols-12 gap-2 bg-gray-100 px-3 py-2 text-xs font-medium text-gray-600 border-b">
                <div className="col-span-1">#</div>
                <div className="col-span-5">Title</div>
                <div className="col-span-2">Type</div>
                <div className="col-span-2">Pages</div>
                <div className="col-span-2">Polish</div>
              </div>
              <div className="max-h-64 overflow-y-auto">
                {chapters.chapters.map((ch, idx) => (
                  <div
                    key={ch.entry_id || idx}
                    className="grid grid-cols-12 gap-2 px-3 py-2 text-sm border-b last:border-b-0 hover:bg-gray-50"
                  >
                    <div className="col-span-1 font-mono text-xs text-gray-400">
                      {ch.entry_number || idx + 1}
                    </div>
                    <div className="col-span-5 flex items-center">
                      <div style={{ width: `${(ch.level || 0) * 12}px` }} className="flex-shrink-0" />
                      <span className={ch.level === 0 || ch.level === 1 ? 'font-medium' : ''}>
                        {ch.title || 'Untitled'}
                      </span>
                    </div>
                    <div className="col-span-2">
                      <MatterTypeBadge type={ch.matter_type} />
                    </div>
                    <div className="col-span-2 font-mono text-xs text-gray-500">
                      {ch.start_page && ch.end_page ? `${ch.start_page}-${ch.end_page}` : '-'}
                    </div>
                    <div className="col-span-2">
                      {ch.polish_complete ? (
                        <span className="text-green-600 text-xs">● Complete</span>
                      ) : ch.polish_failed ? (
                        <span className="text-red-600 text-xs">✕ Failed</span>
                      ) : (
                        <span className="text-gray-400 text-xs">○ Pending</span>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {/* Metrics breakdown by Structure stage */}
      {metrics && hasStructureMetrics(metrics) && (
        <div className="mt-3">
          <button
            onClick={() => setMetricsExpanded(!metricsExpanded)}
            className="text-sm text-blue-600 hover:text-blue-800 flex items-center space-x-1"
          >
            <span>{metricsExpanded ? 'Hide' : 'Show'} Stage Metrics</span>
            <span className={`transition-transform ${metricsExpanded ? 'rotate-180' : ''}`}>▼</span>
          </button>
          {metricsExpanded && (
            <div className="mt-2 grid grid-cols-1 md:grid-cols-2 gap-2">
              {metrics['structure-classify'] && <StructureMetricsCard label="Matter Classification" metrics={metrics['structure-classify']} />}
              {metrics['structure-polish'] && <StructureMetricsCard label="Text Polish" metrics={metrics['structure-polish']} />}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function MatterTypeBadge({ type }: { type?: string }) {
  const styles: Record<string, string> = {
    front_matter: 'bg-purple-100 text-purple-700',
    body: 'bg-blue-100 text-blue-700',
    back_matter: 'bg-orange-100 text-orange-700',
    unknown: 'bg-gray-100 text-gray-600',
  }
  const labels: Record<string, string> = {
    front_matter: 'Front',
    body: 'Body',
    back_matter: 'Back',
    unknown: '?',
  }
  const key = type || 'unknown'
  return (
    <span className={`text-xs px-1.5 py-0.5 rounded ${styles[key] || styles.unknown}`}>
      {labels[key] || key}
    </span>
  )
}

function hasStructureMetrics(metrics: Record<string, StageMetrics>): boolean {
  const structureKeys = ['structure-classify', 'structure-polish']
  return structureKeys.some(key => metrics[key] && metrics[key].count > 0)
}

function StructureMetricsCard({ label, metrics }: { label: string; metrics: StageMetrics }) {
  const formatLatency = (ms: number) => {
    if (ms < 1000) return `${ms.toFixed(0)}ms`
    return `${(ms / 1000).toFixed(1)}s`
  }

  return (
    <div className="bg-gray-50 rounded px-3 py-2 text-xs">
      <div className="font-medium text-gray-700 mb-1">{label}</div>
      <div className="space-y-0.5 text-gray-600">
        <div className="flex justify-between">
          <span>Calls:</span>
          <span className="font-mono">
            {metrics.count}
            {metrics.error_count > 0 && (
              <span className="text-red-500 ml-1">({metrics.error_count} err)</span>
            )}
          </span>
        </div>
        {metrics.latency_p50 > 0 && (
          <div className="flex justify-between">
            <span>Latency:</span>
            <span className="font-mono">
              {formatLatency(metrics.latency_p50 * 1000)} p50 / {formatLatency(metrics.latency_p95 * 1000)} p95
            </span>
          </div>
        )}
        {metrics.total_cost_usd > 0 && (
          <div className="flex justify-between">
            <span>Cost:</span>
            <span className="font-mono">${metrics.total_cost_usd.toFixed(4)}</span>
          </div>
        )}
        {metrics.total_tokens > 0 && (
          <div className="flex justify-between">
            <span>Tokens:</span>
            <span className="font-mono">
              {metrics.total_prompt_tokens.toLocaleString()}→{metrics.total_completion_tokens.toLocaleString()}
            </span>
          </div>
        )}
      </div>
    </div>
  )
}
