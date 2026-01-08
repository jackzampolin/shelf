import { useState } from 'react'
import { Link } from '@tanstack/react-router'
import type { StatusType } from '@/components/ui'
import type { TocStatus, TocEntry, StageMetrics } from './types'

interface TocSectionProps {
  toc?: TocStatus
  bookId: string
  metrics?: Record<string, StageMetrics>
}

export function TocSection({ toc, bookId, metrics }: TocSectionProps) {
  const [entriesExpanded, setEntriesExpanded] = useState(false)
  const [metricsExpanded, setMetricsExpanded] = useState(false)

  if (!toc) return null

  const finderStatus: StatusType = toc.finder_complete ? 'complete' : toc.finder_failed ? 'failed' : toc.finder_started ? 'in_progress' : 'pending'
  const extractStatus: StatusType = toc.extract_complete ? 'complete' : toc.extract_failed ? 'failed' : toc.extract_started ? 'in_progress' : 'pending'
  const linkStatus: StatusType = toc.link_complete ? 'complete' : toc.link_failed ? 'failed' : toc.link_started ? 'in_progress' : 'pending'
  const finalizeStatus: StatusType = toc.finalize_complete ? 'complete' : toc.finalize_failed ? 'failed' : toc.finalize_started ? 'in_progress' : 'pending'

  const extractedCount = (toc.entries || []).filter(e => e.source !== 'discovered').length
  const discoveredCount = toc.entries_discovered || 0
  const linkedCount = toc.entries_linked || 0
  const totalCount = toc.entry_count || 0

  return (
    <div className="border-t pt-4">
      <div className="flex items-center justify-between mb-3">
        <span className="text-sm font-medium text-gray-700">Table of Contents</span>
        <div className="flex items-center space-x-3">
          {toc.cost_usd !== undefined && (
            <span className="font-mono text-sm text-gray-500">
              ${toc.cost_usd.toFixed(4)}
            </span>
          )}
          {toc.found && toc.start_page && (
            <Link
              to="/books/$bookId/pages/$pageNum"
              params={{ bookId, pageNum: String(toc.start_page) }}
              className="text-sm text-blue-600 hover:text-blue-800"
            >
              View ToC Pages
            </Link>
          )}
        </div>
      </div>

      <div className="flex items-center space-x-1 text-xs mb-3">
        <TocStageChip label="Find" status={finderStatus} detail={toc.found ? `p${toc.start_page}-${toc.end_page}` : undefined} />
        <span className="text-gray-300">→</span>
        <TocStageChip label="Extract" status={extractStatus} detail={extractedCount > 0 ? `${extractedCount}` : undefined} />
        <span className="text-gray-300">→</span>
        <TocStageChip label="Link" status={linkStatus} detail={totalCount > 0 ? `${linkedCount}/${totalCount}` : undefined} />
        <span className="text-gray-300">→</span>
        <TocStageChip label="Finalize" status={finalizeStatus} detail={discoveredCount > 0 ? `+${discoveredCount}` : undefined} />
      </div>

      {totalCount > 0 && (
        <div className="flex items-center justify-between bg-gray-50 rounded px-3 py-2 mb-3">
          <div className="flex items-center space-x-4 text-sm">
            <span className="text-gray-600">
              <strong>{totalCount}</strong> entries
            </span>
            <span className="text-gray-600">
              <strong>{linkedCount}</strong> linked ({totalCount > 0 ? Math.round((linkedCount / totalCount) * 100) : 0}%)
            </span>
            {discoveredCount > 0 && (
              <span className="text-green-600">
                <strong>+{discoveredCount}</strong> discovered
              </span>
            )}
          </div>
          <button
            onClick={() => setEntriesExpanded(!entriesExpanded)}
            className="text-sm text-blue-600 hover:text-blue-800 flex items-center space-x-1"
          >
            <span>{entriesExpanded ? 'Hide' : 'Show'} Entries</span>
            <span className={`transition-transform ${entriesExpanded ? 'rotate-180' : ''}`}>▼</span>
          </button>
        </div>
      )}

      {entriesExpanded && toc.entries && toc.entries.length > 0 && (
        <div className="border rounded-lg overflow-hidden">
          <div className="grid grid-cols-12 gap-2 bg-gray-100 px-3 py-2 text-xs font-medium text-gray-600 border-b">
            <div className="col-span-1">#</div>
            <div className="col-span-6">Title</div>
            <div className="col-span-2">Type</div>
            <div className="col-span-1 text-right">Print</div>
            <div className="col-span-2 text-right">Scan Page</div>
          </div>
          <div className="max-h-96 overflow-y-auto">
            {toc.entries.map((entry, idx) => (
              <TocEntryRow key={idx} entry={entry} bookId={bookId} />
            ))}
          </div>
        </div>
      )}

      {/* Metrics breakdown by ToC stage */}
      {metrics && hasTocMetrics(metrics) && (
        <div className="mt-3">
          <button
            onClick={() => setMetricsExpanded(!metricsExpanded)}
            className="text-sm text-blue-600 hover:text-blue-800 flex items-center space-x-1"
          >
            <span>{metricsExpanded ? 'Hide' : 'Show'} Stage Metrics</span>
            <span className={`transition-transform ${metricsExpanded ? 'rotate-180' : ''}`}>▼</span>
          </button>
          {metricsExpanded && (
            <div className="mt-2 grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-2">
              {metrics['toc'] && <StageMetricsCard label="Find/Extract" metrics={metrics['toc']} stage="toc" bookId={bookId} />}
              {metrics['toc-link'] && <StageMetricsCard label="Link" metrics={metrics['toc-link']} stage="toc-link" bookId={bookId} />}
              {metrics['toc-pattern'] && <StageMetricsCard label="Pattern Analysis" metrics={metrics['toc-pattern']} stage="toc-pattern" bookId={bookId} />}
              {metrics['toc-discover'] && <StageMetricsCard label="Chapter Discovery" metrics={metrics['toc-discover']} stage="toc-discover" bookId={bookId} />}
              {metrics['toc-validate'] && <StageMetricsCard label="Gap Validation" metrics={metrics['toc-validate']} stage="toc-validate" bookId={bookId} />}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function TocStageChip({ label, status, detail }: { label: string; status: StatusType; detail?: string }) {
  const statusStyles = {
    pending: 'bg-gray-100 text-gray-500 border-gray-200',
    in_progress: 'bg-blue-50 text-blue-700 border-blue-200',
    complete: 'bg-green-50 text-green-700 border-green-200',
    failed: 'bg-red-50 text-red-700 border-red-200',
  }

  const statusIcons = {
    pending: '○',
    in_progress: '◐',
    complete: '●',
    failed: '✕',
  }

  return (
    <div className={`px-2 py-1 rounded border ${statusStyles[status]} flex items-center space-x-1`}>
      <span>{statusIcons[status]}</span>
      <span className="font-medium">{label}</span>
      {detail && <span className="text-xs opacity-75">({detail})</span>}
    </div>
  )
}

function TocEntryRow({ entry, bookId }: { entry: TocEntry; bookId: string }) {
  const level = entry.level || 0
  const isDiscovered = entry.source === 'discovered'
  const isLinked = entry.is_linked && entry.actual_page_num

  return (
    <div
      className={`grid grid-cols-12 gap-2 px-3 py-2 text-sm border-b last:border-b-0 hover:bg-gray-50 ${
        isDiscovered ? 'bg-green-50/50' : ''
      }`}
    >
      <div className="col-span-1 font-mono text-xs text-gray-400">
        {entry.entry_number || '-'}
      </div>
      <div className="col-span-6 flex items-center">
        <div style={{ width: `${level * 16}px` }} className="flex-shrink-0" />
        <span className={level === 0 ? 'font-medium' : ''}>
          {entry.title || 'Untitled'}
        </span>
      </div>
      <div className="col-span-2">
        <div className="flex items-center space-x-1">
          {entry.level_name && (
            <span className="text-xs text-gray-500">{entry.level_name}</span>
          )}
          {isDiscovered && (
            <span className="text-xs bg-green-100 text-green-700 px-1 rounded">new</span>
          )}
        </div>
      </div>
      <div className="col-span-1 text-right font-mono text-gray-500">
        {entry.printed_page_number || '-'}
      </div>
      <div className="col-span-2 text-right">
        {isLinked ? (
          <Link
            to="/books/$bookId/pages/$pageNum"
            params={{ bookId, pageNum: String(entry.actual_page_num) }}
            className="font-mono text-blue-600 hover:text-blue-800"
          >
            p.{entry.actual_page_num}
          </Link>
        ) : (
          <span className="text-gray-300">—</span>
        )}
      </div>
    </div>
  )
}

function hasTocMetrics(metrics: Record<string, StageMetrics>): boolean {
  const tocKeys = ['toc', 'toc-link', 'toc-pattern', 'toc-discover', 'toc-validate']
  return tocKeys.some(key => metrics[key] && metrics[key].count > 0)
}

interface StageMetricsCardProps {
  label: string
  metrics: StageMetrics
  stage?: string
  bookId?: string
}

function StageMetricsCard({ label, metrics, stage, bookId }: StageMetricsCardProps) {
  const formatLatency = (ms: number) => {
    if (ms < 1000) return `${ms.toFixed(0)}ms`
    return `${(ms / 1000).toFixed(1)}s`
  }

  const logsUrl = stage && bookId
    ? `/api/books/${bookId}/agent-logs?stage=${encodeURIComponent(stage)}`
    : null

  return (
    <div className="bg-gray-50 rounded px-3 py-2 text-xs">
      <div className="flex items-center justify-between mb-1">
        <span className="font-medium text-gray-700">{label}</span>
        {logsUrl && (
          <a
            href={logsUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="text-blue-600 hover:text-blue-800 text-xs"
            title="View agent logs"
          >
            Logs
          </a>
        )}
      </div>
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
