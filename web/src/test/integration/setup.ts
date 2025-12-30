import { beforeAll } from 'vitest'
import createClient from 'openapi-fetch'
import { readFileSync, existsSync } from 'fs'
import path from 'path'
import { fileURLToPath } from 'url'
import type { paths } from '@/api/types'

const __dirname = path.dirname(fileURLToPath(import.meta.url))

// Read server config written by globalSetup
function getServerConfig(): { url: string; port: number } {
  const configPath = path.join(__dirname, '.test-server.json')

  if (existsSync(configPath)) {
    const config = JSON.parse(readFileSync(configPath, 'utf-8'))
    return config
  }

  // Fallback for running tests against external server
  const url = process.env.BACKEND_URL || 'http://localhost:8080'
  return { url, port: 8080 }
}

const serverConfig = getServerConfig()

// Export for use in tests
export const BACKEND_URL = serverConfig.url

// Create a test client that talks to the test server
export const testClient = createClient<paths>({
  baseUrl: BACKEND_URL,
})

// Per-file setup (runs once per test file)
beforeAll(async () => {
  console.log(`\nTest file using backend: ${BACKEND_URL}\n`)
})
