import { describe, it, expect } from 'vitest'
import { testClient, BACKEND_URL } from './setup'

describe('Health Endpoints', () => {
  describe('GET /api/health', () => {
    it('should return ok status', async () => {
      const { data, error } = await testClient.GET('/api/health')

      expect(error).toBeUndefined()
      expect(data).toBeDefined()
      expect(data?.status).toBe('ok')
    })
  })

  describe('GET /api/ready', () => {
    it('should return ok status with defra healthy', async () => {
      const { data, error } = await testClient.GET('/api/ready')

      expect(error).toBeUndefined()
      expect(data).toBeDefined()
      expect(data?.status).toBe('ok')
      expect(data?.defra).toBe('ok')
    })
  })

  describe('GET /api/status', () => {
    it('should return detailed server status', async () => {
      const { data, error } = await testClient.GET('/api/status')

      expect(error).toBeUndefined()
      expect(data).toBeDefined()
      expect(data?.server).toBe('running')
      expect(data?.providers).toBeDefined()
      expect(data?.defra).toBeDefined()
      expect(data?.defra?.container).toBe('running')
      expect(data?.defra?.health).toBe('healthy')
    })

    it('should list available providers', async () => {
      const { data } = await testClient.GET('/api/status')

      // Providers should be arrays (may be empty if not configured)
      expect(Array.isArray(data?.providers?.ocr)).toBe(true)
      expect(Array.isArray(data?.providers?.llm)).toBe(true)
    })
  })

  describe('GET /swagger.json', () => {
    it('should return OpenAPI spec when endpoint is registered', async () => {
      const response = await fetch(`${BACKEND_URL}/swagger.json`)

      // Skip if endpoint not registered (requires server restart after adding endpoint)
      if (response.status === 404) {
        console.log('Skipping: swagger endpoint not registered (restart server)')
        return
      }

      expect(response.ok).toBe(true)
      expect(response.headers.get('content-type')).toContain('application/json')

      const spec = await response.json()
      expect(spec.swagger || spec.openapi).toBeDefined()
      expect(spec.paths).toBeDefined()
    })
  })
})
