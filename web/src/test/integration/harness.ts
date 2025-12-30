import { spawn, ChildProcess } from 'child_process'
import { createServer } from 'net'
import path from 'path'
import { fileURLToPath } from 'url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const PROJECT_ROOT = path.resolve(__dirname, '../../../../')

export interface TestServer {
  url: string
  port: number
  process: ChildProcess
  stop: () => Promise<void>
}

/**
 * Find an available port by briefly binding to port 0
 */
async function findFreePort(): Promise<number> {
  return new Promise((resolve, reject) => {
    const server = createServer()
    server.listen(0, '127.0.0.1', () => {
      const addr = server.address()
      if (addr && typeof addr === 'object') {
        const port = addr.port
        server.close(() => resolve(port))
      } else {
        reject(new Error('Could not get port'))
      }
    })
    server.on('error', reject)
  })
}

/**
 * Wait for the server to be ready by polling the health endpoint
 */
async function waitForServer(url: string, maxAttempts = 60, delayMs = 1000): Promise<void> {
  for (let attempt = 1; attempt <= maxAttempts; attempt++) {
    try {
      const response = await fetch(`${url}/health`)
      if (response.ok) {
        const data = await response.json()
        if (data.status === 'ok') {
          return
        }
      }
    } catch {
      // Server not ready yet
    }

    if (attempt < maxAttempts) {
      await new Promise((resolve) => setTimeout(resolve, delayMs))
    }
  }

  throw new Error(`Server at ${url} not ready after ${maxAttempts} attempts`)
}

/**
 * Wait for DefraDB to be ready
 */
async function waitForDefra(url: string, maxAttempts = 60, delayMs = 1000): Promise<void> {
  for (let attempt = 1; attempt <= maxAttempts; attempt++) {
    try {
      const response = await fetch(`${url}/ready`)
      if (response.ok) {
        const data = await response.json()
        if (data.status === 'ok' && data.defra === 'ok') {
          return
        }
      }
    } catch {
      // Not ready yet
    }

    if (attempt < maxAttempts) {
      await new Promise((resolve) => setTimeout(resolve, delayMs))
    }
  }

  throw new Error(`DefraDB not ready after ${maxAttempts} attempts`)
}

/**
 * Build the shelf binary if it doesn't exist or is outdated
 */
async function ensureBinaryBuilt(): Promise<string> {
  const binaryPath = path.join(PROJECT_ROOT, 'build', 'shelf')

  return new Promise((resolve, reject) => {
    console.log('Building shelf binary...')
    const build = spawn('make', ['build'], {
      cwd: PROJECT_ROOT,
      stdio: ['ignore', 'pipe', 'pipe'],
    })

    let stderr = ''
    build.stderr?.on('data', (data) => {
      stderr += data.toString()
    })

    build.on('close', (code) => {
      if (code === 0) {
        console.log('Build complete')
        resolve(binaryPath)
      } else {
        reject(new Error(`Build failed with code ${code}: ${stderr}`))
      }
    })

    build.on('error', reject)
  })
}

/**
 * Start a test server instance
 */
export async function startTestServer(): Promise<TestServer> {
  const port = await findFreePort()
  const defraPort = await findFreePort()
  const url = `http://127.0.0.1:${port}`

  // Ensure binary is built
  const binaryPath = await ensureBinaryBuilt()

  console.log(`Starting test server on port ${port}, DefraDB on port ${defraPort}...`)

  // Create a unique home directory for this test run to isolate DefraDB data
  const testHome = path.join(PROJECT_ROOT, '.test-home', `test-${port}`)
  const shelfHome = path.join(testHome, '.shelf')

  // Create config with unique container name and port to avoid conflicts
  const { mkdirSync, writeFileSync } = await import('fs')
  mkdirSync(shelfHome, { recursive: true })

  const containerName = `shelf-defra-test-${port}`
  const configContent = `
# Auto-generated test config
defra:
  container_name: "${containerName}"
  port: "${defraPort}"

defaults:
  ocr_providers:
    - mistral
    - paddle
  llm_provider: openrouter
`
  writeFileSync(path.join(shelfHome, 'config.yaml'), configContent)
  console.log(`Created test config with container: ${containerName}, defra port: ${defraPort}`)

  const serverProcess = spawn(binaryPath, ['serve', '--port', port.toString(), '--host', '127.0.0.1', '--home', shelfHome], {
    cwd: PROJECT_ROOT,
    env: {
      ...process.env,
      HOME: testHome,
      SHELF_HOME: testHome,
    },
    stdio: ['ignore', 'pipe', 'pipe'],
  })

  // Capture server output for debugging
  let serverOutput = ''
  let serverErrors = ''

  serverProcess.stdout?.on('data', (data) => {
    const output = data.toString()
    serverOutput += output
    console.log(`[server:stdout] ${output.trim()}`)
  })

  serverProcess.stderr?.on('data', (data) => {
    const output = data.toString()
    serverErrors += output
    console.log(`[server:stderr] ${output.trim()}`)
  })

  // Handle unexpected exit
  let stopped = false
  serverProcess.on('exit', (code) => {
    if (!stopped) {
      console.error(`Server exited unexpectedly with code ${code}`)
    }
  })

  // Create stop function
  const stop = async (): Promise<void> => {
    stopped = true

    if (serverProcess.pid) {
      console.log('Stopping test server...')

      // Send SIGTERM for graceful shutdown
      serverProcess.kill('SIGTERM')

      // Wait for process to exit (with timeout)
      await Promise.race([
        new Promise<void>((resolve) => {
          serverProcess.on('exit', () => resolve())
        }),
        new Promise<void>((resolve) => {
          setTimeout(() => {
            // Force kill if still running
            if (!serverProcess.killed) {
              serverProcess.kill('SIGKILL')
            }
            resolve()
          }, 10000)
        }),
      ])

      console.log('Test server stopped')

      // Clean up the test container
      console.log(`Cleaning up container: ${containerName}`)
      try {
        const cleanup = spawn('docker', ['rm', '-f', containerName], {
          stdio: 'pipe',
        })
        await new Promise<void>((resolve) => {
          cleanup.on('close', () => resolve())
        })
        console.log('Container cleaned up')
      } catch {
        console.log('Container cleanup skipped (may not exist)')
      }
    }
  }

  try {
    // Wait for server to be ready
    console.log('Waiting for server to start...')
    await waitForServer(url, 60, 1000)
    console.log('Server is up')

    // Wait for DefraDB to be ready
    console.log('Waiting for DefraDB...')
    await waitForDefra(url, 60, 1000)
    console.log('DefraDB is ready')

    return {
      url,
      port,
      process: serverProcess,
      stop,
    }
  } catch (error) {
    // Clean up on failure
    await stop()
    throw error
  }
}

/**
 * Global test server instance (set by globalSetup)
 */
let globalServer: TestServer | null = null

export function getTestServer(): TestServer {
  if (!globalServer) {
    throw new Error('Test server not started. Make sure globalSetup ran correctly.')
  }
  return globalServer
}

export function setTestServer(server: TestServer | null): void {
  globalServer = server
}
