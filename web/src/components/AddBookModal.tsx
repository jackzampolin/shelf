import { useState, useRef, useCallback } from 'react'
import { useNavigate } from '@tanstack/react-router'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Dialog, DialogPanel, DialogTitle } from '@headlessui/react'

interface AddBookModalProps {
  isOpen: boolean
  onClose: () => void
}

interface IngestResponse {
  job_id: string
  book_id: string
  title: string
  author?: string
  status: string
  process_job_id?: string
}

export function AddBookModal({ isOpen, onClose }: AddBookModalProps) {
  const [isDragging, setIsDragging] = useState(false)
  const [selectedFiles, setSelectedFiles] = useState<File[]>([])
  const fileInputRef = useRef<HTMLInputElement>(null)
  const navigate = useNavigate()
  const queryClient = useQueryClient()

  const uploadMutation = useMutation({
    mutationFn: async (files: File[]) => {
      const formData = new FormData()
      for (const file of files) {
        formData.append('files', file)
      }
      formData.append('auto_process', 'true')

      const response = await fetch('/api/books/ingest/upload', {
        method: 'POST',
        body: formData,
      })

      if (!response.ok) {
        const err = await response.json().catch(() => ({ error: 'Upload failed' }))
        throw new Error(err.error || 'Upload failed')
      }

      return response.json() as Promise<IngestResponse>
    },
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['books'] })
      setSelectedFiles([])
      onClose()

      // Navigate to the book page
      if (data.book_id) {
        navigate({ to: '/books/$bookId', params: { bookId: data.book_id } })
      }
    },
  })

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    setIsDragging(true)
  }, [])

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    setIsDragging(false)
  }, [])

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    setIsDragging(false)

    const files = Array.from(e.dataTransfer.files).filter(
      (f) => f.type === 'application/pdf' || f.name.toLowerCase().endsWith('.pdf')
    )

    if (files.length > 0) {
      setSelectedFiles(files)
    }
  }, [])

  const handleFileSelect = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files ? Array.from(e.target.files) : []
    if (files.length > 0) {
      setSelectedFiles(files)
    }
  }, [])

  const handleSubmit = () => {
    if (selectedFiles.length > 0) {
      uploadMutation.mutate(selectedFiles)
    }
  }

  const handleClose = () => {
    if (!uploadMutation.isPending) {
      setSelectedFiles([])
      onClose()
    }
  }

  return (
    <Dialog open={isOpen} onClose={handleClose} className="relative z-50">
      <div className="fixed inset-0 bg-black/30" aria-hidden="true" />

      <div className="fixed inset-0 flex items-center justify-center p-4">
        <DialogPanel className="w-full max-w-lg bg-white rounded-lg shadow-xl">
          <div className="p-6">
            <DialogTitle className="text-lg font-semibold text-gray-900 mb-4">
              Add Book
            </DialogTitle>

            {/* Drop zone */}
            <div
              onDragOver={handleDragOver}
              onDragLeave={handleDragLeave}
              onDrop={handleDrop}
              onClick={() => fileInputRef.current?.click()}
              className={`
                border-2 border-dashed rounded-lg p-8 text-center cursor-pointer
                transition-colors duration-200
                ${isDragging
                  ? 'border-blue-500 bg-blue-50'
                  : selectedFiles.length > 0
                    ? 'border-green-500 bg-green-50'
                    : 'border-gray-300 hover:border-gray-400 hover:bg-gray-50'
                }
              `}
            >
              <input
                ref={fileInputRef}
                type="file"
                accept=".pdf,application/pdf"
                multiple
                onChange={handleFileSelect}
                className="hidden"
              />

              {selectedFiles.length > 0 ? (
                <div>
                  <div className="text-green-600 mb-2">
                    <svg className="w-12 h-12 mx-auto" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
                    </svg>
                  </div>
                  <p className="text-sm font-medium text-gray-900">
                    {selectedFiles.length} file{selectedFiles.length > 1 ? 's' : ''} selected
                  </p>
                  <ul className="mt-2 text-sm text-gray-600">
                    {selectedFiles.map((f, i) => (
                      <li key={i} className="truncate">{f.name}</li>
                    ))}
                  </ul>
                  <p className="mt-2 text-xs text-gray-500">Click to change</p>
                </div>
              ) : (
                <div>
                  <div className="text-gray-400 mb-2">
                    <svg className="w-12 h-12 mx-auto" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12" />
                    </svg>
                  </div>
                  <p className="text-sm font-medium text-gray-900">
                    Drop PDF files here or click to browse
                  </p>
                  <p className="mt-1 text-xs text-gray-500">
                    Multi-part scans are sorted by numeric suffix
                  </p>
                </div>
              )}
            </div>

            {uploadMutation.isError && (
              <div className="mt-4 p-3 bg-red-50 border border-red-200 rounded-md">
                <p className="text-sm text-red-600">
                  {uploadMutation.error?.message || 'Upload failed'}
                </p>
              </div>
            )}

            {/* Actions */}
            <div className="mt-6 flex justify-end space-x-3">
              <button
                type="button"
                onClick={handleClose}
                disabled={uploadMutation.isPending}
                className="px-4 py-2 text-sm font-medium text-gray-700 bg-white border border-gray-300 rounded-md hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500 disabled:opacity-50"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={handleSubmit}
                disabled={selectedFiles.length === 0 || uploadMutation.isPending}
                className="px-4 py-2 text-sm font-medium text-white bg-blue-600 border border-transparent rounded-md hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500 disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {uploadMutation.isPending ? (
                  <span className="flex items-center">
                    <svg className="animate-spin -ml-1 mr-2 h-4 w-4 text-white" fill="none" viewBox="0 0 24 24">
                      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
                    </svg>
                    Processing...
                  </span>
                ) : (
                  'Add & Process'
                )}
              </button>
            </div>
          </div>
        </DialogPanel>
      </div>
    </Dialog>
  )
}
