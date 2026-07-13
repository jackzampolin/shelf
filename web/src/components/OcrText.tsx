import type { ReactNode } from 'react'

type OcrTextProps = {
  text?: string | null
  emptyText?: string
  className?: string
}

const imagePattern = /!\[([^\]]*)\]\(([^)\s]+)\)/g

function renderLine(line: string, lineIndex: number): ReactNode[] {
  const nodes: ReactNode[] = []
  let lastIndex = 0
  imagePattern.lastIndex = 0

  for (const match of line.matchAll(imagePattern)) {
    const [token, alt, src] = match
    const index = match.index ?? 0

    if (index > lastIndex) {
      nodes.push(
        <span key={`${lineIndex}-text-${lastIndex}`}>
          {line.slice(lastIndex, index)}
        </span>
      )
    }

    nodes.push(
      <img
        key={`${lineIndex}-img-${index}`}
        src={src}
        alt={alt}
        loading="lazy"
        className="my-2 max-h-80 max-w-full rounded border border-gray-200 bg-white object-contain"
      />
    )

    lastIndex = index + token.length
  }

  if (lastIndex < line.length) {
    nodes.push(
      <span key={`${lineIndex}-text-tail`}>
        {line.slice(lastIndex)}
      </span>
    )
  }

  return nodes
}

export function OcrText({ text, emptyText = 'No text available', className = '' }: OcrTextProps) {
  const value = text || emptyText

  return (
    <div className={`font-mono text-sm leading-relaxed text-gray-800 ${className}`}>
      {value.split('\n').map((line, index) => (
        <div key={index} className={line.trim() === '' ? 'h-4' : 'min-h-5'}>
          {renderLine(line, index)}
        </div>
      ))}
    </div>
  )
}
