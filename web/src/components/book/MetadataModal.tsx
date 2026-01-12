import { Modal, MetadataRow } from '@/components/ui'

interface BookMetadata {
  title?: string
  author?: string
  authors?: string[]
  isbn?: string
  lccn?: string
  publisher?: string
  publication_year?: number
  language?: string
  description?: string
  subjects?: string[]
}

interface MetadataModalProps {
  data: BookMetadata
  onClose: () => void
}

export function MetadataModal({ data, onClose }: MetadataModalProps) {
  return (
    <Modal title="Book Metadata" onClose={onClose}>
      <div className="space-y-4">
        <MetadataRow label="Title" value={data.title} />
        <MetadataRow label="Author" value={data.author} />
        {data.authors && data.authors.length > 0 && (
          <MetadataRow label="Authors" value={data.authors.join(', ')} />
        )}
        <MetadataRow label="ISBN" value={data.isbn} />
        <MetadataRow label="LCCN" value={data.lccn} />
        <MetadataRow label="Publisher" value={data.publisher} />
        <MetadataRow
          label="Publication Year"
          value={data.publication_year?.toString()}
        />
        <MetadataRow label="Language" value={data.language} />
        {data.description && (
          <div>
            <dt className="text-sm font-medium text-gray-500">Description</dt>
            <dd className="mt-1 text-sm text-gray-900 whitespace-pre-wrap">
              {data.description}
            </dd>
          </div>
        )}
        {data.subjects && data.subjects.length > 0 && (
          <div>
            <dt className="text-sm font-medium text-gray-500">Subjects</dt>
            <dd className="mt-1 flex flex-wrap gap-1">
              {data.subjects.map((subject, idx) => (
                <span
                  key={idx}
                  className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-gray-100 text-gray-800"
                >
                  {subject}
                </span>
              ))}
            </dd>
          </div>
        )}
      </div>
    </Modal>
  )
}
