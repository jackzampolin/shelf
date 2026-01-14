import { useState, useMemo } from 'react'
import { Link } from '@tanstack/react-router'
import { useDetailedStatus, type BookData } from './useBookData'
import type { TocEntry } from '../types'

interface TocTabProps {
  bookId: string
  book: BookData
}

export function TocTab({ bookId, book: _book }: TocTabProps) {
  const { data: detailedStatus, isLoading } = useDetailedStatus(bookId)
  const [searchFilter, setSearchFilter] = useState('')
  const [showOnlyLinked, setShowOnlyLinked] = useState(false)
  const [showOnlyDiscovered, setShowOnlyDiscovered] = useState(false)

  const toc = detailedStatus?.toc
  const entries = toc?.entries || []

  // Filter entries
  const filteredEntries = useMemo(() => {
    let result = [...entries]

    if (searchFilter) {
      const lower = searchFilter.toLowerCase()
      result = result.filter(
        (e: TocEntry) =>
          e.title?.toLowerCase().includes(lower) ||
          e.entry_number?.toLowerCase().includes(lower) ||
          e.level_name?.toLowerCase().includes(lower)
      )
    }

    if (showOnlyLinked) {
      result = result.filter((e: TocEntry) => e.is_linked && e.actual_page_num)
    }

    if (showOnlyDiscovered) {
      result = result.filter((e: TocEntry) => e.source === 'discovered')
    }

    return result
  }, [entries, searchFilter, showOnlyLinked, showOnlyDiscovered])

  // Stats
  const linkedCount = entries.filter((e: TocEntry) => e.is_linked).length
  const discoveredCount = entries.filter((e: TocEntry) => e.source === 'discovered').length
  const totalCount = entries.length

  if (isLoading) {
    return (
      <div className="text-center py-12">
        <div className="text-gray-500">Loading table of contents...</div>
      </div>
    )
  }

  if (!toc?.found) {
    return (
      <div className="bg-white border rounded-lg p-12 text-center">
        <div className="text-gray-400 text-5xl mb-4">📑</div>
        <h3 className="text-lg font-medium text-gray-900 mb-2">Table of Contents Not Found</h3>
        <p className="text-gray-500 mb-4">
          The table of contents has not been extracted yet. This happens during the ToC processing stage.
        </p>
        <Link
          to="/books/$bookId/pages/$pageNum"
          params={{ bookId, pageNum: '1' }}
          className="inline-flex items-center px-4 py-2 border border-gray-300 text-sm font-medium rounded-md text-gray-700 bg-white hover:bg-gray-50"
        >
          Browse Pages
        </Link>
      </div>
    )
  }

  return (
    <div className="space-y-4">
      {/* ToC Header Info */}
      <div className="bg-white border rounded-lg p-4">
        <div className="flex items-center justify-between">
          <div>
            <h3 className="text-lg font-medium text-gray-900">Table of Contents</h3>
            <p className="text-sm text-gray-500">
              Found on pages {toc.start_page}–{toc.end_page}
            </p>
          </div>
          <Link
            to="/books/$bookId/pages/$pageNum"
            params={{ bookId, pageNum: String(toc.start_page) }}
            className="text-blue-600 hover:text-blue-800 text-sm"
          >
            View ToC Pages →
          </Link>
        </div>

        {/* Stats */}
        <div className="flex items-center space-x-6 mt-4 pt-4 border-t">
          <div className="text-center">
            <div className="text-2xl font-bold text-gray-900">{totalCount}</div>
            <div className="text-xs text-gray-500">Total Entries</div>
          </div>
          <div className="text-center">
            <div className="text-2xl font-bold text-green-600">{linkedCount}</div>
            <div className="text-xs text-gray-500">Linked</div>
          </div>
          {discoveredCount > 0 && (
            <div className="text-center">
              <div className="text-2xl font-bold text-blue-600">+{discoveredCount}</div>
              <div className="text-xs text-gray-500">Discovered</div>
            </div>
          )}
          <div className="flex-1" />
          <div className="text-sm text-gray-500">
            {totalCount > 0 ? Math.round((linkedCount / totalCount) * 100) : 0}% linked
          </div>
        </div>
      </div>

      {/* Filters */}
      <div className="bg-white border rounded-lg p-3">
        <div className="flex items-center space-x-4">
          <div className="flex-1">
            <input
              type="text"
              value={searchFilter}
              onChange={(e) => setSearchFilter(e.target.value)}
              placeholder="Search entries..."
              className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm"
            />
          </div>
          <label className="flex items-center space-x-2 text-sm">
            <input
              type="checkbox"
              checked={showOnlyLinked}
              onChange={(e) => setShowOnlyLinked(e.target.checked)}
              className="rounded border-gray-300 text-blue-600"
            />
            <span className="text-gray-600">Linked only</span>
          </label>
          {discoveredCount > 0 && (
            <label className="flex items-center space-x-2 text-sm">
              <input
                type="checkbox"
                checked={showOnlyDiscovered}
                onChange={(e) => setShowOnlyDiscovered(e.target.checked)}
                className="rounded border-gray-300 text-blue-600"
              />
              <span className="text-gray-600">Discovered only</span>
            </label>
          )}
        </div>
        <div className="mt-2 text-xs text-gray-500">
          Showing {filteredEntries.length} of {totalCount} entries
        </div>
      </div>

      {/* Entries Table */}
      <div className="bg-white border rounded-lg overflow-hidden">
        <div className="grid grid-cols-12 gap-2 bg-gray-50 px-4 py-3 text-xs font-medium text-gray-500 uppercase tracking-wider border-b">
          <div className="col-span-1">#</div>
          <div className="col-span-6">Title</div>
          <div className="col-span-2">Type</div>
          <div className="col-span-1 text-right">Print</div>
          <div className="col-span-2 text-right">Scan Page</div>
        </div>
        <div className="max-h-[32rem] overflow-y-auto divide-y">
          {filteredEntries.length === 0 ? (
            <div className="px-4 py-8 text-center text-gray-500">No entries match your filters</div>
          ) : (
            filteredEntries.map((entry: TocEntry, idx: number) => (
              <TocEntryRow key={idx} entry={entry} bookId={bookId} />
            ))
          )}
        </div>
      </div>
    </div>
  )
}

