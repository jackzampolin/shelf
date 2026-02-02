import { useState } from 'react'
import { createFileRoute, Link } from '@tanstack/react-router'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'

// Types for prompts API
interface BookPrompt {
  key: string
  text: string
  variables?: string[]
  is_override: boolean
  cid?: string
}

interface BookPromptsListResponse {
  book_id: string
  prompts: BookPrompt[]
}

interface SetPromptRequest {
  text: string
  note?: string
}

export const Route = createFileRoute('/books/$bookId/prompts')({
  component: BookPromptsPage,
})

// Group prompts by prefix
function groupByPrefix(prompts: BookPrompt[]): Record<string, BookPrompt[]> {
  const groups: Record<string, BookPrompt[]> = {}

  for (const prompt of prompts) {
    const parts = prompt.key.split('.')
    const prefix = parts.length >= 2 ? `${parts[0]}.${parts[1]}` : parts[0]

    if (!groups[prefix]) {
      groups[prefix] = []
    }
    groups[prefix].push(prompt)
  }

  for (const group of Object.values(groups)) {
    group.sort((a, b) => a.key.localeCompare(b.key))
  }

  return groups
}

function BookPromptsPage() {
  const { bookId } = Route.useParams()
  const queryClient = useQueryClient()
  const [editingKey, setEditingKey] = useState<string | null>(null)
  const [editText, setEditText] = useState<string>('')
  const [editNote, setEditNote] = useState<string>('')
  const [expandedPrompt, setExpandedPrompt] = useState<string | null>(null)

  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ['books', bookId, 'prompts'],
    queryFn: async (): Promise<BookPromptsListResponse> => {
      const res = await fetch(`/api/books/${bookId}/prompts`)
      if (!res.ok) throw new Error('Failed to load prompts')
      return res.json()
    },
  })

  const setOverrideMutation = useMutation({
    mutationFn: async ({ key, text, note }: { key: string; text: string; note: string }) => {
      const res = await fetch(`/api/books/${bookId}/prompts/${encodeURIComponent(key)}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text, note } as SetPromptRequest),
      })
      if (!res.ok) {
        const errBody = await res.json().catch(() => ({}))
        throw new Error(errBody.error || 'Failed to set override')
      }
      return res.json() as Promise<BookPrompt>
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['books', bookId, 'prompts'] })
      setEditingKey(null)
      setEditText('')
      setEditNote('')
    },
  })

  const clearOverrideMutation = useMutation({
    mutationFn: async (key: string) => {
      const res = await fetch(`/api/books/${bookId}/prompts/${encodeURIComponent(key)}`, {
        method: 'DELETE',
      })
      if (!res.ok) {
        const errBody = await res.json().catch(() => ({}))
        throw new Error(errBody.error || 'Failed to clear override')
      }
      return res.json() as Promise<BookPrompt>
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['books', bookId, 'prompts'] })
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
  const overrideCount = prompts.filter((p) => p.is_override).length

  const groupTitles: Record<string, string> = {
    'stages.ocr': 'OCR Stage',
    'stages.metadata': 'Metadata Stage',
    'stages.extract_toc': 'Extract ToC Stage',
    'agents.toc_finder': 'ToC Finder Agent',
  }

  const startEditing = (prompt: BookPrompt) => {
    setEditingKey(prompt.key)
    setEditText(prompt.text)
    setEditNote('')
  }

  const saveEdit = () => {
    if (!editingKey) return
    setOverrideMutation.mutate({ key: editingKey, text: editText, note: editNote })
  }

  const cancelEdit = () => {
    setEditingKey(null)
    setEditText('')
    setEditNote('')
  }

  return (
    <div className="space-y-6">
      {/* Breadcrumb */}
      <nav className="text-sm">
        <Link to="/books" className="text-blue-600 hover:text-blue-800">
          Library
        </Link>
        <span className="mx-2 text-gray-400">/</span>
        <Link to="/books/$bookId" params={{ bookId }} className="text-blue-600 hover:text-blue-800">
          Book
        </Link>
        <span className="mx-2 text-gray-400">/</span>
        <span className="text-gray-600">Prompts</span>
      </nav>

      <div className="flex justify-between items-center">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Book Prompts</h1>
          <p className="text-gray-500">
            Customize prompts for this book
            {overrideCount > 0 && (
              <span className="ml-2 text-blue-600">({overrideCount} override{overrideCount !== 1 ? 's' : ''})</span>
            )}
          </p>
        </div>
        <div className="flex space-x-2">
          <Link
            to="/books/$bookId"
            params={{ bookId }}
            className="inline-flex items-center px-3 py-2 border border-gray-300 shadow-sm text-sm font-medium rounded-md text-gray-700 bg-white hover:bg-gray-50"
          >
            Back to Book
          </Link>
          <button
            onClick={() => refetch()}
            className="inline-flex items-center px-3 py-2 border border-gray-300 shadow-sm text-sm font-medium rounded-md text-gray-700 bg-white hover:bg-gray-50"
          >
            Refresh
          </button>
        </div>
      </div>

      <div className="bg-blue-50 border border-blue-200 rounded-lg p-4">
        <p className="text-sm text-blue-800">
          Override prompts for this book only. Overrides will be used for all future processing of this book.
          Clear an override to revert to the default prompt.
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
            </div>
            <div className="divide-y divide-gray-200">
              {groupPrompts.map((prompt) => (
                <div key={prompt.key} className="px-6 py-4">
                  {editingKey === prompt.key ? (
                    <div className="space-y-3">
                      <div className="flex items-center justify-between">
                        <span className="text-sm font-medium text-gray-900">
                          {prompt.key}
                        </span>
                        <div className="flex space-x-2">
                          <button
                            onClick={saveEdit}
                            disabled={setOverrideMutation.isPending}
                            className="px-3 py-1 text-sm font-medium text-white bg-blue-600 rounded hover:bg-blue-700 disabled:opacity-50"
                          >
                            {setOverrideMutation.isPending ? 'Saving...' : 'Save'}
                          </button>
                          <button
                            onClick={cancelEdit}
                            className="px-3 py-1 text-sm font-medium text-gray-600 bg-gray-100 rounded hover:bg-gray-200"
                          >
                            Cancel
                          </button>
                        </div>
                      </div>
                      <textarea
                        value={editText}
                        onChange={(e) => setEditText(e.target.value)}
                        className="w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm font-mono text-sm focus:ring-blue-500 focus:border-blue-500"
                        rows={12}
                      />
                      <input
                        type="text"
                        value={editNote}
                        onChange={(e) => setEditNote(e.target.value)}
                        placeholder="Note about this change (optional)"
                        className="w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm text-sm focus:ring-blue-500 focus:border-blue-500"
                      />
                      {setOverrideMutation.isError && (
                        <p className="text-sm text-red-600">
                          Error: {setOverrideMutation.error?.message}
                        </p>
                      )}
                    </div>
                  ) : (
                    <div className="flex items-start justify-between">
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center space-x-2">
                          <span className="text-sm font-medium text-gray-900">
                            {prompt.key.split('.').pop()}
                          </span>
                          <span className="text-xs text-gray-400 font-mono">
                            {prompt.key}
                          </span>
                          {prompt.is_override && (
                            <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-yellow-100 text-yellow-800">
                              Override
                            </span>
                          )}
                        </div>
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
                        {prompt.cid && (
                          <div className="mt-1 text-xs text-gray-400 font-mono">
                            CID: {prompt.cid.substring(0, 16)}...
                          </div>
                        )}
                      </div>
                      <div className="flex space-x-2 ml-4">
                        <button
                          onClick={() =>
                            setExpandedPrompt(expandedPrompt === prompt.key ? null : prompt.key)
                          }
                          className="text-sm text-gray-600 hover:text-gray-800"
                        >
                          {expandedPrompt === prompt.key ? 'Hide' : 'View'}
                        </button>
                        <button
                          onClick={() => startEditing(prompt)}
                          className="text-sm text-blue-600 hover:text-blue-800"
                        >
                          Edit
                        </button>
                        {prompt.is_override && (
                          <button
                            onClick={() => clearOverrideMutation.mutate(prompt.key)}
                            disabled={clearOverrideMutation.isPending}
                            className="text-sm text-red-600 hover:text-red-800 disabled:opacity-50"
                          >
                            Clear
                          </button>
                        )}
                      </div>
                    </div>
                  )}

                  {expandedPrompt === prompt.key && editingKey !== prompt.key && (
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
