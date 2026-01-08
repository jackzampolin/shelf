import { Disclosure, DisclosureButton, DisclosurePanel } from '@headlessui/react'
import { Modal, StatusBadge, RoleBadge, KeyValueDisplay } from '@/components/ui'
import { formatJSON } from '@/lib/format'
import type { Message, ToolCall } from './types'

interface AgentLogDetail {
  agent_type?: string
  iterations?: number
  success?: boolean
  started_at?: string
  error?: string
  result?: unknown
  messages?: unknown
  tool_calls?: unknown
}

interface AgentLogModalProps {
  detail: AgentLogDetail | null
  onClose: () => void
}

export function AgentLogModal({ detail, onClose }: AgentLogModalProps) {
  return (
    <Modal
      title={`Agent Log: ${detail?.agent_type || 'Loading...'}`}
      onClose={onClose}
      wide
    >
      {detail ? (
        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-4 text-sm">
            <div>
              <span className="text-gray-500">Agent Type:</span>{' '}
              <span className="font-medium">{detail.agent_type}</span>
            </div>
            <div>
              <span className="text-gray-500">Iterations:</span>{' '}
              <span className="font-medium">{detail.iterations}</span>
            </div>
            <div>
              <span className="text-gray-500">Status:</span>{' '}
              <StatusBadge status={detail.success ? 'complete' : 'failed'} />
            </div>
            <div>
              <span className="text-gray-500">Started:</span>{' '}
              <span className="font-mono text-xs">
                {detail.started_at ? new Date(detail.started_at).toLocaleString() : '-'}
              </span>
            </div>
          </div>
          {detail.error && (
            <div className="bg-red-50 border border-red-200 rounded p-3">
              <div className="text-sm font-medium text-red-800">Error</div>
              <div className="text-sm text-red-700 mt-1">{detail.error}</div>
            </div>
          )}
          {detail.result !== undefined && detail.result !== null && (
            <div>
              <div className="text-sm font-medium text-gray-700 mb-2">Result</div>
              <div className="bg-gray-50 rounded p-3">
                <KeyValueDisplay data={detail.result} />
              </div>
            </div>
          )}
          <MessagesSection messages={detail.messages} />
          <ToolCallsSection toolCalls={detail.tool_calls} />
        </div>
      ) : (
        <div className="text-center py-4 text-gray-500">Loading...</div>
      )}
    </Modal>
  )
}

function MessagesSection({ messages }: { messages?: unknown }) {
  if (!messages || !Array.isArray(messages) || messages.length === 0) {
    return null
  }

  const firstItem = messages[0]
  if (typeof firstItem !== 'object' || firstItem === null) {
    return null
  }

  const typedMessages = messages as Message[]

  return (
    <div>
      <div className="text-sm font-medium text-gray-700 mb-2">
        Messages ({typedMessages.length})
      </div>
      <div className="space-y-2 max-h-80 overflow-y-auto">
        {typedMessages.map((msg, idx) => (
          <div key={idx} className="bg-gray-50 rounded p-3 text-sm">
            <div className="flex items-center gap-2 mb-1">
              <RoleBadge role={msg.role || 'unknown'} />
              {msg.tool_call_id && (
                <span className="text-xs text-gray-400 font-mono">
                  {msg.tool_call_id}
                </span>
              )}
            </div>
            <div className="text-gray-700 whitespace-pre-wrap text-xs">
              {msg.content || <span className="text-gray-400 italic">No content</span>}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

function ToolCallsSection({ toolCalls }: { toolCalls?: unknown }) {
  if (!toolCalls || !Array.isArray(toolCalls) || toolCalls.length === 0) {
    return null
  }

  const firstItem = toolCalls[0]
  if (typeof firstItem !== 'object' || firstItem === null) {
    return null
  }

  const typedCalls = toolCalls as ToolCall[]

  return (
    <div>
      <div className="text-sm font-medium text-gray-700 mb-2">
        Tool Calls ({typedCalls.length})
      </div>
      <div className="space-y-2 max-h-80 overflow-y-auto">
        {typedCalls.map((call, idx) => (
          <Disclosure key={idx}>
            {({ open }) => (
              <div className="border rounded">
                <DisclosureButton className="w-full flex items-center justify-between p-3 text-left bg-gray-50 hover:bg-gray-100">
                  <div className="flex items-center gap-2">
                    <span className={`text-xs transition-transform ${open ? 'rotate-90' : ''}`}>
                      ▶
                    </span>
                    <span className="font-mono text-sm text-blue-600">
                      {call.tool_name}
                    </span>
                    {call.iteration !== undefined && (
                      <span className="text-xs text-gray-400">
                        iter {call.iteration}
                      </span>
                    )}
                  </div>
                  <div className="flex items-center gap-2 text-xs text-gray-500">
                    {call.result_len !== undefined && (
                      <span>{call.result_len} chars</span>
                    )}
                    {call.error && (
                      <span className="text-red-500">error</span>
                    )}
                  </div>
                </DisclosureButton>
                <DisclosurePanel className="p-3 border-t bg-white">
                  {call.args_json && (
                    <div className="mb-2">
                      <div className="text-xs font-medium text-gray-500 mb-1">Arguments</div>
                      <pre className="text-xs bg-gray-50 p-2 rounded overflow-x-auto">
                        {formatJSON(call.args_json)}
                      </pre>
                    </div>
                  )}
                  {call.error && (
                    <div className="text-xs text-red-600 bg-red-50 p-2 rounded">
                      {call.error}
                    </div>
                  )}
                  {call.timestamp && (
                    <div className="text-xs text-gray-400 mt-2">
                      {new Date(call.timestamp).toLocaleString()}
                    </div>
                  )}
                </DisclosurePanel>
              </div>
            )}
          </Disclosure>
        ))}
      </div>
    </div>
  )
}
