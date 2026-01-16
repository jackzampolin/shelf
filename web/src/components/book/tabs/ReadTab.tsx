import { useState, useMemo } from 'react'
import { Link } from '@tanstack/react-router'
import { useChapters, type BookData } from './useBookData'

interface ReadTabProps {
  bookId: string
  book: BookData
}

interface Chapter {
  id: string
  title: string
  level: number
  level_name?: string
  entry_number?: string
  start_page: number
  end_page: number
  matter_type: string
  sort_order: number
  word_count?: number
  page_count: number
  polish_complete?: boolean
  polish_failed?: boolean
  polished_text?: string
}

export function ReadTab({ bookId, book: _book }: ReadTabProps) {
  const { data: chaptersData, isLoading } = useChapters(bookId)
  const [expandedChapter, setExpandedChapter] = useState<string | null>(null)
  const [matterFilter, setMatterFilter] = useState<string>('all')

  const chapters = chaptersData?.chapters || []
  const hasChapters = chaptersData?.has_chapters

  // Sort chapters by sort_order
  const sortedChapters = useMemo(() => {
    let filtered = [...chapters]
    if (matterFilter !== 'all') {
      filtered = filtered.filter((c: Chapter) => c.matter_type === matterFilter)
    }
    return filtered.sort((a: Chapter, b: Chapter) => a.sort_order - b.sort_order)
  }, [chapters, matterFilter])

  // Group chapters by matter type for stats
  const matterCounts = useMemo(() => {
    return chapters.reduce(
      (acc: Record<string, number>, c: Chapter) => {
        const matter = c.matter_type || 'unknown'
        acc[matter] = (acc[matter] || 0) + 1
        return acc
      },
      {} as Record<string, number>
    )
  }, [chapters])

  if (isLoading) {
    return (
      <div className="text-center py-12">
        <div className="text-gray-500">Loading chapters...</div>
      </div>
    )
  }

  if (!hasChapters) {
    return (
      <div className="bg-white border rounded-lg p-12 text-center">
        <div className="text-gray-400 text-5xl mb-4">📖</div>
        <h3 className="text-lg font-medium text-gray-900 mb-2">No Chapters Available</h3>
        <p className="text-gray-500 mb-4">
          Chapters are generated after the table of contents is extracted and linked.
        </p>
        <Link
          to="/books/$bookId/pages/$pageNum"
          params={{ bookId, pageNum: '1' }}
          className="inline-flex items-center px-4 py-2 border border-gray-300 text-sm font-medium rounded-md text-gray-700 bg-white hover:bg-gray-50"
        >
          Browse Pages Instead
        </Link>
      </div>
    )
  }

  const matterColors: Record<string, string> = {
    front_matter: 'bg-purple-100 text-purple-800 border-purple-200',
    body: 'bg-blue-100 text-blue-800 border-blue-200',
    back_matter: 'bg-orange-100 text-orange-800 border-orange-200',
  }

  return (
    <div className="space-y-4">
      {/* Filter Bar */}
      <div className="flex items-center justify-between bg-white border rounded-lg p-3">
        <div className="flex items-center space-x-2">
          <span className="text-sm text-gray-500">Filter:</span>
          <button
            onClick={() => setMatterFilter('all')}
            className={`px-3 py-1 rounded-full text-sm font-medium transition-colors ${
              matterFilter === 'all'
                ? 'bg-gray-900 text-white'
                : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
            }`}
          >
            All ({chapters.length})
          </button>
          {matterCounts.front_matter > 0 && (
            <button
              onClick={() => setMatterFilter('front_matter')}
              className={`px-3 py-1 rounded-full text-sm font-medium transition-colors ${
                matterFilter === 'front_matter'
                  ? 'bg-purple-600 text-white'
                  : 'bg-purple-100 text-purple-700 hover:bg-purple-200'
              }`}
            >
              Front ({matterCounts.front_matter})
            </button>
          )}
          {matterCounts.body > 0 && (
            <button
              onClick={() => setMatterFilter('body')}
              className={`px-3 py-1 rounded-full text-sm font-medium transition-colors ${
                matterFilter === 'body'
                  ? 'bg-blue-600 text-white'
                  : 'bg-blue-100 text-blue-700 hover:bg-blue-200'
              }`}
            >
              Body ({matterCounts.body})
            </button>
          )}
          {matterCounts.back_matter > 0 && (
            <button
              onClick={() => setMatterFilter('back_matter')}
              className={`px-3 py-1 rounded-full text-sm font-medium transition-colors ${
                matterFilter === 'back_matter'
                  ? 'bg-orange-600 text-white'
                  : 'bg-orange-100 text-orange-700 hover:bg-orange-200'
              }`}
            >
              Back ({matterCounts.back_matter})
            </button>
          )}
        </div>
        <div className="text-sm text-gray-500">
          {sortedChapters.length} {sortedChapters.length === 1 ? 'chapter' : 'chapters'}
        </div>
      </div>

      {/* Chapters List */}
      <div className="bg-white border rounded-lg divide-y">
        {sortedChapters.map((chapter: Chapter) => (
          <ChapterCard
            key={chapter.id}
            chapter={chapter}
            bookId={bookId}
            isExpanded={expandedChapter === chapter.id}
            onToggle={() => setExpandedChapter(expandedChapter === chapter.id ? null : chapter.id)}
            matterColors={matterColors}
          />
        ))}
      </div>
    </div>
  )
}

