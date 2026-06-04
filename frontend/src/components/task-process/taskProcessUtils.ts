import type { Component } from 'vue'
import type { TaskLog, ToolCall } from '../../api'
import MarkdownIt from 'markdown-it'
import hljs from 'highlight.js/lib/core'
import javascript from 'highlight.js/lib/languages/javascript'
import typescript from 'highlight.js/lib/languages/typescript'
import python from 'highlight.js/lib/languages/python'
import bash from 'highlight.js/lib/languages/bash'
import json from 'highlight.js/lib/languages/json'
import yaml from 'highlight.js/lib/languages/yaml'
import xml from 'highlight.js/lib/languages/xml'
import css from 'highlight.js/lib/languages/css'
import sql from 'highlight.js/lib/languages/sql'
import go from 'highlight.js/lib/languages/go'
import rust from 'highlight.js/lib/languages/rust'
import java from 'highlight.js/lib/languages/java'
import cpp from 'highlight.js/lib/languages/cpp'
import plaintext from 'highlight.js/lib/languages/plaintext'

hljs.registerLanguage('javascript', javascript)
hljs.registerLanguage('js', javascript)
hljs.registerLanguage('typescript', typescript)
hljs.registerLanguage('ts', typescript)
hljs.registerLanguage('python', python)
hljs.registerLanguage('py', python)
hljs.registerLanguage('bash', bash)
hljs.registerLanguage('sh', bash)
hljs.registerLanguage('shell', bash)
hljs.registerLanguage('json', json)
hljs.registerLanguage('yaml', yaml)
hljs.registerLanguage('yml', yaml)
hljs.registerLanguage('xml', xml)
hljs.registerLanguage('html', xml)
hljs.registerLanguage('css', css)
hljs.registerLanguage('sql', sql)
hljs.registerLanguage('go', go)
hljs.registerLanguage('rust', rust)
hljs.registerLanguage('java', java)
hljs.registerLanguage('cpp', cpp)
hljs.registerLanguage('c', cpp)
hljs.registerLanguage('plaintext', plaintext)
hljs.registerLanguage('text', plaintext)

const md: MarkdownIt = new MarkdownIt({
  html: false,
  breaks: true,
  linkify: true,
  highlight(str, lang): string {
    if (lang && hljs.getLanguage(lang)) {
      try {
        const highlighted = hljs.highlight(str, { language: lang, ignoreIllegals: true }).value
        return `<pre class="md-code-block hljs"><code class="language-${lang}">${highlighted}</code></pre>`
      } catch { /* ignore */ }
    }
    return `<pre class="md-code-block hljs"><code>${md.utils.escapeHtml(str)}</code></pre>`
  },
})
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
  preview: string
  payloadId: number | null
  charCount: number | null
  truncated: boolean
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

export interface NormalizedCompactRow {
  kind: 'context_compact'
  event: TaskLog
}

export type NormalizedTaskProcessRow = NormalizedTextEventRow | NormalizedToolEventRow | NormalizedCompactRow

export interface SkillUsageStat {
  name: string
  count: number
}

const STRUCTURED_TYPES = new Set(['thinking', 'assistant_text', 'tool_call', 'context_compact'])

function parseJsonMetadata(metadata: unknown): unknown {
  if (typeof metadata !== 'string') return metadata
  try {
    return JSON.parse(metadata)
  } catch {
    return metadata
  }
}

function normalizeSkillName(value: unknown): string | null {
  if (typeof value === 'string') {
    const trimmed = value.trim()
    if (!trimmed) return null
    const pathParts = trimmed.split(/[\\/]/).filter(Boolean)
    if (pathParts[pathParts.length - 1]?.toLowerCase() === 'skill.md' && pathParts.length >= 2) {
      return pathParts[pathParts.length - 2]
    }
    return pathParts[pathParts.length - 1] || trimmed
  }
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null
  const obj = value as Record<string, unknown>
  return normalizeSkillName(
    obj.name ?? obj.skill_name ?? obj.skillName ?? obj.skill ?? obj.id ?? obj.path,
  )
}

function normalizeSkillCount(value: unknown): number {
  const count = Number(value)
  return Number.isFinite(count) && count > 0 ? count : 1
}

function addSkillUsage(
  usage: Map<string, number>,
  nameValue: unknown,
  countValue: unknown = 1,
) {
  const name = normalizeSkillName(nameValue)
  if (!name) return
  usage.set(name, (usage.get(name) ?? 0) + normalizeSkillCount(countValue))
}

function collectSkillUsageValue(
  usage: Map<string, number>,
  value: unknown,
  countValue: unknown = 1,
) {
  if (!value) return

  if (typeof value === 'string') {
    addSkillUsage(usage, value, countValue)
    return
  }

  if (Array.isArray(value)) {
    for (const item of value) {
      if (item && typeof item === 'object' && !Array.isArray(item)) {
        const obj = item as Record<string, unknown>
        addSkillUsage(usage, obj.name ?? obj.skill_name ?? obj.skillName ?? obj.skill ?? obj.id ?? obj.path, obj.count ?? obj.times ?? obj.uses)
      } else {
        addSkillUsage(usage, item)
      }
    }
    return
  }

  if (typeof value === 'object') {
    for (const [name, countOrMeta] of Object.entries(value as Record<string, unknown>)) {
      if (countOrMeta && typeof countOrMeta === 'object' && !Array.isArray(countOrMeta)) {
        const obj = countOrMeta as Record<string, unknown>
        addSkillUsage(usage, obj.name ?? obj.skill_name ?? obj.skillName ?? obj.skill ?? obj.id ?? obj.path ?? name, obj.count ?? obj.times ?? obj.uses)
      } else {
        addSkillUsage(usage, name, countOrMeta)
      }
    }
  }
}

