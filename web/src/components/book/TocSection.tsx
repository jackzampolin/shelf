import { useState } from 'react'
import { Link } from '@tanstack/react-router'
import { useQuery } from '@tanstack/react-query'
import { client, unwrap } from '@/api/client'
import type { StatusType } from '@/components/ui'
import type { TocStatus, TocEntry, StageMetrics } from './types'

interface TocSectionProps {
  toc?: TocStatus
  bookId: string
  metrics?: Record<string, StageMetrics>
}

interface AgentLog {
  id: string
  agent_type: string
  started_at: string
  completed_at?: string
  iterations: number
  success: boolean
  error?: string
}

export function TocSection({ toc, bookId, metrics }: TocSectionProps) {
  const [entriesExpanded, setEntriesExpanded] = useState(false)
  const [pipelineExpanded, setPipelineExpanded] = useState(true)

  // Fetch agent logs when pipeline is expanded
  const { data: agentLogs } = useQuery({
    queryKey: ['book-agent-logs', bookId],
    queryFn: async () => {
      const resp = await client.GET('/api/books/{book_id}/agent-logs', {
        params: { path: { book_id: bookId } }
      })
      return unwrap(resp)
    },
    enabled: pipelineExpanded,
    refetchInterval: 5000, // Poll for updates during processing
  })

  if (!toc) return null

  // Group agent logs by type
  const logsByType: Record<string, AgentLog[]> = {}
  if (agentLogs?.logs) {
    for (const log of agentLogs.logs) {
      const type = log.agent_type || 'unknown'
      if (!logsByType[type]) logsByType[type] = []
      logsByType[type].push(log as AgentLog)
    }
  }

  const finderStatus: StatusType = toc.finder_complete ? 'complete' : toc.finder_failed ? 'failed' : toc.finder_started ? 'in_progress' : 'pending'
  const extractStatus: StatusType = toc.extract_complete ? 'complete' : toc.extract_failed ? 'failed' : toc.extract_started ? 'in_progress' : 'pending'
  const linkStatus: StatusType = toc.link_complete ? 'complete' : toc.link_failed ? 'failed' : toc.link_started ? 'in_progress' : 'pending'
  const finalizeStatus: StatusType = toc.finalize_complete ? 'complete' : toc.finalize_failed ? 'failed' : toc.finalize_started ? 'in_progress' : 'pending'

  const extractedCount = (toc.entries || []).filter(e => e.source !== 'discovered').length
  const discoveredCount = toc.entries_discovered || 0
  const linkedCount = toc.entries_linked || 0
  const totalCount = toc.entry_count || 0

  // Get metrics for stages
  const tocMetrics = metrics?.['toc']
  const linkMetrics = metrics?.['toc-link']
  const patternMetrics = metrics?.['toc-pattern']
  const discoverMetrics = metrics?.['toc-discover']
  const validateMetrics = metrics?.['toc-validate']

  // Determine finalize sub-stage states
  const hasPatternAnalysis = patternMetrics && patternMetrics.count > 0
  const hasChapterDiscovery = discoverMetrics && discoverMetrics.count > 0
  const hasGapValidation = validateMetrics && validateMetrics.count > 0

  return (
    <div className="border-t pt-4">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center space-x-2">
          <span className="text-sm font-medium text-gray-700">Table of Contents</span>
          <button
            onClick={() => setPipelineExpanded(!pipelineExpanded)}
            className="text-xs text-blue-600 hover:text-blue-800"
          >
            {pipelineExpanded ? 'Hide' : 'Show'} Pipeline
          </button>
        </div>
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

      {pipelineExpanded && (
        <div className="bg-gray-50 rounded-lg p-4 mb-3">
          {/* Main pipeline flow */}
          <div className="flex flex-col space-y-3">
            {/* Row 1: Find → Extract */}
            <div className="flex items-center space-x-2">
              <PipelineStage
                label="Find ToC"
                status={finderStatus}
                detail={toc.found ? `p${toc.start_page}-${toc.end_page}` : undefined}
                metrics={tocMetrics}
                logs={logsByType['toc_finder']}
                              />
              <Arrow />
              <PipelineStage
                label="Extract"
                status={extractStatus}
                detail={extractedCount > 0 ? `${extractedCount} entries` : undefined}
                metrics={tocMetrics}
                logs={logsByType['toc_extract']}
                              />
            </div>

            {/* Row 2: Link (with call count) */}
            <div className="flex items-center space-x-2 pl-4">
              <span className="text-gray-300 text-xs">↳</span>
              <PipelineStage
                label="Link Entries"
                status={linkStatus}
                detail={totalCount > 0 ? `${linkedCount}/${totalCount} linked` : undefined}
                metrics={linkMetrics}
                logs={logsByType['toc_entry_finder']}
                                showCallCount
              />
            </div>

            {/* Row 3: Finalize sub-stages (branching) */}
            <div className="flex items-start space-x-2 pl-4">
              <span className="text-gray-300 text-xs mt-2">↳</span>
              <div className="flex-1">
                <div className="text-xs text-gray-500 mb-2">Finalize ({finalizeStatus})</div>
                <div className="flex items-center space-x-2 flex-wrap gap-y-2">
                  <PipelineStage
                    label="Pattern Analysis"
                    status={hasPatternAnalysis ? 'complete' : finalizeStatus === 'pending' ? 'pending' : 'in_progress'}
                    metrics={patternMetrics}
                    logs={logsByType['pattern_analyzer']}
                                        compact
                  />

                  {/* Conditional branch to Chapter Discovery */}
                  <div className="flex items-center space-x-2">
                    <ConditionalArrow active={!!hasPatternAnalysis} />
                    <PipelineStage
                      label="Chapter Discovery"
                      status={hasChapterDiscovery ? 'complete' : hasPatternAnalysis ? (finalizeStatus === 'complete' ? 'complete' : 'pending') : 'pending'}
                      detail={discoveredCount > 0 ? `+${discoveredCount}` : undefined}
                      metrics={discoverMetrics}
                      logs={logsByType['chapter_finder']}
                                            compact
                      dimmed={!hasPatternAnalysis && finalizeStatus !== 'in_progress'}
                    />
                  </div>

                  {/* Conditional branch to Gap Validation */}
                  <div className="flex items-center space-x-2">
                    <ConditionalArrow active={!!hasChapterDiscovery} />
                    <PipelineStage
                      label="Gap Validation"
                      status={hasGapValidation ? 'complete' : hasChapterDiscovery ? (finalizeStatus === 'complete' ? 'complete' : 'pending') : 'pending'}
                      metrics={validateMetrics}
                      logs={logsByType['gap_investigator']}
                                            compact
                      dimmed={!hasChapterDiscovery && finalizeStatus !== 'in_progress'}
                    />
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Entry summary and expand */}
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
    </div>
  )
}

interface PipelineStageProps {
  label: string
  status: StatusType
  detail?: string
  metrics?: StageMetrics
  logs?: AgentLog[]
  compact?: boolean
  dimmed?: boolean
  showCallCount?: boolean
}

function PipelineStage({ label, status, detail, metrics, logs, compact, dimmed, showCallCount }: PipelineStageProps) {
  const [expanded, setExpanded] = useState(false)

  const statusStyles = {
    pending: 'bg-gray-100 text-gray-500 border-gray-200',
    in_progress: 'bg-blue-50 text-blue-700 border-blue-200 animate-pulse',
    complete: 'bg-green-50 text-green-700 border-green-200',
    failed: 'bg-red-50 text-red-700 border-red-200',
  }

  const statusIcons = {
    pending: '○',
    in_progress: '◐',
    complete: '●',
    failed: '✕',
  }

  const callCount = metrics?.count || logs?.length || 0
  const hasLogs = logs && logs.length > 0

  return (
    <div className={`relative ${dimmed ? 'opacity-40' : ''}`}>
      <button
        onClick={() => hasLogs && setExpanded(!expanded)}
        className={`
          ${compact ? 'px-2 py-1 text-xs' : 'px-3 py-1.5 text-sm'}
          rounded border ${statusStyles[status]}
          flex items-center space-x-1
          ${hasLogs ? 'cursor-pointer hover:ring-2 hover:ring-blue-300' : 'cursor-default'}
          transition-all
        `}
      >
        <span>{statusIcons[status]}</span>
        <span className="font-medium">{label}</span>
        {detail && <span className="opacity-75">({detail})</span>}
        {showCallCount && callCount > 0 && (
          <span className="ml-1 bg-white/50 px-1.5 rounded text-xs font-mono">{callCount} calls</span>
        )}
        {!showCallCount && callCount > 1 && (
          <span className="ml-1 bg-white/50 px-1 rounded text-xs font-mono">×{callCount}</span>
        )}
        {hasLogs && (
          <span className={`ml-1 transition-transform ${expanded ? 'rotate-180' : ''}`}>▾</span>
        )}
      </button>

      {/* Expanded call details */}
      {expanded && hasLogs && (
        <div className="absolute top-full left-0 mt-1 z-10 bg-white border rounded-lg shadow-lg p-2 min-w-64 max-h-64 overflow-y-auto">
          <div className="text-xs font-medium text-gray-500 mb-2">Agent Calls ({logs.length})</div>
          <div className="space-y-1">
            {logs.map((log, idx) => (
              <AgentCallBadge key={log.id || idx} log={log} index={idx + 1} />
            ))}
          </div>
          {metrics && (
            <div className="mt-2 pt-2 border-t text-xs text-gray-500">
              <div className="flex justify-between">
                <span>Total Cost:</span>
                <span className="font-mono">${metrics.total_cost_usd?.toFixed(4) || '0.0000'}</span>
              </div>
              <div className="flex justify-between">
                <span>Tokens:</span>
                <span className="font-mono">
                  {metrics.total_prompt_tokens?.toLocaleString() || 0}→{metrics.total_completion_tokens?.toLocaleString() || 0}
                </span>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function AgentCallBadge({ log, index }: { log: AgentLog; index: number }) {
  const duration = log.completed_at && log.started_at
    ? ((new Date(log.completed_at).getTime() - new Date(log.started_at).getTime()) / 1000).toFixed(1)
    : null

  return (
    <div className={`
      flex items-center justify-between px-2 py-1 rounded text-xs
      ${log.success ? 'bg-green-50 text-green-700' : log.error ? 'bg-red-50 text-red-700' : 'bg-blue-50 text-blue-700'}
    `}>
      <div className="flex items-center space-x-2">
        <span className="font-mono text-gray-400">#{index}</span>
        <span>{log.success ? '✓' : log.error ? '✕' : '◐'}</span>
        <span>{log.iterations} iter</span>
      </div>
      {duration && <span className="font-mono">{duration}s</span>}
    </div>
  )
}

function Arrow() {
  return <span className="text-gray-300 text-lg">→</span>
}

function ConditionalArrow({ active }: { active: boolean }) {
  return (
    <span className={`text-lg ${active ? 'text-green-400' : 'text-gray-200'}`}>
      {active ? '→' : '⇢'}
    </span>
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
