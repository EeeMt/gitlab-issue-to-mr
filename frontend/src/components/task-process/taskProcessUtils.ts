import type { Component } from 'vue'
import type { TaskLog, ToolCall } from '../../api'
import {
  TerminalOutline,
  CreateOutline,
  DocumentTextOutline,
  PencilOutline,
  SearchOutline,
  ExtensionPuzzleOutline,
} from '@vicons/ionicons5'

export interface ParsedTextEntry {
  text: string
  payloadId: number | null
  charCount: number | null
}

export interface NormalizedTextEventRow {
  kind: 'thinking' | 'assistant_text'
  event: TaskLog
  textEntry: ParsedTextEntry
}

export interface NormalizedToolEventRow {
  kind: 'tool_call'
  event: TaskLog
  toolCall: ToolCall
}

export type NormalizedTaskProcessRow = NormalizedTextEventRow | NormalizedToolEventRow

const STRUCTURED_TYPES = new Set(['thinking', 'assistant_text', 'tool_call'])

export function isTextRow(row: NormalizedTaskProcessRow): row is NormalizedTextEventRow {
  return row.kind === 'thinking' || row.kind === 'assistant_text'
}

export function isToolRow(row: NormalizedTaskProcessRow): row is NormalizedToolEventRow {
  return row.kind === 'tool_call'
}

export function getToolIcon(name: string): Component {
  switch (name) {
    case 'Bash': return TerminalOutline
    case 'Write':
    case 'MultiEdit': return CreateOutline
    case 'Read': return DocumentTextOutline
    case 'Edit': return PencilOutline
    case 'Glob':
    case 'Grep': return SearchOutline
    default: return ExtensionPuzzleOutline
  }
}

export function getToolColor(name: string): string {
  switch (name) {
    case 'Bash': return '#7c3aed'
    case 'Write':
    case 'MultiEdit': return '#059669'
    case 'Read': return '#0284c7'
    case 'Edit': return '#d97706'
    case 'Glob':
    case 'Grep': return '#64748b'
    default: return '#db2777'
  }
}

export function getInputSummary(call: ToolCall): string {
  const input = call.input
  if (!input) return ''
  switch (call.name) {
    case 'Bash': {
      const cmd = typeof input.command === 'string' ? input.command : ''
      return cmd.length > 80 ? cmd.slice(0, 80) + '…' : cmd
    }
    case 'Write':
    case 'Edit':
    case 'Read':
    case 'MultiEdit': {
      const path =
        (typeof input.file_path === 'string' ? input.file_path : null) ??
        (typeof input.new_file_path === 'string' ? input.new_file_path : null) ??
        ''
      return path
    }
    case 'Glob':
      return typeof input.pattern === 'string' ? input.pattern : ''
    case 'Grep': {
      const pattern = typeof input.pattern === 'string' ? input.pattern : ''
      const include = typeof (input as Record<string, unknown>).include === 'string'
        ? ` (${String((input as Record<string, unknown>).include)})`
        : ''
      return pattern + include
    }
    default: {
      const firstStr = Object.values(input).find((v) => typeof v === 'string')
      return typeof firstStr === 'string' ? String(firstStr).slice(0, 80) : ''
    }
  }
}

export function hasDetailedInput(call: ToolCall): boolean {
  if (call.input_payload_id) return true
  const input = call.input
  if (!input || Object.keys(input).length === 0) return false
  if (['Read', 'Glob', 'Grep'].includes(call.name) && Object.keys(input).length <= 2) return false
  return true
}

export function formatInput(call: ToolCall): string {
  const input = call.input
  if (!input) return ''
  switch (call.name) {
    case 'Bash':
      return typeof input.command === 'string' ? input.command : JSON.stringify(input, null, 2)
    case 'Write':
    case 'MultiEdit':
      return JSON.stringify(input, null, 2)
    case 'Edit': {
      const editInput = input as Record<string, unknown>
      const parts: string[] = []
      if (editInput.file_path) parts.push(`file: ${editInput.file_path}`)
      if (editInput.old_string) parts.push(`--- (old)\n${editInput.old_string}`)
      if (editInput.new_string) parts.push(`+++ (new)\n${editInput.new_string}`)
      return parts.length > 0 ? parts.join('\n\n') : JSON.stringify(input, null, 2)
    }
    default:
      return JSON.stringify(input, null, 2)
  }
}

