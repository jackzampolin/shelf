import { useState } from 'react'
import { createFileRoute } from '@tanstack/react-router'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'

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

interface ProviderGroup {
  name: string
  label: string
  settings: ConfigEntry[]
}

interface CategoryGroup {
  category: string
  label: string
  providers: ProviderGroup[]
}

export const Route = createFileRoute('/settings')({
  component: SettingsPage,
})

// Group settings by category and provider
function groupByProvider(settings: Record<string, ConfigEntry>): CategoryGroup[] {
  const categoryMap: Record<string, Record<string, ConfigEntry[]>> = {}

  for (const [key, entry] of Object.entries(settings)) {
    const parts = key.split('.')

    if (parts[0] === 'providers' && parts.length >= 4) {
      // providers.ocr.mistral.type -> category=providers.ocr, provider=mistral
      const category = `${parts[0]}.${parts[1]}`
      const provider = parts[2]

      if (!categoryMap[category]) categoryMap[category] = {}
      if (!categoryMap[category][provider]) categoryMap[category][provider] = []
      categoryMap[category][provider].push({ ...entry, key })
    } else if (parts[0] === 'defaults') {
      // defaults.ocr_providers -> category=defaults, provider=_root
      const category = 'defaults'
      const provider = '_root'

      if (!categoryMap[category]) categoryMap[category] = {}
      if (!categoryMap[category][provider]) categoryMap[category][provider] = []
      categoryMap[category][provider].push({ ...entry, key })
    }
  }

  const categoryLabels: Record<string, string> = {
    'providers.ocr': 'OCR Providers',
    'providers.llm': 'LLM Providers',
    'defaults': 'Defaults',
  }

  const providerLabels: Record<string, string> = {
    mistral: 'Mistral',
    paddle: 'Paddle',
    openrouter: 'OpenRouter',
    _root: 'Settings',
  }

  const result: CategoryGroup[] = []

  // Sort categories: providers.llm, providers.ocr, defaults
  const sortedCategories = Object.keys(categoryMap).sort((a, b) => {
    const order = ['providers.llm', 'providers.ocr', 'defaults']
    return order.indexOf(a) - order.indexOf(b)
  })

  for (const category of sortedCategories) {
    const providers = categoryMap[category]
    const providerGroups: ProviderGroup[] = []

    for (const [provider, entries] of Object.entries(providers)) {
      entries.sort((a, b) => {
        // Sort: type first, then enabled last, rest alphabetically
        const aName = a.key.split('.').pop() || ''
        const bName = b.key.split('.').pop() || ''
        if (aName === 'type') return -1
        if (bName === 'type') return 1
        if (aName === 'enabled') return 1
        if (bName === 'enabled') return -1
        return aName.localeCompare(bName)
      })

      providerGroups.push({
        name: provider,
        label: providerLabels[provider] || provider,
        settings: entries,
      })
    }

    result.push({
      category,
      label: categoryLabels[category] || category,
      providers: providerGroups,
    })
  }

  return result
}

// Tooltip component
function Tooltip({ content, children }: { content: string; children: React.ReactNode }) {
  if (!content) return <>{children}</>

  return (
    <div className="group relative inline-block">
      {children}
      <div className="invisible group-hover:visible absolute z-10 w-64 px-3 py-2 text-sm text-gray-600 bg-white border border-gray-200 rounded-lg shadow-lg -top-2 left-full ml-2">
        {content}
        <div className="absolute w-2 h-2 bg-white border-l border-b border-gray-200 transform rotate-45 top-3 -left-1" />
      </div>
    </div>
  )
}

