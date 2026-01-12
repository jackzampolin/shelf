export function MetadataRow({ label, value }: { label: string; value?: string }) {
  if (!value) return null
  return (
    <div className="flex">
      <dt className="text-sm font-medium text-gray-500 w-32 flex-shrink-0">{label}</dt>
      <dd className="text-sm text-gray-900">{value}</dd>
    </div>
  )
}
