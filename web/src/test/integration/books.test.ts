import { describe, it, expect } from 'vitest'
import { testClient } from './setup'

describe('Books Endpoints', () => {
  describe('GET /api/books', () => {
    it('should return books list (may be empty)', async () => {
      const { data, error } = await testClient.GET('/api/books')

      expect(error).toBeUndefined()
      expect(data).toBeDefined()
      // Go returns null for nil slices, so we check for array OR null
      expect(data?.books === null || Array.isArray(data?.books)).toBe(true)
    })

    it('should return books with expected fields', async () => {
      const { data } = await testClient.GET('/api/books')

      if (data?.books && data.books.length > 0) {
        const book = data.books[0]
        expect(book.id).toBeDefined()
        expect(book.title).toBeDefined()
        expect(typeof book.page_count).toBe('number')
        expect(book.status).toBeDefined()
      }
    })
  })

  describe('GET /api/books/{id}', () => {
    it('should return 404 for non-existent book', async () => {
      const { error, response } = await testClient.GET('/api/books/{id}', {
        params: { path: { id: 'non-existent-book-id' } },
      })

      expect(response.status).toBe(404)
      expect(error).toBeDefined()
    })

    it('should return book details when book exists', async () => {
      // First get list of books
      const { data: listData } = await testClient.GET('/api/books')

      if (!listData?.books || listData.books.length === 0) {
        console.log('Skipping: no books in library')
        return
      }

      const bookId = listData.books[0].id ?? ''

      const { data, error } = await testClient.GET('/api/books/{id}', {
        params: { path: { id: bookId } },
      })

      expect(error).toBeUndefined()
      expect(data).toBeDefined()
      expect(data?.id).toBe(bookId)
      expect(data?.title).toBeDefined()
      expect(typeof data?.page_count).toBe('number')
    })
  })

  describe('GET /api/books/{id}/cost', () => {
    it('should handle non-existent book gracefully', async () => {
      const { data, response } = await testClient.GET('/api/books/{id}/cost', {
        params: { path: { id: 'non-existent-book-id' } },
      })

      // Endpoint may return 200 with zero cost or 404
      // This is valid behavior - cost of a non-existent book is 0
      if (response.ok) {
        expect(data?.total_cost_usd).toBe(0)
      } else {
        expect(response.status).toBeGreaterThanOrEqual(400)
      }
    })

    it('should return cost breakdown when book exists', async () => {
      // First get list of books
      const { data: listData } = await testClient.GET('/api/books')

      if (!listData?.books || listData.books.length === 0) {
        console.log('Skipping: no books in library')
        return
      }

      const bookId = listData.books[0].id ?? ''

      const { data, error } = await testClient.GET('/api/books/{id}/cost', {
        params: { path: { id: bookId } },
      })

      expect(error).toBeUndefined()
      expect(data).toBeDefined()
      expect(typeof data?.total_cost_usd).toBe('number')
    })

    it('should support by=stage parameter', async () => {
      const { data: listData } = await testClient.GET('/api/books')

      if (!listData?.books || listData.books.length === 0) {
        console.log('Skipping: no books in library')
        return
      }

      const bookId = listData.books[0].id ?? ''

      const { data, error } = await testClient.GET('/api/books/{id}/cost', {
        params: {
          path: { id: bookId },
          query: { by: 'stage' },
        },
      })

      expect(error).toBeUndefined()
      expect(data).toBeDefined()
      expect(typeof data?.total_cost_usd).toBe('number')
      // breakdown should be present when by=stage
      if (data?.breakdown) {
        expect(typeof data.breakdown).toBe('object')
      }
    })
  })

  describe('POST /api/books/ingest', () => {
    it('should return 400 for empty pdf_paths', async () => {
      const { error, response } = await testClient.POST('/api/books/ingest', {
        body: {
          pdf_paths: [],
        },
      })

      expect(response.status).toBe(400)
      expect(error).toBeDefined()
    })

    // Note: We don't test actual ingest here because:
    // 1. It requires real PDF files on the server filesystem
    // 2. It would trigger actual processing (LLM API calls)
    // These should be tested with proper fixtures in a controlled environment
  })
})
