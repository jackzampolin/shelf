import { useState, useMemo } from 'react'
import { createFileRoute, Link } from '@tanstack/react-router'
import { useQuery } from '@tanstack/react-query'
import { Disclosure, DisclosureButton, DisclosurePanel } from '@headlessui/react'

export const Route = createFileRoute('/books/$bookId/chapters')({
  component: ChaptersPage,
})

interface ChapterPage {
  page_num: number
  blended_text?: string
  label?: string
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
  pages?: ChapterPage[]
}

interface ChaptersResponse {
  book_id: string
  book_title?: string
  total_pages: number
  chapters: Chapter[]
  has_chapters: boolean
}

function ChaptersPage() {
  const { bookId } = Route.useParams()
  const [expandedChapter, setExpandedChapter] = useState<string | null>(null)
  const [loadingText, setLoadingText] = useState<string | null>(null)
  const [chapterTexts, setChapterTexts] = useState<Record<string, ChapterPage[]>>({})

  const { data: chaptersData, isLoading, error } = useQuery({
    queryKey: ['books', bookId, 'chapters'],
    queryFn: async (): Promise<ChaptersResponse> => {
      const res = await fetch(`/api/books/${bookId}/chapters`)
      if (!res.ok) throw new Error('Failed to fetch chapters')
      return res.json()
    },
  })

  const { data: book } = useQuery({
    queryKey: ['books', bookId],
    queryFn: async () => {
      const res = await fetch(`/api/books/${bookId}`)
      if (!res.ok) throw new Error('Failed to fetch book')
      return res.json()
    },
  })

  const loadChapterText = async (chapterId: string, hasPolishedText: boolean) => {
    // Toggle if already expanded
    if (expandedChapter === chapterId) {
      setExpandedChapter(null)
      return
    }

    // If chapter has polished text, just expand - no fetch needed
    if (hasPolishedText) {
      setExpandedChapter(chapterId)
      return
    }

    // If we already have page data cached, just expand
    if (chapterTexts[chapterId]) {
      setExpandedChapter(chapterId)
      return
    }

    // Fetch page data as fallback
    setLoadingText(chapterId)
    try {
      const res = await fetch(`/api/books/${bookId}/chapters?include_text=true`)
      if (!res.ok) throw new Error('Failed to fetch chapter text')
      const data: ChaptersResponse = await res.json()

      const textsMap: Record<string, ChapterPage[]> = {}
      for (const chapter of data.chapters) {
        if (chapter.pages) {
          textsMap[chapter.id] = chapter.pages
        }
      }
      setChapterTexts(textsMap)
      setExpandedChapter(chapterId)
    } catch (err) {
      console.error('Failed to load chapter text:', err)
    } finally {
      setLoadingText(null)
    }
  }

  // Sort chapters by sort_order for consistent display
  const sortedChapters = useMemo(() => {
    if (!chaptersData?.chapters) return []
    return [...chaptersData.chapters].sort((a, b) => a.sort_order - b.sort_order)
  }, [chaptersData?.chapters])

  if (isLoading) {
    return (
      <div className="text-center py-12">
        <div className="text-gray-500">Loading chapters...</div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="text-center py-12">
        <div className="text-red-500">Error loading chapters: {error.message}</div>
      </div>
    )
  }

  if (!chaptersData?.has_chapters) {
    return (
      <div className="space-y-6">
        <nav className="text-sm">
          <Link to="/books" className="text-blue-600 hover:text-blue-800">
            Library
          </Link>
          <span className="mx-2 text-gray-400">/</span>
          <Link
            to="/books/$bookId"
            params={{ bookId }}
            className="text-blue-600 hover:text-blue-800"
          >
            {book?.title || 'Book'}
          </Link>
          <span className="mx-2 text-gray-400">/</span>
          <span className="text-gray-600">Chapters</span>
        </nav>
        <div className="bg-white rounded-lg shadow p-12 text-center">
          <div className="text-gray-500 mb-4">No chapters found for this book.</div>
          <div className="text-sm text-gray-400">
            Chapters are generated after the ToC is extracted and linked.
          </div>
        </div>
      </div>
    )
  }

  const matterColors: Record<string, string> = {
    front_matter: 'bg-blue-100 text-blue-800',
    body: 'bg-green-100 text-green-800',
    back_matter: 'bg-purple-100 text-purple-800',
  }

  return (
    <div className="space-y-6">
      {/* Breadcrumb */}
      <nav className="text-sm">
        <Link to="/books" className="text-blue-600 hover:text-blue-800">
          Library
        </Link>
        <span className="mx-2 text-gray-400">/</span>
        <Link
          to="/books/$bookId"
          params={{ bookId }}
          className="text-blue-600 hover:text-blue-800"
        >
          {chaptersData.book_title || book?.title || 'Book'}
        </Link>
        <span className="mx-2 text-gray-400">/</span>
        <span className="text-gray-600">Chapters</span>
      </nav>

      {/* Header */}
      <div className="flex justify-between items-start">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Book Structure</h1>
          <p className="text-gray-500">
            {chaptersData.chapters.length} chapters across {chaptersData.total_pages} pages
          </p>
        </div>
        <Link
          to="/books/$bookId/pages/$pageNum"
          params={{ bookId, pageNum: '1' }}
          className="inline-flex items-center px-4 py-2 border border-gray-300 text-sm font-medium rounded-md text-gray-700 bg-white hover:bg-gray-50"
        >
          View Pages
        </Link>
      </div>

      {/* Chapters list */}
      <div className="bg-white rounded-lg shadow divide-y">
        {sortedChapters.map((chapter) => (
          <Disclosure key={chapter.id}>
            {() => (
              <div>
                <DisclosureButton
                  className="w-full px-6 py-4 flex items-center justify-between text-left hover:bg-gray-50"
                  onClick={(e) => {
                    e.preventDefault()
                    loadChapterText(chapter.id, !!chapter.polished_text)
                  }}
                >
                  <div className="flex items-center space-x-4 flex-1 min-w-0">
                    <span
                      className={`text-xs transition-transform ${
                        expandedChapter === chapter.id ? 'rotate-90' : ''
                      }`}
                    >
                      {loadingText === chapter.id ? (
                        <span className="animate-spin">...</span>
                      ) : (
                        '▶'
                      )}
                    </span>

                    <div className="flex-1 min-w-0">
                      <div className="flex items-center space-x-2">
                        {chapter.entry_number && (
                          <span className="text-gray-400 font-mono text-sm">
                            {chapter.entry_number}.
                          </span>
                        )}
                        <span className={`font-medium ${chapter.level === 1 ? 'text-lg' : ''}`}>
                          {chapter.title || `(${chapter.level_name || 'Untitled'})`}
                        </span>
                        {chapter.level_name && chapter.title && (
                          <span className="text-xs text-gray-400">
                            ({chapter.level_name})
                          </span>
                        )}
                      </div>
                      <div className="flex items-center space-x-3 mt-1 text-sm text-gray-500">
                        <span>Pages {chapter.start_page}–{chapter.end_page}</span>
                        <span>({chapter.page_count} pages)</span>
                        {chapter.word_count && chapter.word_count > 0 && (
                          <span>{chapter.word_count.toLocaleString()} words</span>
                        )}
                      </div>
                    </div>
                  </div>

                  <div className="flex items-center space-x-3">
                    <span
                      className={`px-2 py-1 rounded text-xs font-medium ${
                        matterColors[chapter.matter_type] || 'bg-gray-100 text-gray-600'
                      }`}
                    >
                      {chapter.matter_type?.replace('_', ' ') || 'unknown'}
                    </span>
                    <Link
                      to="/books/$bookId/pages/$pageNum"
                      params={{ bookId, pageNum: String(chapter.start_page) }}
                      onClick={(e) => e.stopPropagation()}
                      className="text-blue-600 hover:text-blue-800 text-sm"
                    >
                      View
                    </Link>
                  </div>
                </DisclosureButton>

                {expandedChapter === chapter.id && (
                  <DisclosurePanel static className="px-6 pb-4">
                    <div className="border-l-2 border-gray-200 pl-4 ml-4">
                      {/* Show polished text if available */}
                      {chapter.polished_text ? (
                        <div className="bg-gray-50 rounded p-4">
                          <div className="flex items-center justify-between mb-3">
                            <div className="flex items-center space-x-2">
                              <span className="text-sm font-medium text-gray-700">
                                Polished Text
                              </span>
                              {chapter.polish_complete && (
                                <span className="text-xs text-green-600">● Complete</span>
                              )}
                            </div>
                            <Link
                              to="/books/$bookId/pages/$pageNum"
                              params={{ bookId, pageNum: String(chapter.start_page) }}
                              className="text-blue-600 hover:text-blue-800 text-xs"
                            >
                              View pages {chapter.start_page}–{chapter.end_page}
                            </Link>
                          </div>
                          <div className="prose prose-sm max-w-none text-gray-700 leading-relaxed max-h-[32rem] overflow-y-auto">
                            {chapter.polished_text.split('\n\n').map((para, idx) => (
                              <p key={idx} className="mb-3">{para}</p>
                            ))}
                          </div>
                        </div>
                      ) : chapterTexts[chapter.id]?.length > 0 ? (
                        /* Fall back to page-by-page view if no polished text */
                        <div className="space-y-4">
                          <div className="text-xs text-amber-600 mb-2">
                            No polished text available - showing raw page content
                          </div>
                          {chapterTexts[chapter.id].map((page) => (
                            <div key={page.page_num} className="bg-gray-50 rounded p-4">
                              <div className="flex items-center justify-between mb-2">
                                <div className="flex items-center space-x-2">
                                  <span className="font-medium text-sm text-gray-700">
                                    Page {page.page_num}
                                  </span>
                                  {page.label && (
                                    <span className="text-xs text-gray-400">
                                      ({page.label})
                                    </span>
                                  )}
                                </div>
                                <Link
                                  to="/books/$bookId/pages/$pageNum"
                                  params={{ bookId, pageNum: String(page.page_num) }}
                                  className="text-blue-600 hover:text-blue-800 text-xs"
                                >
                                  View page
                                </Link>
                              </div>
                              <pre className="whitespace-pre-wrap font-mono text-xs text-gray-600 leading-relaxed max-h-96 overflow-y-auto">
                                {page.blended_text || 'No text available'}
                              </pre>
                            </div>
                          ))}
                        </div>
                      ) : (
                        <div className="text-sm text-gray-400 py-4">
                          {chapter.polish_failed ? (
                            <span className="text-red-500">Polish failed for this chapter.</span>
                          ) : !chapter.polish_complete ? (
                            <span>Chapter text not yet polished. Processing may still be in progress.</span>
                          ) : (
                            <span>No content available for this chapter.</span>
                          )}
                        </div>
                      )}
                    </div>
                  </DisclosurePanel>
                )}
              </div>
            )}
          </Disclosure>
        ))}
      </div>

      {/* Summary stats */}
      <div className="grid grid-cols-3 gap-4">
        <div className="bg-white rounded-lg shadow p-4">
          <div className="text-sm text-gray-500">Front Matter</div>
          <div className="text-2xl font-semibold">
            {chaptersData.chapters.filter((c) => c.matter_type === 'front_matter').length}
          </div>
        </div>
        <div className="bg-white rounded-lg shadow p-4">
          <div className="text-sm text-gray-500">Body</div>
          <div className="text-2xl font-semibold">
            {chaptersData.chapters.filter((c) => c.matter_type === 'body').length}
          </div>
        </div>
        <div className="bg-white rounded-lg shadow p-4">
          <div className="text-sm text-gray-500">Back Matter</div>
          <div className="text-2xl font-semibold">
            {chaptersData.chapters.filter((c) => c.matter_type === 'back_matter').length}
          </div>
        </div>
      </div>
    </div>
  )
}