interface ChapterCardProps {
  chapter: Chapter
  bookId: string
  isExpanded: boolean
  onToggle: () => void
  matterColors: Record<string, string>
}

function ChapterCard({ chapter, bookId, isExpanded, onToggle, matterColors }: ChapterCardProps) {
  const hasPolishedText = !!chapter.polished_text
  const indent = chapter.level * 16

  return (
    <div className="group">
      {/* Chapter Header */}
      <button
        onClick={onToggle}
        className="w-full px-4 py-4 flex items-start justify-between text-left hover:bg-gray-50 transition-colors"
      >
        <div className="flex items-start space-x-3 flex-1 min-w-0" style={{ paddingLeft: indent }}>
          {/* Expand indicator */}
          <span
            className={`text-gray-400 transition-transform mt-1 ${isExpanded ? 'rotate-90' : ''} ${
              hasPolishedText ? '' : 'opacity-30'
            }`}
          >
            ▶
          </span>

          <div className="flex-1 min-w-0">
            {/* Title row */}
            <div className="flex items-center space-x-2">
              {chapter.entry_number && (
                <span className="text-gray-400 font-mono text-sm">{chapter.entry_number}.</span>
              )}
              <span className={`font-medium ${chapter.level <= 1 ? 'text-lg' : ''}`}>
                {chapter.title || `(${chapter.level_name || 'Untitled'})`}
              </span>
              {chapter.level_name && chapter.title && (
                <span className="text-xs text-gray-400">({chapter.level_name})</span>
              )}
            </div>

            {/* Meta row */}
            <div className="flex items-center space-x-3 mt-1 text-sm text-gray-500">
              <span>
                Pages {chapter.start_page}–{chapter.end_page}
              </span>
              {chapter.word_count && chapter.word_count > 0 && (
                <span>{chapter.word_count.toLocaleString()} words</span>
              )}
              {!hasPolishedText && (
                <span className="text-amber-600 text-xs">(text not ready)</span>
              )}
            </div>
          </div>
        </div>

        {/* Right side: matter type badge and link */}
        <div className="flex items-center space-x-3 ml-4">
          <span
            className={`px-2 py-1 rounded text-xs font-medium border ${
              matterColors[chapter.matter_type] || 'bg-gray-100 text-gray-600 border-gray-200'
            }`}
          >
            {chapter.matter_type?.replace('_', ' ') || 'unknown'}
          </span>
          <Link
            to="/books/$bookId/pages/$pageNum"
            params={{ bookId, pageNum: String(chapter.start_page) }}
            onClick={(e) => e.stopPropagation()}
            className="text-blue-600 hover:text-blue-800 text-sm opacity-0 group-hover:opacity-100 transition-opacity"
          >
            View →
          </Link>
        </div>
      </button>

      {/* Expanded Content */}
      {isExpanded && (
        <div className="px-4 pb-4" style={{ paddingLeft: indent + 16 + 12 }}>
          <div className="bg-gray-50 rounded-lg p-4 border-l-4 border-gray-300">
            {hasPolishedText ? (
              <div className="prose prose-sm max-w-none text-gray-700 leading-relaxed max-h-[32rem] overflow-y-auto">
                {chapter.polished_text!.split('\n\n').map((para, idx) => (
                  <p key={idx} className="mb-3">
                    {para}
                  </p>
                ))}
              </div>
            ) : (
              <div className="text-gray-500 text-sm py-4 text-center">
                {chapter.polish_failed ? (
                  <span className="text-red-500">Failed to polish this chapter.</span>
                ) : (
                  <span>Chapter text is being processed...</span>
                )}
              </div>
            )}

            {/* Footer with link to full page view */}
            <div className="mt-4 pt-3 border-t flex justify-end">
              <Link
                to="/books/$bookId/pages/$pageNum"
                params={{ bookId, pageNum: String(chapter.start_page) }}
                className="text-blue-600 hover:text-blue-800 text-sm"
              >
                View pages {chapter.start_page}–{chapter.end_page} →
              </Link>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
