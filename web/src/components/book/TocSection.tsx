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
  onViewAgentLog?: (logId: string) => void
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

interface LLMCall {
  id: string
  timestamp: string
  prompt_key: string
  model: string
  latency_ms: number
  input_tokens: number
  output_tokens: number
  success: boolean
  response?: string
}

export function TocSection({ toc, bookId, metrics, onViewAgentLog }: TocSectionProps) {
  const [entriesExpanded, setEntriesExpanded] = useState(false)
  const [pipelineExpanded, setPipelineExpanded] = useState(true)
  const [patternExpanded, setPatternExpanded] = useState(false)

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

  // Fetch LLM calls for non-agent stages (pattern_analyzer, extract_toc)
  const { data: llmCalls } = useQuery({
    queryKey: ['book-llmcalls', bookId, 'toc-stages'],
    queryFn: async () => {
      const resp = await client.GET('/api/llmcalls', {
        params: { query: { book_id: bookId, limit: 100 } }
      })
      return unwrap(resp)
    },
    enabled: pipelineExpanded,
    refetchInterval: 5000,
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

  // Group LLM calls by prompt_key for non-agent stages
  const llmCallsByPrompt: Record<string, LLMCall[]> = {}
  if (llmCalls?.calls) {
    for (const call of llmCalls.calls) {
      const key = call.prompt_key || 'unknown'
      if (!llmCallsByPrompt[key]) llmCallsByPrompt[key] = []
      llmCallsByPrompt[key].push(call as LLMCall)
    }
  }

  // Map prompt keys to display names for non-agent stages
  const patternCalls = llmCallsByPrompt['agents.pattern_analyzer.system'] || []
  const extractCalls = llmCallsByPrompt['stages.extract_toc.system'] || []

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

  // Determine finalize sub-stage states from API data (preferred) or fallback to logs/calls
  const hasPatternCalls = patternCalls.length > 0
  const hasChapterLogs = (logsByType['chapter_finder']?.length || 0) > 0
  const hasGapLogs = (logsByType['gap_investigator']?.length || 0) > 0

  // Use API-provided status when available
  const patternComplete = toc.pattern_complete ?? hasPatternCalls
  const entriesToFind = toc.entries_to_find ?? 0
  const discoverComplete = toc.discover_complete ?? (patternComplete && entriesToFind === 0)
  const validateComplete = toc.validate_complete ?? toc.finalize_complete

  // Derive phase statuses
  const patternStatus: StatusType = patternComplete
    ? 'complete'
    : (finalizeStatus === 'in_progress' || finalizeStatus === 'complete')
      ? 'in_progress'
      : 'pending'

  const discoverStatus: StatusType = discoverComplete
    ? 'complete'
    : patternComplete
      ? (discoveredCount > 0 || hasChapterLogs ? 'in_progress' : 'pending')
      : 'pending'

  const gapStatus: StatusType = validateComplete
    ? 'complete'
    : discoverComplete
      ? (hasGapLogs ? 'in_progress' : 'pending')
      : 'pending'

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
                onViewLog={onViewAgentLog}
              />
              <Arrow />
              <PipelineStage
                label="Extract"
                status={extractStatus}
                detail={extractedCount > 0 ? `${extractedCount} entries` : undefined}
                metrics={tocMetrics}
                logs={logsByType['toc_extract']}
                llmCalls={extractCalls}
                onViewLog={onViewAgentLog}
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
                onViewLog={onViewAgentLog}
              />
            </div>

            {/* Row 3: Finalize sub-stages (branching) */}
            <div className="flex items-start space-x-2 pl-4">
              <span className="text-gray-300 text-xs mt-2">↳</span>
              <div className="flex-1">
                <div className="text-xs text-gray-500 mb-2">
                  Finalize ({finalizeStatus})
                  {toc.patterns_found !== undefined && toc.patterns_found > 0 && (
                    <span className="ml-2 text-gray-400">
                      {toc.patterns_found} patterns, {toc.excluded_ranges || 0} excluded
                    </span>
                  )}
                </div>
                <div className="flex items-center space-x-2 flex-wrap gap-y-2">
                  <PipelineStage
                    label="Pattern Analysis"
                    status={patternStatus}
                    detail={patternComplete && entriesToFind === 0 ? '0 to find' : entriesToFind > 0 ? `${entriesToFind} to find` : undefined}
                    metrics={patternMetrics}
                    llmCalls={patternCalls}
                    compact
                  />

                  {/* Conditional branch to Chapter Discovery */}
                  <div className="flex items-center space-x-2">
                    <ConditionalArrow active={patternComplete} />
                    <PipelineStage
                      label="Chapter Discovery"
                      status={discoverStatus}
                      detail={
                        entriesToFind > 0
                          ? `${discoveredCount}/${entriesToFind} found`
                          : patternComplete
                            ? 'skipped'
                            : undefined
                      }
                      metrics={discoverMetrics}
                      logs={logsByType['chapter_finder']}
                      compact
                      dimmed={!patternComplete && finalizeStatus === 'pending'}
                      showCallCount
                      onViewLog={onViewAgentLog}
                    />
                  </div>

                  {/* Conditional branch to Gap Validation */}
                  <div className="flex items-center space-x-2">
                    <ConditionalArrow active={discoverComplete} />
                    <PipelineStage
                      label="Gap Validation"
                      status={gapStatus}
                      metrics={validateMetrics}
                      logs={logsByType['gap_investigator']}
                      compact
                      dimmed={!discoverComplete && finalizeStatus === 'pending'}
                      onViewLog={onViewAgentLog}
                    />
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Pattern Analysis Details (expandable) */}
      {toc.pattern_analysis && (
        <div className="mb-3">
          <button
            onClick={() => setPatternExpanded(!patternExpanded)}
            className="flex items-center space-x-2 text-sm text-gray-600 hover:text-gray-800"
          >
            <span className={`transition-transform ${patternExpanded ? 'rotate-90' : ''}`}>▶</span>
            <span>Pattern Analysis Details</span>
            {toc.pattern_analysis.excluded_ranges && toc.pattern_analysis.excluded_ranges.length > 0 && (
              <span className="text-xs text-gray-400">
                ({toc.pattern_analysis.excluded_ranges.length} excluded ranges)
              </span>
            )}
          </button>

          {patternExpanded && (
            <div className="mt-2 bg-gray-50 rounded-lg p-3 text-sm">
              {/* Reasoning */}
              {toc.pattern_analysis.reasoning && (
                <div className="mb-3">
                  <div className="text-xs font-medium text-gray-500 mb-1">Reasoning</div>
                  <div className="text-gray-700 whitespace-pre-wrap text-xs bg-white rounded p-2 border">
                    {toc.pattern_analysis.reasoning}
                  </div>
                </div>
              )}

              {/* Patterns Found */}
              {toc.pattern_analysis.patterns && toc.pattern_analysis.patterns.length > 0 && (
                <div className="mb-3">
                  <div className="text-xs font-medium text-gray-500 mb-1">
                    Discovered Patterns ({toc.pattern_analysis.patterns.length})
                  </div>
                  <div className="space-y-1">
                    {toc.pattern_analysis.patterns.map((pattern, idx) => (
                      <div key={idx} className="bg-white rounded p-2 border text-xs">
                        <div className="flex items-center space-x-2">
                          <span className="font-medium">{pattern.level_name}</span>
                          <span className="text-gray-400">|</span>
                          <span className="font-mono">{pattern.heading_format}</span>
                          <span className="text-gray-400">|</span>
                          <span>{pattern.range_start} → {pattern.range_end}</span>
                        </div>
                        {pattern.reasoning && (
                          <div className="text-gray-500 mt-1">{pattern.reasoning}</div>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Excluded Ranges */}
              {toc.pattern_analysis.excluded_ranges && toc.pattern_analysis.excluded_ranges.length > 0 && (
                <div>
                  <div className="text-xs font-medium text-gray-500 mb-1">
                    Excluded Ranges ({toc.pattern_analysis.excluded_ranges.length})
                  </div>
                  <div className="space-y-1">
                    {toc.pattern_analysis.excluded_ranges.map((range, idx) => (
                      <div key={idx} className="bg-white rounded px-2 py-1 border text-xs flex items-center space-x-2">
                        <span className="font-mono text-gray-600">p{range.start_page}–{range.end_page}</span>
                        <span className="text-gray-400">|</span>
                        <span className="text-gray-600">{range.reason}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* No patterns or exclusions */}
              {(!toc.pattern_analysis.patterns || toc.pattern_analysis.patterns.length === 0) &&
               (!toc.pattern_analysis.excluded_ranges || toc.pattern_analysis.excluded_ranges.length === 0) &&
               !toc.pattern_analysis.reasoning && (
                <div className="text-gray-500 text-xs">No pattern analysis data available</div>
              )}
            </div>
          )}
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
  llmCalls?: LLMCall[]
  compact?: boolean
  dimmed?: boolean
  showCallCount?: boolean
  onViewLog?: (logId: string) => void
  onViewLLMCall?: (callId: string) => void
}

function PipelineStage({ label, status, detail, metrics, logs, llmCalls, compact, dimmed, showCallCount, onViewLog, onViewLLMCall }: PipelineStageProps) {
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

  // Count runs - either agent logs or LLM calls
  const hasLogs = logs && logs.length > 0
  const hasLLMCalls = llmCalls && llmCalls.length > 0
  const callCount = (logs?.length || 0) + (llmCalls?.length || 0)
  const hasExpandableContent = hasLogs || hasLLMCalls

  return (
    <div className={`relative ${dimmed ? 'opacity-40' : ''}`}>
      <button
        onClick={() => hasExpandableContent && setExpanded(!expanded)}
        className={`
          ${compact ? 'px-2 py-1 text-xs' : 'px-3 py-1.5 text-sm'}
          rounded border ${statusStyles[status]}
          flex items-center space-x-1
          ${hasExpandableContent ? 'cursor-pointer hover:ring-2 hover:ring-blue-300' : 'cursor-default'}
          transition-all
        `}
      >
        <span>{statusIcons[status]}</span>
        <span className="font-medium">{label}</span>
        {detail && <span className="opacity-75">({detail})</span>}
        {callCount > 1 && (
          <span className="ml-1 bg-white/50 px-1.5 rounded text-xs font-mono">
            {showCallCount ? `${callCount} calls` : `×${callCount}`}
          </span>
        )}
        {hasExpandableContent && (
          <span className={`ml-1 transition-transform ${expanded ? 'rotate-180' : ''}`}>▾</span>
        )}
      </button>

      {/* Expanded call details */}
      {expanded && hasExpandableContent && (
        <div className="absolute top-full left-0 mt-1 z-10 bg-white border rounded-lg shadow-lg p-2 min-w-64 max-h-64 overflow-y-auto">
          {/* Agent runs */}
          {hasLogs && (
            <>
              <div className="text-xs font-medium text-gray-500 mb-2">Agent Runs ({logs.length})</div>
              <div className="space-y-1">
                {logs.map((log, idx) => (
                  <AgentCallBadge
                    key={log.id || idx}
                    log={log}
                    index={idx + 1}
                    onView={onViewLog && log.id ? () => onViewLog(log.id) : undefined}
                  />
                ))}
              </div>
            </>
          )}

          {/* LLM calls (for non-agent stages) */}
          {hasLLMCalls && (
            <>
              <div className={`text-xs font-medium text-gray-500 mb-2 ${hasLogs ? 'mt-3 pt-2 border-t' : ''}`}>
                LLM Calls ({llmCalls.length})
              </div>
              <div className="space-y-1">
                {llmCalls.map((call, idx) => (
                  <LLMCallBadge
                    key={call.id || idx}
                    call={call}
                    index={idx + 1}
                    onView={onViewLLMCall && call.id ? () => onViewLLMCall(call.id) : undefined}
                  />
                ))}
              </div>
            </>
          )}

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

function AgentCallBadge({ log, index, onView }: { log: AgentLog; index: number; onView?: () => void }) {
  const duration = log.completed_at && log.started_at
    ? ((new Date(log.completed_at).getTime() - new Date(log.started_at).getTime()) / 1000).toFixed(1)
    : null

  const content = (
    <>
      <div className="flex items-center space-x-2">
        <span className="font-mono text-gray-400">#{index}</span>
        <span>{log.success ? '✓' : log.error ? '✕' : '◐'}</span>
        <span>{log.iterations} iter</span>
      </div>
      <div className="flex items-center space-x-2">
        {duration && <span className="font-mono">{duration}s</span>}
        {onView && <span className="text-blue-500">→</span>}
      </div>
    </>
  )

  if (onView) {
    return (
      <button
        onClick={(e) => {
          e.stopPropagation()
          onView()
        }}
        className={`
          w-full flex items-center justify-between px-2 py-1 rounded text-xs
          ${log.success ? 'bg-green-50 text-green-700 hover:bg-green-100' : log.error ? 'bg-red-50 text-red-700 hover:bg-red-100' : 'bg-blue-50 text-blue-700 hover:bg-blue-100'}
          transition-colors cursor-pointer
        `}
      >
        {content}
      </button>
    )
  }

  return (
    <div className={`
      flex items-center justify-between px-2 py-1 rounded text-xs
      ${log.success ? 'bg-green-50 text-green-700' : log.error ? 'bg-red-50 text-red-700' : 'bg-blue-50 text-blue-700'}
    `}>
      {content}
    </div>
  )
}

function LLMCallBadge({ call, index, onView }: { call: LLMCall; index: number; onView?: () => void }) {
  const latencySec = (call.latency_ms / 1000).toFixed(1)

  const content = (
    <>
      <div className="flex items-center space-x-2">
        <span className="font-mono text-gray-400">#{index}</span>
        <span>{call.success ? '✓' : '✕'}</span>
        <span className="truncate max-w-32" title={call.model}>{call.model.split('/').pop()}</span>
      </div>
      <div className="flex items-center space-x-2">
        <span className="font-mono text-gray-500">{call.input_tokens}→{call.output_tokens}</span>
        <span className="font-mono">{latencySec}s</span>
        {onView && <span className="text-blue-500">→</span>}
      </div>
    </>
  )

  if (onView) {
    return (
      <button
        onClick={(e) => {
          e.stopPropagation()
          onView()
        }}
        className={`
          w-full flex items-center justify-between px-2 py-1 rounded text-xs
          ${call.success ? 'bg-green-50 text-green-700 hover:bg-green-100' : 'bg-red-50 text-red-700 hover:bg-red-100'}
          transition-colors cursor-pointer
        `}
      >
        {content}
      </button>
    )
  }

  return (
    <div className={`
      flex items-center justify-between px-2 py-1 rounded text-xs
      ${call.success ? 'bg-green-50 text-green-700' : 'bg-red-50 text-red-700'}
    `}>
      {content}
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
