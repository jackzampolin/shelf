import { createRootRoute, Link, Outlet } from '@tanstack/react-router'
import { TanStackRouterDevtools } from '@tanstack/router-devtools'

export const Route = createRootRoute({
  component: RootLayout,
})

function RootLayout() {
  return (
    <div className="min-h-screen bg-gray-50">
      {/* Header */}
      <header className="bg-white shadow-sm border-b">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex justify-between items-center h-16">
            <div className="flex items-center space-x-8">
              <Link to="/" className="text-xl font-bold text-gray-900">
                Shelf
              </Link>
              <nav className="flex space-x-4">
                <Link
                  to="/"
                  className="text-gray-600 hover:text-gray-900 px-3 py-2 text-sm font-medium [&.active]:text-blue-600 [&.active]:font-semibold"
                >
                  Dashboard
                </Link>
                <Link
                  to="/books"
                  className="text-gray-600 hover:text-gray-900 px-3 py-2 text-sm font-medium [&.active]:text-blue-600 [&.active]:font-semibold"
                >
                  Library
                </Link>
                <Link
                  to="/jobs"
                  className="text-gray-600 hover:text-gray-900 px-3 py-2 text-sm font-medium [&.active]:text-blue-600 [&.active]:font-semibold"
                >
                  Jobs
                </Link>
                <Link
                  to="/settings"
                  className="text-gray-600 hover:text-gray-900 px-3 py-2 text-sm font-medium [&.active]:text-blue-600 [&.active]:font-semibold"
                >
                  Settings
                </Link>
                <Link
                  to="/llmcalls"
                  className="text-gray-600 hover:text-gray-900 px-3 py-2 text-sm font-medium [&.active]:text-blue-600 [&.active]:font-semibold"
                >
                  LLM Calls
                </Link>
                <Link
                  to="/prompts"
                  className="text-gray-600 hover:text-gray-900 px-3 py-2 text-sm font-medium [&.active]:text-blue-600 [&.active]:font-semibold"
                >
                  Prompts
                </Link>
              </nav>
            </div>
            <div className="flex items-center space-x-4">
              <a
                href="/swagger"
                target="_blank"
                className="text-gray-500 hover:text-gray-700 text-sm"
              >
                API Docs
              </a>
            </div>
          </div>
        </div>
      </header>

      {/* Main content */}
      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        <Outlet />
      </main>

      {/* Dev tools */}
      <TanStackRouterDevtools />
    </div>
  )
}
