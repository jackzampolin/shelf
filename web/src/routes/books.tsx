import { createFileRoute, Link } from '@tanstack/react-router'
import { useQuery } from '@tanstack/react-query'
import { client, unwrap } from '@/api/client'

export const Route = createFileRoute('/books')({
  component: BooksPage,
})

function BooksPage() {
  const { data, isLoading, error } = useQuery({
    queryKey: ['books'],
    queryFn: async () => unwrap(await client.GET('/api/books')),
  })

  if (isLoading) {
    return (
      <div className="text-center py-12">
        <div className="text-gray-500">Loading books...</div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="text-center py-12">
        <div className="text-red-500">Error loading books: {error.message}</div>
      </div>
    )
  }

  const books = data?.books || []

  return (
    <div className="space-y-6">
      <div className="flex justify-between items-center">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Library</h1>
          <p className="text-gray-500">{books.length} books</p>
        </div>
      </div>

      {books.length === 0 ? (
        <div className="bg-white rounded-lg shadow p-12 text-center">
          <p className="text-gray-500">No books in your library yet.</p>
          <p className="text-sm text-gray-400 mt-2">
            Use the CLI to ingest PDF scans: <code className="bg-gray-100 px-2 py-1 rounded">shelf api ingest &lt;pdf-files...&gt;</code>
          </p>
        </div>
      ) : (
        <div className="bg-white rounded-lg shadow overflow-hidden">
          <table className="min-w-full divide-y divide-gray-200">
            <thead className="bg-gray-50">
              <tr>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                  Title
                </th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                  Author
                </th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                  Pages
                </th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                  Status
                </th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                  Actions
                </th>
              </tr>
            </thead>
            <tbody className="bg-white divide-y divide-gray-200">
              {books.map((book) => {
                const bookId = book.id ?? ''
                return (
                  <tr key={bookId} className="hover:bg-gray-50">
                    <td className="px-6 py-4 whitespace-nowrap">
                      <Link
                        to="/books/$bookId"
                        params={{ bookId }}
                        className="text-blue-600 hover:text-blue-800 font-medium"
                      >
                        {book.title}
                      </Link>
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                      {book.author || '-'}
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                      {book.page_count}
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap">
                      <span
                        className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${
                          book.status === 'complete'
                            ? 'bg-green-100 text-green-800'
                            : book.status === 'processing'
                            ? 'bg-blue-100 text-blue-800'
                            : 'bg-gray-100 text-gray-800'
                        }`}
                      >
                        {book.status}
                      </span>
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap text-sm">
                      <Link
                        to="/books/$bookId"
                        params={{ bookId }}
                        className="text-blue-600 hover:text-blue-800"
                      >
                        View
                      </Link>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