// Compact setting row
function SettingRow({
  entry,
  isEditing,
  editValue,
  onEditValueChange,
  onStartEdit,
  onSaveEdit,
  onCancelEdit,
  onReset,
  onToggle,
  isSaving,
  isResetting,
}: {
  entry: ConfigEntry
  isEditing: boolean
  editValue: string
  onEditValueChange: (value: string) => void
  onStartEdit: () => void
  onSaveEdit: () => void
  onCancelEdit: () => void
  onReset: () => void
  onToggle?: (value: boolean) => void
  isSaving: boolean
  isResetting: boolean
}) {
  const shortName = entry.key.split('.').pop() || entry.key
  const isBoolean = typeof entry.value === 'boolean'
  const isEnvVar = typeof entry.value === 'string' && entry.value.startsWith('${') && entry.value.endsWith('}')

  const formatValue = (value: unknown): string => {
    if (typeof value === 'string') return value
    return JSON.stringify(value)
  }

  if (isEditing) {
    return (
      <div className="py-2 px-3 bg-blue-50 rounded">
        <div className="flex items-center justify-between mb-2">
          <span className="text-sm font-medium text-gray-700">{shortName}</span>
          <div className="flex space-x-2">
            <button
              onClick={onSaveEdit}
              disabled={isSaving}
              className="px-2 py-1 text-xs font-medium text-white bg-blue-600 rounded hover:bg-blue-700 disabled:opacity-50"
            >
              {isSaving ? 'Saving...' : 'Save'}
            </button>
            <button
              onClick={onCancelEdit}
              className="px-2 py-1 text-xs font-medium text-gray-600 bg-gray-100 rounded hover:bg-gray-200"
            >
              Cancel
            </button>
          </div>
        </div>
        <textarea
          value={editValue}
          onChange={(e) => onEditValueChange(e.target.value)}
          className="w-full px-2 py-1 border border-gray-300 rounded text-sm font-mono focus:ring-blue-500 focus:border-blue-500"
          rows={typeof entry.value === 'object' ? 3 : 1}
        />
        {entry.description && (
          <p className="mt-1 text-xs text-gray-500">{entry.description}</p>
        )}
      </div>
    )
  }

  return (
    <div className="flex items-center justify-between py-1.5 px-3 hover:bg-gray-50 rounded group">
      <div className="flex items-center space-x-3 min-w-0 flex-1">
        <Tooltip content={entry.description}>
          <span className="text-sm text-gray-600 w-24 flex-shrink-0">{shortName}</span>
        </Tooltip>

        {isBoolean ? (
          <button
            onClick={() => onToggle?.(!entry.value)}
            className={`relative inline-flex h-5 w-9 flex-shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 ease-in-out focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 ${
              entry.value ? 'bg-blue-600' : 'bg-gray-200'
            }`}
          >
            <span
              className={`pointer-events-none inline-block h-4 w-4 transform rounded-full bg-white shadow ring-0 transition duration-200 ease-in-out ${
                entry.value ? 'translate-x-4' : 'translate-x-0'
              }`}
            />
          </button>
        ) : isEnvVar ? (
          <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-purple-100 text-purple-800 font-mono truncate">
            {formatValue(entry.value)}
          </span>
        ) : (
          <span className="text-sm text-gray-800 font-mono truncate">
            {formatValue(entry.value)}
          </span>
        )}
      </div>

      <div className="flex space-x-2 opacity-0 group-hover:opacity-100 transition-opacity ml-2">
        {!isBoolean && (
          <button
            onClick={onStartEdit}
            className="text-xs text-blue-600 hover:text-blue-800"
          >
            Edit
          </button>
        )}
        <button
          onClick={onReset}
          disabled={isResetting}
          className="text-xs text-gray-400 hover:text-gray-600"
        >
          Reset
        </button>
      </div>
    </div>
  )
}

