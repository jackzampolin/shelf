import { describe, it, expect } from 'vitest'
import { testClient } from './setup'

describe('Metrics Endpoints', () => {
  describe('GET /api/metrics', () => {
    it('should return metrics list', async () => {
      const { data, error } = await testClient.GET('/api/metrics')

      expect(error).toBeUndefined()
      expect(data).toBeDefined()
      // Go returns null for nil slices, so we check for array OR null
      expect(data?.metrics === null || Array.isArray(data?.metrics)).toBe(true)
      expect(typeof data?.count).toBe('number')
    })
  })

  describe('GET /api/metrics/cost', () => {
    it('should return total cost', async () => {
      const { data, error } = await testClient.GET('/api/metrics/cost')

      expect(error).toBeUndefined()
      expect(data).toBeDefined()
      expect(typeof data?.total_cost_usd).toBe('number')
    })

    it('should support breakdown by provider', async () => {
      const { data, error } = await testClient.GET('/api/metrics/cost', {
        params: { query: { by: 'provider' } },
      })

      expect(error).toBeUndefined()
      expect(data).toBeDefined()
      expect(typeof data?.total_cost_usd).toBe('number')

      // breakdown should be present
      if (data?.breakdown) {
        expect(typeof data.breakdown).toBe('object')
      }
    })

    it('should support breakdown by model', async () => {
      const { data, error } = await testClient.GET('/api/metrics/cost', {
        params: { query: { by: 'model' } },
      })

      expect(error).toBeUndefined()
      expect(data).toBeDefined()
      expect(typeof data?.total_cost_usd).toBe('number')
    })

    it('should support breakdown by stage', async () => {
      const { data, error } = await testClient.GET('/api/metrics/cost', {
        params: { query: { by: 'stage' } },
      })

      expect(error).toBeUndefined()
      expect(data).toBeDefined()
      expect(typeof data?.total_cost_usd).toBe('number')
    })
  })

  describe('GET /api/metrics/summary', () => {
    it('should return metrics summary', async () => {
      const { data, error } = await testClient.GET('/api/metrics/summary')

      expect(error).toBeUndefined()
      expect(data).toBeDefined()

      // Check all expected summary fields
      expect(typeof data?.count).toBe('number')
      expect(typeof data?.total_cost_usd).toBe('number')
      expect(typeof data?.total_tokens).toBe('number')
      expect(typeof data?.total_time_seconds).toBe('number')
      expect(typeof data?.success_count).toBe('number')
      expect(typeof data?.error_count).toBe('number')
      expect(typeof data?.avg_cost_usd).toBe('number')
      expect(typeof data?.avg_tokens).toBe('number')
      expect(typeof data?.avg_time_seconds).toBe('number')
    })

    it('should have consistent totals', async () => {
      const { data } = await testClient.GET('/api/metrics/summary')

      if (data) {
        // Success + error should equal total count
        expect(data.success_count + data.error_count).toBe(data.count)
      }
    })
  })
})
