export type StatusType = 'pending' | 'in_progress' | 'complete' | 'failed'

export function StatusBadge({ status }: { status: StatusType }) {
  const styles = {
    pending: 'bg-gray-100 text-gray-600',
    in_progress: 'bg-blue-100 text-blue-700',
    complete: 'bg-green-100 text-green-700',
    failed: 'bg-red-100 text-red-700',
  }

  const labels = {
    pending: 'Pending',
    in_progress: 'In Progress',
    complete: 'Complete',
    failed: 'Failed',
  }

  return (
    <span className={`px-2 py-0.5 rounded text-xs font-medium ${styles[status]}`}>
      {labels[status]}
    </span>
  )
}
