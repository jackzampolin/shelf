function formatKey(key: string): string {
  return key
    .replace(/_/g, ' ')
    .replace(/([a-z])([A-Z])/g, '$1 $2')
    .replace(/^./, (s) => s.toUpperCase())
}

function isSimpleValue(value: unknown): boolean {
  return (
    value === null ||
    value === undefined ||
    typeof value === 'boolean' ||
    typeof value === 'number' ||
    typeof value === 'string'
  )
}

export function KeyValueDisplay({ data, depth = 0 }: { data: unknown; depth?: number }) {
  if (data === null || data === undefined) {
    return <span className="text-gray-400 italic">null</span>
  }

  if (typeof data === 'boolean') {
    return (
      <span className={data ? 'text-green-600' : 'text-red-600'}>
        {data ? '✓ true' : '✗ false'}
      </span>
    )
  }

  if (typeof data === 'number') {
    if (data >= 0 && data <= 1) {
      const percent = Math.round(data * 100)
      return (
        <span className="inline-flex items-center gap-2">
          <span className="font-mono">{data.toFixed(2)}</span>
          <span className="text-xs text-gray-500">({percent}%)</span>
        </span>
      )
    }
    return <span className="font-mono text-blue-600">{data}</span>
  }

  if (typeof data === 'string') {
    if (data.length > 200) {
      return <span className="text-gray-700">{data.slice(0, 200)}...</span>
    }
    return <span className="text-gray-700">{data}</span>
  }

  if (Array.isArray(data)) {
    if (data.length === 0) {
      return <span className="text-gray-400 italic">empty array</span>
    }
    return (
      <div className="space-y-1">
        {data.map((item, idx) => (
          <div key={idx} className="flex gap-2">
            <span className="text-gray-400 text-xs">{idx}.</span>
            <KeyValueDisplay data={item} depth={depth + 1} />
          </div>
        ))}
      </div>
    )
  }

  if (typeof data === 'object') {
    const entries = Object.entries(data)
    if (entries.length === 0) {
      return <span className="text-gray-400 italic">empty object</span>
    }
    return (
      <div className={`space-y-2 ${depth > 0 ? 'pl-3 border-l border-gray-200' : ''}`}>
        {entries.map(([key, value]) => (
          <div key={key} className="text-sm">
            <span className="font-medium text-gray-600">{formatKey(key)}:</span>{' '}
            {isSimpleValue(value) ? (
              <KeyValueDisplay data={value} depth={depth + 1} />
            ) : (
              <div className="mt-1">
                <KeyValueDisplay data={value} depth={depth + 1} />
              </div>
            )}
          </div>
        ))}
      </div>
    )
  }

  return <span>{String(data)}</span>
}
