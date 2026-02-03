import { useState } from 'react'
import { createFileRoute } from '@tanstack/react-router'
import { useQuery } from '@tanstack/react-query'

// Types for prompts API (not yet in generated types)
interface Prompt {
  key: string
  text: string
  description?: string
  variables?: string[]
  hash?: string
  doc_id?: string
}

interface PromptsListResponse {
  prompts: Prompt[]
}

export const Route = createFileRoute('/prompts')({
  component: PromptsPage,
})

// Group prompts by prefix (stages.ocr.system -> stages.ocr)
function groupByPrefix(prompts: Prompt[]): Record<string, Prompt[]> {
  const groups: Record<string, Prompt[]> = {}

  for (const prompt of prompts) {
    const parts = prompt.key.split('.')
    // Use first two parts as prefix (e.g., "stages.ocr" or "agents.toc_finder")
    const prefix = parts.length >= 2 ? `${parts[0]}.${parts[1]}` : parts[0]

    if (!groups[prefix]) {
      groups[prefix] = []
    }
    groups[prefix].push(prompt)
  }

  // Sort prompts within each group
  for (const group of Object.values(groups)) {
    group.sort((a, b) => a.key.localeCompare(b.key))
  }

  return groups
}

function PromptsPage() {
  const [expandedPrompt, setExpandedPrompt] = useState<string | null>(null)

  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ['prompts'],
    queryFn: async (): Promise<PromptsListResponse> => {
      const res = await fetch('/api/prompts')
      if (!res.ok) throw new Error('Failed to load prompts')
      return res.json()
    },
  })

  if (isLoading) {
    return (
      <div className="text-center py-12">
        <div className="text-gray-500">Loading prompts...</div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="text-center py-12">
        <div className="text-red-500">Error loading prompts: {error.message}</div>
      </div>
    )
  }

  const prompts = data?.prompts || []
  const groups = groupByPrefix(prompts)

  const groupTitles: Record<string, string> = {
    'stages.ocr': 'OCR Stage',
    'stages.metadata': 'Metadata Stage',
    'stages.extract_toc': 'Extract ToC Stage',
    'agents.toc_finder': 'ToC Finder Agent',
  }

  return (
    <div className="space-y-6">
      <div className="flex justify-between items-center">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Prompts</h1>
          <p className="text-gray-500">
            View and manage system prompts for processing stages
          </p>
        </div>
        <button
          onClick={() => refetch()}
          className="inline-flex items-center px-3 py-2 border border-gray-300 shadow-sm text-sm font-medium rounded-md text-gray-700 bg-white hover:bg-gray-50"
        >
          Refresh
        </button>
      </div>

      <div className="bg-blue-50 border border-blue-200 rounded-lg p-4">
        <p className="text-sm text-blue-800">
          These are the default prompts embedded in the code. To customize a prompt for a specific book,
          navigate to the book's detail page and use the Prompts tab. Book-level overrides take precedence
          over these defaults.
        </p>
      </div>

      {Object.entries(groups)
        .sort(([a], [b]) => a.localeCompare(b))
        .map(([prefix, groupPrompts]) => (
          <div key={prefix} className="bg-white rounded-lg shadow overflow-hidden">
            <div className="px-6 py-4 bg-gray-50 border-b border-gray-200">
              <h2 className="text-lg font-medium text-gray-900">
                {groupTitles[prefix] || prefix}
              </h2>
              <p className="text-sm text-gray-500 mt-1">
                {groupPrompts.length} prompt{groupPrompts.length !== 1 ? 's' : ''}
              </p>
            </div>
            <div className="divide-y divide-gray-200">
              {groupPrompts.map((prompt) => (
                <div key={prompt.key} className="px-6 py-4">
                  <div className="flex items-start justify-between">
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center space-x-2">
                        <span className="text-sm font-medium text-gray-900">
                          {prompt.key.split('.').pop()}
                        </span>
                        <span className="text-xs text-gray-400 font-mono">
                          {prompt.key}
                        </span>
                      </div>
                      {prompt.description && (
                        <p className="mt-1 text-sm text-gray-500">{prompt.description}</p>
                      )}
                      {prompt.variables && prompt.variables.length > 0 && (
                        <div className="mt-2 flex flex-wrap gap-1">
                          {prompt.variables.map((v) => (
                            <span
                              key={v}
                              className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-purple-100 text-purple-800 font-mono"
                            >
                              {`{{.${v}}}`}
                            </span>
                          ))}
                        </div>
                      )}
                      {prompt.hash && (
                        <div className="mt-1 text-xs text-gray-400 font-mono">
                          Hash: {prompt.hash.substring(0, 12)}...
                        </div>
                      )}
                    </div>
                    <button
                      onClick={() =>
                        setExpandedPrompt(expandedPrompt === prompt.key ? null : prompt.key)
                      }
                      className="ml-4 text-sm text-blue-600 hover:text-blue-800"
                    >
                      {expandedPrompt === prompt.key ? 'Hide' : 'View'}
                    </button>
                  </div>

                  {expandedPrompt === prompt.key && (
                    <div className="mt-4">
                      <pre className="bg-gray-50 rounded-lg p-4 text-sm text-gray-800 whitespace-pre-wrap font-mono overflow-x-auto max-h-96">
                        {prompt.text}
                      </pre>
                    </div>
                  )}
                </div>
              ))}
            </div>
          </div>
        ))}
    </div>
  )
}