function collectSkillUsageFromToolCall(usage: Map<string, number>, call: ToolCall) {
  const toolName = normalizeSkillName(call.name)?.toLowerCase()
  if (!toolName) return

  if (toolName === 'agent') {
    addSkillUsage(usage, call.input?.subagent_type ?? call.input?.agent_type ?? call.input?.type)
    return
  }

  if (!['skill', 'skill_use', 'skill_used', 'use_skill', 'useskill'].includes(toolName)) {
    return
  }

  const callObj = call as unknown as Record<string, unknown>
  addSkillUsage(
    usage,
    callObj.skill_name ?? callObj.skillName ?? callObj.skill ?? callObj.id ?? callObj.path,
    callObj.count ?? callObj.times ?? callObj.uses,
  )

  const input = call.input
  if (!input || typeof input !== 'object' || Array.isArray(input)) {
    collectSkillUsageValue(usage, input)
    return
  }

  const inputObj = input as Record<string, unknown>
  collectSkillUsageValue(usage, inputObj.skills)
  collectSkillUsageValue(usage, inputObj.skill_usage ?? inputObj.skillUsage)
  collectSkillUsageValue(usage, inputObj.used_skills ?? inputObj.usedSkills)
  collectSkillUsageValue(usage, inputObj.skills_used ?? inputObj.skillsUsed)
  addSkillUsage(
    usage,
    inputObj.skill_name ?? inputObj.skillName ?? inputObj.skill ?? inputObj.name ?? inputObj.id ?? inputObj.path,
    inputObj.count ?? inputObj.times ?? inputObj.uses,
  )
}

export function summarizeSkillUsage(taskLogs: TaskLog[]): SkillUsageStat[] {
  const usage = new Map<string, number>()

  for (const row of normalizeTaskProcessRows(taskLogs)) {
    if (row.kind === 'tool_call') {
      collectSkillUsageFromToolCall(usage, row.toolCall)
    }
  }

  return Array.from(usage.entries())
    .map(([name, count]) => ({ name, count }))
    .sort((a, b) => b.count - a.count || a.name.localeCompare(b.name))
}

export function isTextRow(row: NormalizedTaskProcessRow): row is NormalizedTextEventRow {
  return row.kind === 'thinking' || row.kind === 'assistant_text'
}

export function isToolRow(row: NormalizedTaskProcessRow): row is NormalizedToolEventRow {
  return row.kind === 'tool_call'
}

export function isCompactRow(row: NormalizedTaskProcessRow): row is NormalizedCompactRow {
  return row.kind === 'context_compact'
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
  if (call.input_preview) return call.input_truncated ? call.input_preview + '…' : call.input_preview
  const input = call.input
  if (!input || Object.keys(input).length === 0) return ''
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
      if (typeof firstStr !== 'string') return ''
      const s = String(firstStr)
      return s.length > 80 ? s.slice(0, 80) + '…' : s
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
  const metadata = parseJsonMetadata(log.metadata)
  const call = (metadata && typeof metadata === 'object' && !Array.isArray(metadata))
    ? metadata as unknown as ToolCall
    : { name: 'Unknown', input: {}, output: null, error: false }
  return { ...call, timestamp: log.created_at }
}

export function parseTextEntry(metadata: unknown): ParsedTextEntry {
  const parsedMetadata = parseJsonMetadata(metadata)
  if (!parsedMetadata || typeof parsedMetadata !== 'object' || Array.isArray(parsedMetadata))
    return { text: '', preview: '', payloadId: null, charCount: null, truncated: false }
  const obj = parsedMetadata as Record<string, unknown>
  const text = typeof obj.text === 'string' ? obj.text : ''
  const preview = typeof obj.preview === 'string' ? obj.preview : ''
  const payloadId = typeof obj.payload_id === 'number' ? obj.payload_id : null
  const charCount = typeof obj.char_count === 'number' ? obj.char_count : null
  const truncated = obj.truncated === true
  return { text, preview, payloadId, charCount, truncated }
}

export function parseSystemInitEntry(taskLogs: TaskLog[]) {
  const entry = taskLogs.find((l) => l.log_type === 'system_init')
  const metadata = parseJsonMetadata(entry?.metadata)
  if (!metadata || typeof metadata !== 'object' || Array.isArray(metadata)) return null
  const obj = metadata as Record<string, unknown>
  return {
    model: typeof obj.model === 'string' ? obj.model : null,
    cwd: typeof obj.cwd === 'string' ? obj.cwd : null,
  }
}

export function normalizeTaskProcessRows(taskLogs: TaskLog[]): NormalizedTaskProcessRow[] {
  const directEvents = taskLogs.filter((l) => STRUCTURED_TYPES.has(l.log_type ?? ''))

  const sortedEvents = [...directEvents].sort((a, b) => a.created_at.localeCompare(b.created_at))
  const rows: NormalizedTaskProcessRow[] = []
  for (const event of sortedEvents) {
    if (event.log_type === 'thinking' || event.log_type === 'assistant_text') {
      rows.push({ kind: event.log_type, event, textEntry: parseTextEntry(event.metadata) })
    } else if (event.log_type === 'tool_call') {
      rows.push({ kind: 'tool_call', event, toolCall: parseToolCall(event) })
    } else if (event.log_type === 'context_compact') {
      rows.push({ kind: 'context_compact', event })
    }
  }
  return rows
}

export function renderMarkdown(text: string): string {
  if (!text) return ''
  return md.render(text)
}
