import { useState, useEffect } from 'react'
import { createFileRoute, Link, Outlet, useRouterState } from '@tanstack/react-router'
import { OverviewTab, ReadTab, TocTab, ProcessingTab, ListenTab, useBookData } from '@/components/book/tabs'

type TabId = 'overview' | 'read' | 'toc' | 'listen' | 'processing'

interface BookSearchParams {
  tab?: TabId
}

export const Route = createFileRoute('/books/$bookId')({
  component: BookDetailLayout,
  validateSearch: (search: Record<string, unknown>): BookSearchParams => {
    return {
      tab: (search.tab as TabId) || undefined,
    }
  },
})

function BookDetailLayout() {
  const routerState = useRouterState()
  const pathname = routerState.location.pathname
  const isChildRoute =
    pathname.includes('/pages') ||
    pathname.includes('/pages-table') ||
    pathname.includes('/prompts') ||
    pathname.includes('/chapters')

  if (isChildRoute) {
    return <Outlet />
  }

  return <BookDetailPage />
}

const TABS: { id: TabId; label: string }[] = [
  { id: 'overview', label: 'Overview' },
  { id: 'read', label: 'Read' },
  { id: 'toc', label: 'Contents' },
  { id: 'listen', label: 'Listen' },
  { id: 'processing', label: 'Processing' },
]

function BookDetailPage() {
  const { bookId } = Route.useParams()
  const search = Route.useSearch()
  const [activeTab, setActiveTab] = useState<TabId>(search.tab || 'overview')

  // Sync tab with URL search param
  useEffect(() => {
    if (search.tab && search.tab !== activeTab) {
      setActiveTab(search.tab)
    }
  }, [search.tab, activeTab])

  const { data: book, isLoading, error } = useBookData(bookId)

  if (isLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="text-center">
          <div className="animate-spin h-8 w-8 border-4 border-blue-500 border-t-transparent rounded-full mx-auto mb-4" />
          <div className="text-gray-500">Loading book...</div>
        </div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="text-center">
          <div className="text-red-500 text-5xl mb-4">!</div>
          <div className="text-red-600 font-medium">Error loading book</div>
          <div className="text-gray-500 text-sm mt-1">{error.message}</div>
          <Link to="/books" className="mt-4 inline-block text-blue-600 hover:text-blue-800">
            Back to Library
          </Link>
        </div>
      </div>
    )
  }

  if (!book) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="text-center">
          <div className="text-gray-400 text-5xl mb-4">?</div>
          <div className="text-gray-600 font-medium">Book not found</div>
          <Link to="/books" className="mt-4 inline-block text-blue-600 hover:text-blue-800">
            Back to Library
          </Link>
        </div>
      </div>
    )
  }

  const handleTabChange = (tabId: TabId) => {
    setActiveTab(tabId)
    // Update URL without full navigation
    const url = new URL(window.location.href)
    url.searchParams.set('tab', tabId)
    window.history.replaceState(null, '', url.toString())
  }

  return (
    <div className="min-h-screen bg-gray-50">
      {/* Header */}
      <header className="bg-white border-b sticky top-0 z-10">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          {/* Breadcrumb */}
          <nav className="py-3 text-sm">
            <Link to="/books" className="text-blue-600 hover:text-blue-800">
              Library
            </Link>
            <span className="mx-2 text-gray-400">/</span>
            <span className="text-gray-600 truncate">{book.title}</span>
          </nav>

          {/* Title Row */}
          <div className="pb-4">
            <div className="flex items-start justify-between">
              <div className="min-w-0 flex-1">
                <h1 className="text-2xl font-bold text-gray-900 truncate">{book.title}</h1>
                {book.author && <p className="text-gray-500 mt-1">{book.author}</p>}
              </div>
              <div className="ml-4 flex items-center space-x-2">
                <span
                  className={`inline-flex items-center px-3 py-1 rounded-full text-sm font-medium ${
                    book.status === 'complete'
                      ? 'bg-green-100 text-green-800'
                      : book.status === 'processing'
                        ? 'bg-blue-100 text-blue-800'
                        : book.status === 'error'
                          ? 'bg-red-100 text-red-800'
                          : 'bg-gray-100 text-gray-800'
                  }`}
                >
                  {book.status === 'processing' && (
                    <span className="animate-pulse mr-1.5 h-2 w-2 bg-blue-500 rounded-full" />
                  )}
                  {book.status || 'pending'}
                </span>
              </div>
            </div>
          </div>

          {/* Tabs */}
          <div className="flex space-x-1 -mb-px">
            {TABS.map((tab) => (
              <button
                key={tab.id}
                onClick={() => handleTabChange(tab.id)}
                className={`px-4 py-3 text-sm font-medium border-b-2 transition-colors ${
                  activeTab === tab.id
                    ? 'border-blue-500 text-blue-600'
                    : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
                }`}
              >
                {tab.label}
              </button>
            ))}
          </div>
        </div>
      </header>

      {/* Tab Content */}
      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6">
        {activeTab === 'overview' && <OverviewTab bookId={bookId} book={book} />}
        {activeTab === 'read' && <ReadTab bookId={bookId} book={book} />}
        {activeTab === 'toc' && <TocTab bookId={bookId} book={book} />}
        {activeTab === 'listen' && <ListenTab bookId={bookId} book={book} />}
        {activeTab === 'processing' && <ProcessingTab bookId={bookId} book={book} />}
      </main>
    </div>
  )
}
