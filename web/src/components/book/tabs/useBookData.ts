import { useQuery } from '@tanstack/react-query'
import { client, unwrap } from '@/api/client'
import type { StageMetrics } from '../types'

export interface BookData {
  id: string
  title?: string
  author?: string
  page_count?: number
  status?: string
}

export interface CostData {
  total_cost_usd?: number
  breakdown?: Record<string, number>
}

export interface DetailedMetrics {
  book_id: string
  stages: Record<string, StageMetrics>
}

export function useBookData(bookId: string) {
  return useQuery({
    queryKey: ['books', bookId],
    queryFn: async () =>
      unwrap(
        await client.GET('/api/books/{id}', {
          params: { path: { id: bookId } },
        })
      ) as BookData,
  })
}

export function useBookCost(bookId: string) {
  return useQuery({
    queryKey: ['books', bookId, 'cost'],
    queryFn: async () =>
      unwrap(
        await client.GET('/api/books/{id}/cost', {
          params: { path: { id: bookId }, query: { by: 'stage' } },
        })
      ) as CostData,
  })
}

export function useDetailedStatus(bookId: string) {
  return useQuery({
    queryKey: ['jobs', 'status', bookId, 'detailed'],
    queryFn: async () =>
      unwrap(
        await client.GET('/api/jobs/status/{book_id}/detailed', {
          params: { path: { book_id: bookId } },
        })
      ),
    refetchInterval: 5000,
  })
}

export function useDetailedMetrics(bookId: string) {
  return useQuery({
    queryKey: ['books', bookId, 'metrics', 'detailed'],
    queryFn: async () => {
      const resp = await fetch(`/api/books/${bookId}/metrics/detailed`)
      if (!resp.ok) throw new Error('Failed to fetch detailed metrics')
      return resp.json() as Promise<DetailedMetrics>
    },
    refetchInterval: 10000,
  })
}

export function useChapters(bookId: string, enabled = true) {
  return useQuery({
    queryKey: ['books', bookId, 'chapters'],
    queryFn: async () => {
      const res = await fetch(`/api/books/${bookId}/chapters`)
      if (!res.ok) throw new Error('Failed to fetch chapters')
      return res.json()
    },
    enabled,
  })
}

export function usePages(bookId: string) {
  return useQuery({
    queryKey: ['books', bookId, 'pages'],
    queryFn: async () =>
      unwrap(
        await client.GET('/api/books/{book_id}/pages', {
          params: { path: { book_id: bookId } },
        })
      ),
    refetchInterval: 10000,
  })
}