// Collapsible provider card
function ProviderCard({
  provider,
  settings,
  defaultExpanded = false,
  editingKey,
  editValue,
  onEditValueChange,
  onStartEdit,
  onSaveEdit,
  onCancelEdit,
  onReset,
  onToggle,
  isSaving,
  isResetting,
}: {
  provider: ProviderGroup
  settings: ConfigEntry[]
  defaultExpanded?: boolean
  editingKey: string | null
  editValue: string
  onEditValueChange: (value: string) => void
  onStartEdit: (entry: ConfigEntry) => void
  onSaveEdit: () => void
  onCancelEdit: () => void
  onReset: (key: string) => void
  onToggle: (key: string, value: boolean) => void
  isSaving: boolean
  isResetting: boolean
}) {
  const [isExpanded, setIsExpanded] = useState(defaultExpanded)

  // Get enabled status for badge
  const enabledSetting = settings.find(s => s.key.endsWith('.enabled'))
  const isEnabled = enabledSetting?.value === true

  return (
    <div className="border border-gray-200 rounded-lg overflow-hidden">
      <button
        onClick={() => setIsExpanded(!isExpanded)}
        className="w-full flex items-center justify-between px-4 py-2.5 bg-gray-50 hover:bg-gray-100 transition-colors"
      >
        <div className="flex items-center space-x-3">
          <span className={`transform transition-transform ${isExpanded ? 'rotate-90' : ''}`}>
            <svg className="w-4 h-4 text-gray-500" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
            </svg>
          </span>
          <span className="font-medium text-gray-900">{provider.label}</span>
        </div>
        {enabledSetting !== undefined && (
          <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium ${
            isEnabled ? 'bg-green-100 text-green-800' : 'bg-gray-100 text-gray-600'
          }`}>
            {isEnabled ? 'Enabled' : 'Disabled'}
          </span>
        )}
      </button>

      {isExpanded && (
        <div className="border-t border-gray-200 py-1">
          {settings.map((entry) => (
            <SettingRow
              key={entry.key}
              entry={entry}
              isEditing={editingKey === entry.key}
              editValue={editValue}
              onEditValueChange={onEditValueChange}
              onStartEdit={() => onStartEdit(entry)}
              onSaveEdit={onSaveEdit}
              onCancelEdit={onCancelEdit}
              onReset={() => onReset(entry.key)}
              onToggle={(value) => onToggle(entry.key, value)}
              isSaving={isSaving}
              isResetting={isResetting}
            />
          ))}
        </div>
      )}
    </div>
  )
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
  const categories = groupByProvider(settings)

  const startEditing = (entry: ConfigEntry) => {
    setEditingKey(entry.key)
    const val = entry.value
    setEditValue(typeof val === 'string' ? val : JSON.stringify(val, null, 2))
  }

  const saveEdit = () => {
    if (!editingKey) return
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

  const handleToggle = (key: string, value: boolean) => {
    updateMutation.mutate({ key, value })
  }

  const handleReset = (key: string) => {
    resetMutation.mutate(key)
  }

  return (
    <div className="space-y-6">
      <div className="flex justify-between items-center">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Settings</h1>
          <p className="text-gray-500 text-sm">
            Configure providers and defaults. Click a provider to expand.
          </p>
        </div>
        <button
          onClick={() => refetch()}
          className="inline-flex items-center px-3 py-1.5 border border-gray-300 shadow-sm text-sm font-medium rounded-md text-gray-700 bg-white hover:bg-gray-50"
        >
          Refresh
        </button>
      </div>

      {categories.map((category) => (
        <div key={category.category}>
          <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wider mb-3">
            {category.label}
          </h2>
          <div className="space-y-2">
            {category.providers.map((provider) => (
              provider.name === '_root' ? (
                // Defaults section - no collapsible card, just rows
                <div key={provider.name} className="bg-white rounded-lg border border-gray-200 py-1">
                  {provider.settings.map((entry) => (
                    <SettingRow
                      key={entry.key}
                      entry={entry}
                      isEditing={editingKey === entry.key}
                      editValue={editValue}
                      onEditValueChange={setEditValue}
                      onStartEdit={() => startEditing(entry)}
                      onSaveEdit={saveEdit}
                      onCancelEdit={cancelEdit}
                      onReset={() => handleReset(entry.key)}
                      onToggle={(value) => handleToggle(entry.key, value)}
                      isSaving={updateMutation.isPending}
                      isResetting={resetMutation.isPending}
                    />
                  ))}
                </div>
              ) : (
                <ProviderCard
                  key={provider.name}
                  provider={provider}
                  settings={provider.settings}
                  defaultExpanded={false}
                  editingKey={editingKey}
                  editValue={editValue}
                  onEditValueChange={setEditValue}
                  onStartEdit={startEditing}
                  onSaveEdit={saveEdit}
                  onCancelEdit={cancelEdit}
                  onReset={handleReset}
                  onToggle={handleToggle}
                  isSaving={updateMutation.isPending}
                  isResetting={resetMutation.isPending}
                />
              )
            ))}
          </div>
        </div>
      ))}
    </div>
  )
}
