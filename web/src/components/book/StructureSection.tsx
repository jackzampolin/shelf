import { useState } from 'react'
import { Link } from '@tanstack/react-router'
import { useQuery } from '@tanstack/react-query'
import { client, unwrap } from '@/api/client'
import type { StatusType } from '@/components/ui'
import type { StructureStatus, StageMetrics } from './types'

interface StructureSectionProps {
  structure?: StructureStatus
  bookId: string
  metrics?: Record<string, StageMetrics>
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

export function StructureSection({ structure, bookId, metrics }: StructureSectionProps) {
  const [expanded, setExpanded] = useState(false)
  const [pipelineExpanded, setPipelineExpanded] = useState(true)

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

  // Fetch LLM calls for structure stages (classify, polish)
  const { data: llmCalls } = useQuery({
    queryKey: ['book-llmcalls', bookId, 'structure-stages'],
    queryFn: async () => {
      const resp = await client.GET('/api/llmcalls', {
        params: { query: { book_id: bookId, limit: 500 } }
      })
      return unwrap(resp)
    },
    enabled: pipelineExpanded && structure?.started,
    refetchInterval: structure?.complete ? false : 5000,
  })

  // Group LLM calls by prompt_key
  const llmCallsByPrompt: Record<string, LLMCall[]> = {}
  if (llmCalls?.calls) {
    for (const call of llmCalls.calls) {
      const key = call.prompt_key || 'unknown'
      if (!llmCallsByPrompt[key]) llmCallsByPrompt[key] = []
      llmCallsByPrompt[key].push(call as LLMCall)
    }
  }

  // Map prompt keys to structure stages
  const classifyCalls = llmCallsByPrompt['stages.structure.classify'] || []
  const polishCalls = llmCallsByPrompt['stages.structure.polish'] || []

  if (!structure) return null

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

  // Determine phase status based on LLM calls and metrics
  const buildStatus: StatusType = structure.started ? (classifyCalls.length > 0 || structure.complete ? 'complete' : 'in_progress') : 'pending'
  const extractStatus: StatusType = classifyCalls.length > 0 || structure.complete ? 'complete' : (buildStatus === 'complete' ? 'in_progress' : 'pending')
  const classifyStatus: StatusType = classifyCalls.length > 0 ? 'complete' : (extractStatus === 'complete' ? 'in_progress' : 'pending')
  const polishStatus: StatusType = structure.complete ? 'complete' : (polishCalls.length > 0 ? 'in_progress' : (classifyStatus === 'complete' ? 'pending' : 'pending'))

  return (
    <div className="border-t pt-4">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center space-x-2">
          <span className="text-sm font-medium text-gray-700">Structure</span>
          <button
            onClick={() => setPipelineExpanded(!pipelineExpanded)}
            className="text-xs text-blue-600 hover:text-blue-800"
          >
            {pipelineExpanded ? 'Hide' : 'Show'} Pipeline
          </button>
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

      {/* Pipeline visualization */}
      {pipelineExpanded && (
        <div className="bg-gray-50 rounded-lg p-4 mb-3">
          <div className="flex items-center space-x-2 flex-wrap gap-y-2">
            <PipelineStage label="Build" status={buildStatus} detail={structure.chapter_count ? `${structure.chapter_count} ch` : undefined} />
            <Arrow />
            <PipelineStage label="Extract" status={extractStatus} />
            <Arrow />
            <PipelineStage
              label="Classify"
              status={classifyStatus}
              callCount={classifyCalls.length}
              metrics={metrics?.['structure-classify']}
            />
            <Arrow />
            <PipelineStage
              label="Polish"
              status={polishStatus}
              detail={polishStats.total > 0 ? `${polishStats.complete}/${polishStats.total}` : undefined}
              callCount={polishCalls.length}
              metrics={metrics?.['structure-polish']}
            />
          </div>
        </div>
      )}

      {structure.started && !structure.complete && !structure.failed && !pipelineExpanded && (
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

// Pipeline visualization components
interface PipelineStageProps {
  label: string
  status: StatusType
  detail?: string
  callCount?: number
  metrics?: StageMetrics
}

function PipelineStage({ label, status, detail, callCount, metrics }: PipelineStageProps) {
  const statusColors: Record<StatusType, string> = {
    complete: 'bg-green-100 border-green-300 text-green-800',
    in_progress: 'bg-blue-100 border-blue-300 text-blue-800',
    failed: 'bg-red-100 border-red-300 text-red-800',
    pending: 'bg-gray-100 border-gray-200 text-gray-500',
  }

  const statusDots: Record<StatusType, string> = {
    complete: '●',
    in_progress: '◐',
    failed: '✕',
    pending: '○',
  }

  return (
    <div className={`px-2 py-1 rounded border text-xs ${statusColors[status]}`}>
      <div className="flex items-center space-x-1">
        <span>{statusDots[status]}</span>
        <span className="font-medium">{label}</span>
        {callCount !== undefined && callCount > 0 && (
          <span className="text-xs opacity-70">({callCount})</span>
        )}
      </div>
      {detail && (
        <div className="text-xs opacity-70 mt-0.5">{detail}</div>
      )}
      {metrics && metrics.total_cost_usd > 0 && (
        <div className="text-xs opacity-70 mt-0.5 font-mono">
          ${metrics.total_cost_usd.toFixed(4)}
        </div>
      )}
    </div>
  )
}

function Arrow() {
  return <span className="text-gray-300 text-sm">→</span>
}
