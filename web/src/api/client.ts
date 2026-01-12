import createClient from 'openapi-fetch'
import type { paths } from './types'

export const client = createClient<paths>({
  baseUrl: '',
})

/**
 * Unwrap API response, throwing on error.
 * Use this in queryFn to properly propagate API errors to React Query.
 */
export function unwrap<T>(result: { data?: T; error?: unknown }): T {
  if (result.error) {
    const message =
      typeof result.error === 'object' && result.error !== null && 'error' in result.error
        ? String((result.error as { error: unknown }).error)
        : 'API request failed'
    throw new Error(message)
  }
  return result.data as T
}
