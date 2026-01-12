export function RoleBadge({ role }: { role: string }) {
  const styles: Record<string, string> = {
    system: 'bg-purple-100 text-purple-700',
    user: 'bg-blue-100 text-blue-700',
    assistant: 'bg-green-100 text-green-700',
    tool: 'bg-orange-100 text-orange-700',
  }

  return (
    <span className={`px-2 py-0.5 rounded text-xs font-medium ${styles[role] || 'bg-gray-100 text-gray-700'}`}>
      {role}
    </span>
  )
}
