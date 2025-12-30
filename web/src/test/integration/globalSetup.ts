import { startTestServer, TestServer } from './harness'
import { writeFileSync, mkdirSync } from 'fs'
import path from 'path'
import { fileURLToPath } from 'url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))

let server: TestServer | null = null

export async function setup(): Promise<void> {
  console.log('\n========================================')
  console.log('  Starting Integration Test Server')
  console.log('========================================\n')

  server = await startTestServer()

  // Write the server URL to a temp file so tests can read it
  // This is necessary because globalSetup runs in a separate process
  const configPath = path.join(__dirname, '.test-server.json')
  mkdirSync(path.dirname(configPath), { recursive: true })
  writeFileSync(configPath, JSON.stringify({ url: server.url, port: server.port }))

  console.log('\n========================================')
  console.log(`  Server ready at ${server.url}`)
  console.log('========================================\n')
}

export async function teardown(): Promise<void> {
  console.log('\n========================================')
  console.log('  Stopping Integration Test Server')
  console.log('========================================\n')

  if (server) {
    await server.stop()
    server = null
  }

  console.log('Teardown complete\n')
}
