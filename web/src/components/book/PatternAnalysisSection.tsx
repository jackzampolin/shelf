import { StatusBadge } from '@/components/ui'
import type { StageMetrics } from './types'

interface PageNumberPattern {
  location?: string
  position?: string
  format?: string
  start_page?: number
  end_page?: number | null
  start_value?: number
  has_gaps?: boolean
  gap_ranges?: Array<{ start_page: number; end_page: number; reason: string }>
  confidence?: string
  sample_pages?: number[]
  reasoning?: string
}

interface ChapterPattern {
  cluster_id?: string
  running_header?: string
  start_page?: number
  end_page?: number
  chapter_number?: number | null
  chapter_title?: string
  confidence?: string
  reasoning?: string
}

interface BodyBoundaries {
  body_start_page?: number
  body_end_page?: number | null
  confidence?: string
  reasoning?: string
}

interface PagePatternAnalysis {
  page_number_pattern?: PageNumberPattern | null
  chapter_patterns?: ChapterPattern[]
  body_boundaries?: BodyBoundaries | null
  reasoning?: string
}

interface PatternAnalysisSectionProps {
  patternAnalysisJSON?: string
  complete?: boolean
  cost?: number
  metrics?: StageMetrics
}

export function PatternAnalysisSection({
  patternAnalysisJSON,
  complete,
  cost,
  metrics,
}: PatternAnalysisSectionProps) {
  let patternData: PagePatternAnalysis | null = null

  if (patternAnalysisJSON) {
    try {
      patternData = JSON.parse(patternAnalysisJSON)
    } catch (e) {
      console.error('Failed to parse pattern analysis JSON:', e)
    }
  }

  const status = complete ? 'complete' : patternData ? 'in_progress' : 'pending'

  return (
    <div className="border-t pt-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center space-x-2">
          <span className="text-sm font-medium text-gray-700">Pattern Analysis</span>
          <StatusBadge status={status} />
        </div>
        <div className="flex items-center space-x-2">
          {cost !== undefined && (
            <span className="font-mono text-sm text-gray-500">${cost.toFixed(4)}</span>
          )}
        </div>
      </div>

      {/* Metrics */}
      {metrics && metrics.count > 0 && (
        <div className="bg-gray-50 rounded px-3 py-2 mt-2 text-xs">
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
          </div>
        </div>
      )}

      {/* Pattern Analysis Results */}
      {patternData && (
        <div className="mt-3 pl-4 space-y-3 text-sm">
          {/* Page Number Pattern */}
          {patternData.page_number_pattern && (
            <div className="bg-blue-50 rounded p-3">
              <div className="font-medium text-blue-900 mb-2">Page Numbering Pattern</div>
              <div className="space-y-1 text-blue-800">
                <div className="flex items-center space-x-4">
                  <span>
                    <strong>Location:</strong> {patternData.page_number_pattern.location}
                  </span>
                  <span>
                    <strong>Position:</strong> {patternData.page_number_pattern.position}
                  </span>
                  <span>
                    <strong>Format:</strong> {patternData.page_number_pattern.format}
                  </span>
                  <span className={`px-2 py-0.5 rounded text-xs ${
                    patternData.page_number_pattern.confidence === 'high'
                      ? 'bg-green-100 text-green-800'
                      : patternData.page_number_pattern.confidence === 'medium'
                      ? 'bg-yellow-100 text-yellow-800'
                      : 'bg-gray-100 text-gray-800'
                  }`}>
                    {patternData.page_number_pattern.confidence} confidence
                  </span>
                </div>
                <div>
                  <strong>Range:</strong> pages {patternData.page_number_pattern.start_page}
                  {patternData.page_number_pattern.end_page
                    ? ` - ${patternData.page_number_pattern.end_page}`
                    : ' - end'}
                  {' '}(starting at value {patternData.page_number_pattern.start_value})
                </div>
                {patternData.page_number_pattern.has_gaps &&
                 patternData.page_number_pattern.gap_ranges &&
                 patternData.page_number_pattern.gap_ranges.length > 0 && (
                  <div>
                    <strong>Gaps:</strong>{' '}
                    {patternData.page_number_pattern.gap_ranges.map((gap, i) => (
                      <span key={i} className="mr-2">
                        p{gap.start_page}-{gap.end_page} ({gap.reason})
                      </span>
                    ))}
                  </div>
                )}
              </div>
            </div>
          )}

          {/* Body Boundaries */}
          {patternData.body_boundaries && (
            <div className="bg-purple-50 rounded p-3">
              <div className="font-medium text-purple-900 mb-2">Body Boundaries</div>
              <div className="space-y-1 text-purple-800">
                <div className="flex items-center space-x-4">
                  <span>
                    <strong>Body starts:</strong> page {patternData.body_boundaries.body_start_page}
                  </span>
                  {patternData.body_boundaries.body_end_page && (
                    <span>
                      <strong>Body ends:</strong> page {patternData.body_boundaries.body_end_page}
                    </span>
                  )}
                  <span className={`px-2 py-0.5 rounded text-xs ${
                    patternData.body_boundaries.confidence === 'high'
                      ? 'bg-green-100 text-green-800'
                      : patternData.body_boundaries.confidence === 'medium'
                      ? 'bg-yellow-100 text-yellow-800'
                      : 'bg-gray-100 text-gray-800'
                  }`}>
                    {patternData.body_boundaries.confidence} confidence
                  </span>
                </div>
              </div>
            </div>
          )}

          {/* Chapter Patterns */}
          {patternData.chapter_patterns && patternData.chapter_patterns.length > 0 && (
            <div className="bg-green-50 rounded p-3">
              <div className="font-medium text-green-900 mb-2">
                Chapter Patterns ({patternData.chapter_patterns.length} clusters)
              </div>
              <div className="space-y-2 text-green-800 max-h-48 overflow-y-auto">
                {patternData.chapter_patterns.map((pattern, i) => (
                  <div key={i} className="border-l-2 border-green-300 pl-2">
                    <div className="font-medium">{pattern.chapter_title}</div>
                    <div className="text-xs space-x-2">
                      <span>p{pattern.start_page} - {pattern.end_page}</span>
                      {pattern.chapter_number !== null && pattern.chapter_number !== undefined && (
                        <span>• Ch {pattern.chapter_number}</span>
                      )}
                      {pattern.running_header && (
                        <span>• Header: "{pattern.running_header}"</span>
                      )}
                      <span className={`px-1.5 py-0.5 rounded ${
                        pattern.confidence === 'high'
                          ? 'bg-green-100 text-green-800'
                          : pattern.confidence === 'medium'
                          ? 'bg-yellow-100 text-yellow-800'
                          : 'bg-gray-100 text-gray-800'
                      }`}>
                        {pattern.confidence}
                      </span>
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