function TocEntryRow({ entry, bookId }: { entry: TocEntry; bookId: string }) {
  const level = entry.level || 0
  const isDiscovered = entry.source === 'discovered'
  const isLinked = entry.is_linked && entry.actual_page_num

  return (
    <div
      className={`grid grid-cols-12 gap-2 px-4 py-3 text-sm hover:bg-gray-50 ${
        isDiscovered ? 'bg-green-50/50' : ''
      }`}
    >
      <div className="col-span-1 font-mono text-xs text-gray-400">{entry.entry_number || '-'}</div>
      <div className="col-span-6 flex items-center">
        <div style={{ width: `${level * 16}px` }} className="flex-shrink-0" />
        <span className={level === 0 ? 'font-medium' : ''}>{entry.title || 'Untitled'}</span>
      </div>
      <div className="col-span-2">
        <div className="flex items-center space-x-1">
          {entry.level_name && <span className="text-xs text-gray-500">{entry.level_name}</span>}
          {isDiscovered && (
            <span className="text-xs bg-green-100 text-green-700 px-1.5 py-0.5 rounded">new</span>
          )}
        </div>
      </div>
      <div className="col-span-1 text-right font-mono text-gray-500">
        {entry.printed_page_number || '-'}
      </div>
      <div className="col-span-2 text-right">
        {isLinked ? (
          <Link
            to="/books/$bookId/pages/$pageNum"
            params={{ bookId, pageNum: String(entry.actual_page_num) }}
            className="font-mono text-blue-600 hover:text-blue-800"
          >
            p.{entry.actual_page_num}
          </Link>
        ) : (
          <span className="text-gray-300">—</span>
        )}
      </div>
    </div>
  )
}
