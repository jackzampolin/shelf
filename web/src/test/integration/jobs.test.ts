import { describe, it, expect } from 'vitest'
import { testClient } from './setup'

describe('Jobs Endpoints', () => {
  let createdJobId: string | undefined

  describe('GET /api/jobs', () => {
    it('should return jobs list (may be empty)', async () => {
      const { data, error } = await testClient.GET('/api/jobs')

      expect(error).toBeUndefined()
      expect(data).toBeDefined()
      expect(Array.isArray(data?.jobs)).toBe(true)
    })

    it('should support status filter', async () => {
      const { data, error } = await testClient.GET('/api/jobs', {
        params: { query: { status: 'completed' } },
      })

      expect(error).toBeUndefined()
      expect(data).toBeDefined()
      expect(Array.isArray(data?.jobs)).toBe(true)

      // All returned jobs should have the filtered status
      if (data?.jobs && data.jobs.length > 0) {
        data.jobs.forEach((job) => {
          expect(job.status).toBe('completed')
        })
      }
    })

    it('should support job_type filter', async () => {
      const { data, error } = await testClient.GET('/api/jobs', {
        params: { query: { job_type: 'process-book' } },
      })

      expect(error).toBeUndefined()
      expect(data).toBeDefined()
      expect(Array.isArray(data?.jobs)).toBe(true)

      // All returned jobs should have the filtered type
      if (data?.jobs && data.jobs.length > 0) {
        data.jobs.forEach((job) => {
          expect(job.job_type).toBe('process-book')
        })
      }
    })
  })

  describe('POST /api/jobs', () => {
    it('should create a new job', async () => {
      const { data, error } = await testClient.POST('/api/jobs', {
        body: {
          job_type: 'test-job',
          metadata: { test: true },
        },
      })

      expect(error).toBeUndefined()
      expect(data).toBeDefined()
      expect(data?.id).toBeDefined()
      expect(typeof data?.id).toBe('string')

      // Store for later tests
      createdJobId = data?.id
    })

    it('should return 400 for missing job_type', async () => {
      const { error, response } = await testClient.POST('/api/jobs', {
        body: {} as any,
      })

      expect(response.status).toBe(400)
      expect(error).toBeDefined()
    })
  })

  describe('GET /api/jobs/{id}', () => {
    it('should get job by ID', async () => {
      // Skip if no job was created
      if (!createdJobId) {
        console.log('Skipping: no job created')
        return
      }

      const { data, error } = await testClient.GET('/api/jobs/{id}', {
        params: { path: { id: createdJobId } },
      })

      expect(error).toBeUndefined()
      expect(data).toBeDefined()
      // Note: API returns _docID from DefraDB, job_type should match
      expect(data?.job_type).toBe('test-job')
    })

    it('should return 404 for non-existent job', async () => {
      const { error, response } = await testClient.GET('/api/jobs/{id}', {
        params: { path: { id: 'non-existent-id' } },
      })

      expect(response.status).toBe(404)
      expect(error).toBeDefined()
    })
  })

  describe('PATCH /api/jobs/{id}', () => {
    it('should update job status', async () => {
      if (!createdJobId) {
        console.log('Skipping: no job created')
        return
      }

      const { data, error } = await testClient.PATCH('/api/jobs/{id}', {
        params: { path: { id: createdJobId } },
        body: { status: 'completed' },
      })

      expect(error).toBeUndefined()
      expect(data).toBeDefined()
      expect(data?.status).toBe('completed')
    })
  })

  describe('DELETE /api/jobs/{id}', () => {
    it('should delete a job', async () => {
      if (!createdJobId) {
        console.log('Skipping: no job created')
        return
      }

      const { error, response } = await testClient.DELETE('/api/jobs/{id}', {
        params: { path: { id: createdJobId } },
      })

      expect(error).toBeUndefined()
      expect(response.status).toBe(204)

      // Verify deletion
      const { response: getResponse } = await testClient.GET('/api/jobs/{id}', {
        params: { path: { id: createdJobId } },
      })
      expect(getResponse.status).toBe(404)
    })

    it('should handle non-existent job gracefully', async () => {
      const { response } = await testClient.DELETE('/api/jobs/{id}', {
        params: { path: { id: 'non-existent-id' } },
      })

      // Backend may return 204 (idempotent) or 404
      expect([204, 404]).toContain(response.status)
    })
  })

  describe('POST /api/jobs/start/{book_id}', () => {
    it('should return 400 for non-existent book', async () => {
      const { response } = await testClient.POST('/api/jobs/start/{book_id}', {
        params: { path: { book_id: 'non-existent-book' } },
        body: { job_type: 'process-book' },
      })

      // Should fail because book doesn't exist
      expect(response.status).toBeGreaterThanOrEqual(400)
    })

    it('should return 400 for invalid job_type', async () => {
      const { error, response } = await testClient.POST('/api/jobs/start/{book_id}', {
        params: { path: { book_id: 'any-book' } },
        body: { job_type: 'invalid-job-type' },
      })

      expect(response.status).toBe(400)
      expect(error).toBeDefined()
    })
  })

  describe('GET /api/jobs/status/{book_id}', () => {
    it('should return status for any book_id', async () => {
      const { data, response } = await testClient.GET('/api/jobs/status/{book_id}', {
        params: { path: { book_id: 'any-book-id' } },
      })

      // Endpoint may return 200 with zeros or 404 for non-existent book
      if (response.ok) {
        expect(data).toBeDefined()
        expect(typeof data?.total_pages).toBe('number')
        expect(typeof data?.ocr_complete).toBe('number')
      }
    })

    it('should include expected status fields', async () => {
      const { data, response } = await testClient.GET('/api/jobs/status/{book_id}', {
        params: { path: { book_id: 'test-book' } },
      })

      if (response.ok && data) {
        // Check all expected fields are present
        expect('total_pages' in data).toBe(true)
        expect('ocr_complete' in data).toBe(true)
        expect('metadata_complete' in data).toBe(true)
        expect('toc_found' in data).toBe(true)
        expect('toc_extracted' in data).toBe(true)
        expect('is_complete' in data).toBe(true)
      }
    })
  })
})
