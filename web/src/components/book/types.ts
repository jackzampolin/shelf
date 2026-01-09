export interface StageMetrics {
  count: number
  success_count: number
  error_count: number
  total_cost_usd: number
  avg_cost_usd: number
  latency_p50: number
  latency_p95: number
  latency_p99: number
  latency_avg: number
  latency_min: number
  latency_max: number
  total_prompt_tokens: number
  total_completion_tokens: number
  total_reasoning_tokens: number
  total_tokens: number
  avg_prompt_tokens: number
  avg_completion_tokens: number
  avg_reasoning_tokens: number
  avg_total_tokens: number
}

export interface TocEntry {
  entry_number?: string
  title?: string
  level?: number
  level_name?: string
  printed_page_number?: string
  sort_order?: number
  actual_page_num?: number
  is_linked?: boolean
  source?: string
}

export interface PatternAnalysisResult {
  reasoning?: string
  patterns?: DiscoveredPattern[]
  excluded_ranges?: ExcludedRange[]
}

export interface DiscoveredPattern {
  pattern_type?: string
  level_name?: string
  heading_format?: string
  range_start?: string
  range_end?: string
  level?: number
  reasoning?: string
}

export interface ExcludedRange {
  start_page?: number
  end_page?: number
  reason?: string
}

export interface TocStatus {
  finder_started?: boolean
  finder_complete?: boolean
  finder_failed?: boolean
  found?: boolean
  start_page?: number
  end_page?: number
  extract_started?: boolean
  extract_complete?: boolean
  extract_failed?: boolean
  link_started?: boolean
  link_complete?: boolean
  link_failed?: boolean
  link_retries?: number
  finalize_started?: boolean
  finalize_complete?: boolean
  finalize_failed?: boolean
  finalize_retries?: number
  // Finalize sub-phases
  pattern_complete?: boolean
  pattern_analysis?: PatternAnalysisResult
  patterns_found?: number
  excluded_ranges?: number
  entries_to_find?: number
  entries_discovered?: number
  discover_complete?: boolean
  validate_complete?: boolean
  // Entry data
  entry_count?: number
  entries_linked?: number
  entries?: TocEntry[]
  cost_usd?: number
}

export interface StructureStatus {
  started?: boolean
  complete?: boolean
  failed?: boolean
  retries?: number
  cost_usd?: number
  chapter_count?: number
}

export interface AgentLogSummary {
  id?: string
  agent_type?: string
  started_at?: string
  completed_at?: string
  iterations?: number
  success?: boolean
  error?: string
}

export interface Message {
  role?: string
  content?: string
  tool_call_id?: string
}

export interface ToolCall {
  tool_name?: string
  timestamp?: string
  iteration?: number
  args_json?: string
  result_len?: number
  error?: string
}

export const AGENT_CATEGORIES: Record<string, { label: string; agents: string[] }> = {
  toc: {
    label: 'Table of Contents',
    agents: ['toc_finder', 'toc_extract', 'toc_entry_finder'],
  },
  structure: {
    label: 'Structure',
    agents: ['chapter_classifier', 'chapter_polisher', 'common_structure'],
  },
  metadata: {
    label: 'Metadata',
    agents: ['metadata_extract'],
  },
}

export function getAgentCategory(agentType: string): string {
  for (const [category, config] of Object.entries(AGENT_CATEGORIES)) {
    if (config.agents.some(a => agentType.toLowerCase().includes(a.toLowerCase()))) {
      return category
    }
  }
  return 'other'
}

export function getAgentDisplayName(agentType: string): string {
  const names: Record<string, string> = {
    toc_finder: 'ToC Finder',
    toc_extract: 'ToC Extract',
    toc_entry_finder: 'Entry Finder',
    chapter_classifier: 'Classifier',
    chapter_polisher: 'Polisher',
    metadata_extract: 'Metadata',
    common_structure: 'Structure Build',
  }
  for (const [key, name] of Object.entries(names)) {
    if (agentType.toLowerCase().includes(key.toLowerCase())) {
      return name
    }
  }
  return agentType
}