export function formatTimestamp(iso: string): string {
  try {
    const isoUtc = iso.endsWith('Z') || /[+-]\d{2}:\d{2}$/.test(iso) ? iso : iso + 'Z'
    const d = new Date(isoUtc)
    return d.toLocaleTimeString('zh-CN', {
      timeZone: 'Asia/Shanghai',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
      hour12: false,
    })
  } catch {
    return ''
  }
}

export function parseToolCall(log: TaskLog): ToolCall {
  try {
    const call = JSON.parse(log.metadata ?? '{}') as ToolCall
    return { ...call, timestamp: log.created_at }
  } catch {
    return { name: 'Unknown', input: {}, output: null, error: false }
  }
}

export function parseTextEntry(metadata: string | null | undefined): ParsedTextEntry {
  if (!metadata) return { text: '', payloadId: null, charCount: null }
  try {
    const obj = JSON.parse(metadata) as Record<string, unknown>
    const text = typeof obj.text === 'string' ? obj.text : ''
    const payloadId = typeof obj.payload_id === 'number' ? obj.payload_id : null
    const charCount = typeof obj.char_count === 'number' ? obj.char_count : null
    return { text, payloadId, charCount }
  } catch {
    return { text: metadata, payloadId: null, charCount: null }
  }
}

export function parseSystemInitEntry(taskLogs: TaskLog[]) {
  const entry = taskLogs.find((l) => l.log_type === 'system_init')
  if (!entry?.metadata) return null
  try {
    const obj = JSON.parse(entry.metadata) as Record<string, unknown>
    return {
      model: typeof obj.model === 'string' ? obj.model : null,
      cwd: typeof obj.cwd === 'string' ? obj.cwd : null,
    }
  } catch {
    return null
  }
}

export function normalizeTaskProcessRows(taskLogs: TaskLog[]): NormalizedTaskProcessRow[] {
  const directEvents = taskLogs.filter((l) => STRUCTURED_TYPES.has(l.log_type ?? ''))
  const batchEvents: TaskLog[] = []

  for (const batch of taskLogs.filter((l) => l.log_type === 'tool_calls_json')) {
    if (!batch.metadata) continue
    try {
      const calls = JSON.parse(batch.metadata) as ToolCall[]
      calls.forEach((call, i) => {
        batchEvents.push({
          id: -(batch.id * 1000 + i + 1),
          task_id: batch.task_id,
          log_level: 'info',
          log_type: 'tool_call',
          metadata: JSON.stringify(call),
          message: '',
          created_at: batch.created_at,
        })
      })
    } catch {
      // ignore parse errors
    }
  }

  const individualToolCallKeys = new Set(
    directEvents
      .filter((event) => event.log_type === 'tool_call')
      .map((event) => `${event.created_at}:${event.metadata ?? ''}`),
  )

  const dedupedBatchEvents = batchEvents.filter(
    (event) => !individualToolCallKeys.has(`${event.created_at}:${event.metadata ?? ''}`),
  )

  const sortedEvents = [...directEvents, ...dedupedBatchEvents].sort((a, b) => a.created_at.localeCompare(b.created_at))
  const rows: NormalizedTaskProcessRow[] = []
  for (const event of sortedEvents) {
    if (event.log_type === 'thinking' || event.log_type === 'assistant_text') {
      rows.push({ kind: event.log_type, event, textEntry: parseTextEntry(event.metadata) })
    } else if (event.log_type === 'tool_call') {
      rows.push({ kind: 'tool_call', event, toolCall: parseToolCall(event) })
    }
  }
  return rows
}

export function renderMarkdown(text: string): string {
  if (!text) return ''
  let html = text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')

  html = html.replace(/```[\w]*\n?([\s\S]*?)```/g, (_, code) => `<pre class="md-code-block"><code>${code}</code></pre>`)
  html = html.replace(/`([^`]+)`/g, '<code class="md-inline-code">$1</code>')
  html = html.replace(/^### (.+)$/gm, '<h3>$1</h3>')
  html = html.replace(/^## (.+)$/gm, '<h2>$1</h2>')
  html = html.replace(/^# (.+)$/gm, '<h1>$1</h1>')
  html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
  html = html.replace(/__(.+?)__/g, '<strong>$1</strong>')
  html = html.replace(/\*(.+?)\*/g, '<em>$1</em>')
  html = html.replace(/_(.+?)_/g, '<em>$1</em>')
  html = html.replace(/^[*-] (.+)$/gm, '<li>$1</li>')
  html = html.replace(/(<li>.*<\/li>)/s, '<ul>$1</ul>')
  html = html.replace(/\n/g, '<br>')

  return html
}
