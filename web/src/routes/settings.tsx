import { useState } from 'react'
import { createFileRoute } from '@tanstack/react-router'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'

// Types for settings API (not yet in generated types)
interface ConfigEntry {
  key: string
  value: unknown
  description: string
  _docID?: string
}

interface SettingsResponse {
  settings: Record<string, ConfigEntry>
}

interface SettingResponse {
  entry: ConfigEntry
}

export const Route = createFileRoute('/settings')({
  component: SettingsPage,
})

// Group settings by prefix
function groupByPrefix(settings: Record<string, ConfigEntry>): Record<string, ConfigEntry[]> {
  const groups: Record<string, ConfigEntry[]> = {}

  for (const [key, entry] of Object.entries(settings)) {
    // Extract prefix (e.g., "providers.ocr" from "providers.ocr.mistral.type")
    const parts = key.split('.')
    const prefix = parts.length >= 2 ? `${parts[0]}.${parts[1]}` : parts[0]

    if (!groups[prefix]) {
      groups[prefix] = []
    }
    groups[prefix].push({ ...entry, key })
  }

  // Sort entries within each group
  for (const entries of Object.values(groups)) {
    entries.sort((a, b) => a.key.localeCompare(b.key))
  }

  return groups
}

function SettingsPage() {
  const queryClient = useQueryClient()
  const [editingKey, setEditingKey] = useState<string | null>(null)
  const [editValue, setEditValue] = useState<string>('')

  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ['settings'],
    queryFn: async (): Promise<SettingsResponse> => {
      const res = await fetch('/api/settings')
      if (!res.ok) throw new Error('Failed to load settings')
      return res.json()
    },
  })

  const updateMutation = useMutation({
    mutationFn: async ({ key, value }: { key: string; value: unknown }) => {
      const res = await fetch(`/api/settings/${encodeURIComponent(key)}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ value }),
      })
      if (!res.ok) throw new Error('Failed to update setting')
      return res.json() as Promise<SettingResponse>
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['settings'] })
      setEditingKey(null)
    },
  })

  const resetMutation = useMutation({
    mutationFn: async (key: string) => {
      const res = await fetch(`/api/settings/reset/${encodeURIComponent(key)}`, {
        method: 'POST',
      })
      if (!res.ok) throw new Error('Failed to reset setting')
      return res.json() as Promise<SettingResponse>
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['settings'] })
    },
  })

  if (isLoading) {
    return (
      <div className="text-center py-12">
        <div className="text-gray-500">Loading settings...</div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="text-center py-12">
        <div className="text-red-500">Error loading settings: {error.message}</div>
      </div>
    )
  }

  const settings = data?.settings || {}
  const groups = groupByPrefix(settings)

  const startEditing = (entry: ConfigEntry) => {
    setEditingKey(entry.key)
    // Format the value for editing
    const val = entry.value
    setEditValue(typeof val === 'string' ? val : JSON.stringify(val, null, 2))
  }

  const saveEdit = () => {
    if (!editingKey) return

    // Try to parse as JSON, fallback to string
    let parsedValue: unknown
    try {
      parsedValue = JSON.parse(editValue)
    } catch {
      parsedValue = editValue
    }

    updateMutation.mutate({ key: editingKey, value: parsedValue })
  }

  const cancelEdit = () => {
    setEditingKey(null)
    setEditValue('')
  }

  const formatValue = (value: unknown): string => {
    if (typeof value === 'string') return value
    return JSON.stringify(value)
  }

  const isEnvVar = (value: unknown): boolean => {
    return typeof value === 'string' && value.startsWith('${') && value.endsWith('}')
  }

  const groupTitles: Record<string, string> = {
    'providers.ocr': 'OCR Providers',
    'providers.llm': 'LLM Providers',
    defaults: 'Default Settings',
  }

  return (
    <div className="space-y-6">
      <div className="flex justify-between items-center">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Settings</h1>
          <p className="text-gray-500">
            Configure providers and default settings
          </p>
        </div>
        <button
          onClick={() => refetch()}
          className="inline-flex items-center px-3 py-2 border border-gray-300 shadow-sm text-sm font-medium rounded-md text-gray-700 bg-white hover:bg-gray-50"
        >
          Refresh
        </button>
      </div>

      {Object.entries(groups)
        .sort(([a], [b]) => a.localeCompare(b))
        .map(([prefix, entries]) => (
          <div key={prefix} className="bg-white rounded-lg shadow overflow-hidden">
            <div className="px-6 py-4 bg-gray-50 border-b border-gray-200">
              <h2 className="text-lg font-medium text-gray-900">
                {groupTitles[prefix] || prefix}
              </h2>
            </div>
            <div className="divide-y divide-gray-200">
              {entries.map((entry) => (
                <div key={entry.key} className="px-6 py-4">
                  {editingKey === entry.key ? (
                    <div className="space-y-3">
                      <div className="flex items-center justify-between">
                        <span className="text-sm font-medium text-gray-500">
                          {entry.key}
                        </span>
                        <div className="flex space-x-2">
                          <button
                            onClick={saveEdit}
                            disabled={updateMutation.isPending}
                            className="px-3 py-1 text-sm font-medium text-white bg-blue-600 rounded hover:bg-blue-700 disabled:opacity-50"
                          >
                            {updateMutation.isPending ? 'Saving...' : 'Save'}
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
                        value={editValue}
                        onChange={(e) => setEditValue(e.target.value)}
                        className="w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm font-mono text-sm focus:ring-blue-500 focus:border-blue-500"
                        rows={typeof entry.value === 'object' ? 4 : 1}
                      />
                      {entry.description && (
                        <p className="text-sm text-gray-500">{entry.description}</p>
                      )}
                    </div>
                  ) : (
                    <div className="flex items-start justify-between">
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center space-x-2">
                          <span className="text-sm font-medium text-gray-900">
                            {entry.key.split('.').pop()}
                          </span>
                          <span className="text-xs text-gray-400 font-mono">
                            {entry.key}
                          </span>
                        </div>
                        <div className="mt-1 flex items-center space-x-2">
                          {isEnvVar(entry.value) ? (
                            <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-purple-100 text-purple-800 font-mono">
                              {formatValue(entry.value)}
                            </span>
                          ) : (
                            <span className="text-sm text-gray-600 font-mono">
                              {formatValue(entry.value)}
                            </span>
                          )}
                        </div>
                        {entry.description && (
                          <p className="mt-1 text-sm text-gray-500">
                            {entry.description}
                          </p>
                        )}
                      </div>
                      <div className="flex space-x-2 ml-4">
                        <button
                          onClick={() => startEditing(entry)}
                          className="text-sm text-blue-600 hover:text-blue-800"
                        >
                          Edit
                        </button>
                        <button
                          onClick={() => resetMutation.mutate(entry.key)}
                          disabled={resetMutation.isPending}
                          className="text-sm text-gray-500 hover:text-gray-700"
                        >
                          Reset
                        </button>
                      </div>
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
