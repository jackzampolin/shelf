import { createFileRoute, redirect } from '@tanstack/react-router'

export const Route = createFileRoute('/books/$bookId/pages/')({
  beforeLoad: ({ params }) => {
    // Redirect /books/{id}/pages to /books/{id}/pages/1
    throw redirect({
      to: '/books/$bookId/pages/$pageNum',
      params: { bookId: params.bookId, pageNum: '1' },
    })
  },
  component: () => null, // Never rendered due to redirect
})
