<template>
  <n-card class="task-process-panel" :bordered="false">
    <template #header>
      <span class="panel-title">{{ t('taskView.taskProcess') }}</span>
    </template>
    <template #header-extra>
      <n-tag v-if="isActive" type="warning" size="small" round :class="{ 'live-badge--pulse': isActive }">{{ t('taskView.realTime') }}</n-tag>
    </template>

    <!-- system_init banner -->
    <div v-if="systemInitEntry" class="system-init-banner">
      <n-icon size="14" class="system-init-banner__icon"><ServerOutline /></n-icon>
      <span v-if="systemInitEntry.model">{{ t('taskView.modelName') }}: <strong>{{ systemInitEntry.model }}</strong></span>
      <span v-if="systemInitEntry.model && systemInitEntry.cwd" class="system-init-banner__sep">|</span>
      <span v-if="systemInitEntry.cwd">CWD: <code class="system-init-banner__cwd">{{ systemInitEntry.cwd }}</code></span>
    </div>

    <!-- No structured logs fallback: show raw logs directly -->
    <template v-if="!hasStructuredContent">
      <n-empty v-if="taskStatus === 'pending' || taskStatus === 'queued'" :description="t('taskView.taskNotStarted')" class="empty-state" />
      <pre v-else-if="terminalHtml" class="log-content" v-html="terminalHtml"></pre>
      <n-empty v-else-if="!isActive" :description="t('taskView.noLogsAvailable')" class="empty-state" />
      <n-empty v-else :description="t('taskView.noProcessYet')" class="empty-state" />
    </template>

    <!-- Structured event stream -->
    <template v-else>
      <div class="event-stream">
        <template v-for="(event, index) in sortedEvents" :key="index">
          <!-- thinking entry -->
          <div v-if="event.log_type === 'thinking'" class="event-item event-item--thinking">
            <div class="event-header">
              <div class="event-icon" style="color: #888">
                <n-icon size="15"><BulbOutline /></n-icon>
              </div>
              <div class="event-info">
                <span class="event-name">{{ t('taskView.thinkingLabel') }}</span>
                <span v-if="parseTextMeta(event.metadata)" class="event-preview">
                  {{ parseTextMeta(event.metadata).slice(0, 120) }}
                </span>
              </div>
              <span class="event-ts">{{ formatTimestamp(event.created_at) }}</span>
            </div>
            <n-collapse class="event-collapse">
              <n-collapse-item name="detail">
                <template #header>
                  <span class="tool-detail-label">{{ t('taskView.fullText') }}</span>
                </template>
                <pre class="event-content event-content--thinking">{{ parseTextMeta(event.metadata) }}</pre>
              </n-collapse-item>
            </n-collapse>
          </div>

          <!-- assistant_text entry -->
          <div v-else-if="event.log_type === 'assistant_text'" class="event-item event-item--assistant">
            <div class="event-header">
              <div class="event-icon" style="color: #0284c7">
                <n-icon size="15"><ChatboxOutline /></n-icon>
              </div>
              <div class="event-info">
                <span class="event-name">{{ t('taskView.assistantLabel') }}</span>
                <span v-if="parseTextMeta(event.metadata)" class="event-preview">
                  {{ parseTextMeta(event.metadata).slice(0, 120) }}
                </span>
              </div>
              <span class="event-ts">{{ formatTimestamp(event.created_at) }}</span>
            </div>
            <n-collapse class="event-collapse">
              <n-collapse-item name="detail">
                <template #header>
                  <span class="tool-detail-label">{{ t('taskView.fullText') }}</span>
                </template>
                <pre class="event-content">{{ parseTextMeta(event.metadata) }}</pre>
              </n-collapse-item>
            </n-collapse>
          </div>

          <!-- tool_call entry -->
          <div v-else-if="event.log_type === 'tool_call'" class="event-item event-item--tool">
            <div class="event-header">
              <div class="event-icon" :style="{ color: getToolColor(parsedToolCall(event).name) }">
                <n-icon size="15">
                  <component :is="getToolIcon(parsedToolCall(event).name)" />
                </n-icon>
              </div>
              <div class="event-info">
                <span class="event-name">{{ parsedToolCall(event).name }}</span>
                <span v-if="getInputSummary(parsedToolCall(event))" class="event-preview">
                  {{ getInputSummary(parsedToolCall(event)) }}
                </span>
              </div>
              <n-tag v-if="parsedToolCall(event).error" type="error" size="small" round>Error</n-tag>
              <span class="event-ts">{{ formatTimestamp(event.created_at) }}</span>
            </div>
            <n-collapse class="event-collapse">
              <n-collapse-item v-if="hasDetailedInput(parsedToolCall(event))" name="input">
                <template #header>
                  <span class="tool-detail-label">{{ t('taskView.toolInput') }}</span>
                </template>
                <pre class="tool-pre tool-pre--input">{{ formatInput(parsedToolCall(event)) }}</pre>
              </n-collapse-item>
              <n-collapse-item v-if="parsedToolCall(event).output" name="output">
                <template #header>
                  <span class="tool-detail-label">{{ t('taskView.toolOutput') }}</span>
                </template>
                <pre class="tool-pre" :class="{ 'tool-pre--error': parsedToolCall(event).error }">{{ parsedToolCall(event).output }}</pre>
              </n-collapse-item>
            </n-collapse>
          </div>
        </template>

        <!-- Live indicator removed: pulsing badge in header is used instead -->
      </div>

      <!-- Raw logs fallback section -->
      <n-collapse class="raw-logs-collapse" v-if="terminalHtml">
        <n-collapse-item :title="t('taskView.rawLogs')" name="raw">
          <pre class="log-content" v-html="terminalHtml"></pre>
        </n-collapse-item>
      </n-collapse>
    </template>
  </n-card>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { NCard, NCollapse, NCollapseItem, NIcon, NTag, NEmpty } from 'naive-ui'
import { useI18n } from 'vue-i18n'
import {
  TerminalOutline,
  CreateOutline,
  DocumentTextOutline,
  PencilOutline,
  SearchOutline,
  ExtensionPuzzleOutline,
  ServerOutline,
  BulbOutline,
  ChatboxOutline
} from '@vicons/ionicons5'
import type { Component } from 'vue'
import type { TaskLog, ToolCall } from '../api'

const props = defineProps<{
  taskLogs: TaskLog[]
  isActive: boolean
  terminalHtml: string
  taskStatus: string
}>()

const { t } = useI18n()

// ── Tool helpers ──────────────────────────────────────────────────────────────

function getToolIcon(name: string): Component {
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

function getToolColor(name: string): string {
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

function getInputSummary(call: ToolCall): string {
  const input = call.input
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
      const include = typeof input.include === 'string' ? ` (${input.include})` : ''
      return pattern + include
    }
    default: {
      const firstStr = Object.values(input).find((v) => typeof v === 'string')
      return typeof firstStr === 'string' ? String(firstStr).slice(0, 80) : ''
    }
  }
}

function hasDetailedInput(call: ToolCall): boolean {
  const input = call.input
  if (Object.keys(input).length === 0) return false
  if (['Read', 'Glob', 'Grep'].includes(call.name) && Object.keys(input).length <= 2) return false
  return true
}

function formatInput(call: ToolCall): string {
  const input = call.input
  switch (call.name) {
    case 'Bash':
      return typeof input.command === 'string' ? input.command : JSON.stringify(input, null, 2)
    case 'Write':
    case 'MultiEdit':
      return JSON.stringify(input, null, 2)
    case 'Edit': {
      const parts: string[] = []
      if (input.file_path) parts.push(`file: ${input.file_path}`)
      if (input.old_str) parts.push(`--- (old)\n${input.old_str}`)
      if (input.new_str) parts.push(`+++ (new)\n${input.new_str}`)
      return parts.length > 0 ? parts.join('\n\n') : JSON.stringify(input, null, 2)
    }
    default:
      return JSON.stringify(input, null, 2)
  }
}

function formatTimestamp(iso: string): string {
  try {
    const d = new Date(iso)
    const hh = String(d.getHours()).padStart(2, '0')
    const mm = String(d.getMinutes()).padStart(2, '0')
    const ss = String(d.getSeconds()).padStart(2, '0')
    return `${hh}:${mm}:${ss}`
  } catch {
    return ''
  }
}

// ── Metadata parsers ──────────────────────────────────────────────────────────

function parseTextMeta(metadata: string | null | undefined): string {
  if (!metadata) return ''
  try {
    const obj = JSON.parse(metadata) as Record<string, unknown>
    return typeof obj.text === 'string' ? obj.text : metadata
  } catch {
    return metadata
  }
}

function parsedToolCall(log: TaskLog): ToolCall {
  try {
    const call = JSON.parse(log.metadata ?? '{}') as ToolCall
    return { ...call, timestamp: log.created_at }
  } catch {
    return { name: 'Unknown', input: {}, output: null, error: false }
  }
}

// ── system_init ───────────────────────────────────────────────────────────────

const systemInitEntry = computed(() => {
  const entry = props.taskLogs.find(l => l.log_type === 'system_init')
  if (!entry?.metadata) return null
  try {
    const obj = JSON.parse(entry.metadata) as Record<string, unknown>
    return {
      model: typeof obj.model === 'string' ? obj.model : null,
      cwd: typeof obj.cwd === 'string' ? obj.cwd : null
    }
  } catch {
    return null
  }
})

// ── Single sortedEvents computed (handles both individual + batch) ─────────────

const STRUCTURED_TYPES = new Set(['thinking', 'assistant_text', 'tool_call'])

const sortedEvents = computed<TaskLog[]>(() => {
  const hasIndividual = props.taskLogs.some(l => l.log_type === 'tool_call')

  // Start with structured events (excluding system_init shown as banner, and tool_calls_json)
  const directEvents = props.taskLogs.filter(l => STRUCTURED_TYPES.has(l.log_type ?? ''))

  // If no individual tool_call entries, synthesize from batch tool_calls_json
  const batchEvents: TaskLog[] = []
  if (!hasIndividual) {
    const batch = props.taskLogs.find(l => l.log_type === 'tool_calls_json')
    if (batch?.metadata) {
      try {
        const calls = JSON.parse(batch.metadata) as ToolCall[]
        calls.forEach((call, i) => {
          batchEvents.push({
            id: -(i + 1),
            task_id: batch.task_id,
            log_level: 'info',
            log_type: 'tool_call',
            metadata: JSON.stringify(call),
            message: '',
            created_at: batch.created_at
          })
        })
      } catch {
        // ignore parse errors
      }
    }
  }

  return [...directEvents, ...batchEvents].sort((a, b) =>
    a.created_at.localeCompare(b.created_at)
  )
})

const hasStructuredContent = computed(() =>
  sortedEvents.value.length > 0 || systemInitEntry.value !== null
)
</script>

<style scoped>
.task-process-panel {
  border-radius: var(--app-card-radius);
  overflow: hidden;
  min-width: 0;
}

.panel-title {
  font-size: 18px;
  font-weight: 600;
}

.system-init-banner {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 7px 12px;
  margin-bottom: 12px;
  background: rgba(128, 128, 128, 0.06);
  border-radius: 8px;
  font-size: 12px;
  color: var(--n-text-color-2, #666);
  border-left: 3px solid rgba(128, 128, 128, 0.25);
}

.system-init-banner__icon {
  color: var(--n-text-color-3, #999);
  flex-shrink: 0;
}

.system-init-banner__sep {
  opacity: 0.4;
}

.system-init-banner__cwd {
  font-family: var(--n-font-family-mono, monospace);
  font-size: 11px;
  background: rgba(128, 128, 128, 0.1);
  padding: 1px 5px;
  border-radius: 3px;
}

.event-stream {
  display: flex;
  flex-direction: column;
  overflow-x: hidden;
  overflow-y: auto;
  min-width: 0;
  max-height: 600px;
  padding-right: 4px;
}

.event-item {
  border-bottom: 1px solid var(--n-border-color, rgba(128, 128, 128, 0.1));
  padding: 6px 0;
}

.event-item:last-child {
  border-bottom: none;
}

/* Unified event row */
.event-header {
  display: flex;
  align-items: center;
  gap: 8px;
  min-height: 30px;
}

.event-icon {
  display: flex;
  align-items: center;
  flex-shrink: 0;
  width: 20px;
}

.event-info {
  flex: 1;
  display: flex;
  align-items: baseline;
  flex-wrap: wrap;
  gap: 6px;
  overflow: hidden;
}

.event-name {
  font-weight: 500;
  font-size: 13px;
  flex-shrink: 0;
}

.event-preview {
  font-size: 12px;
  color: var(--n-text-color-3, #999);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  word-break: break-all;
  max-width: 100%;
}

.event-ts {
  font-size: 11px;
  color: var(--n-text-color-3, #999);
  flex-shrink: 0;
  font-family: var(--n-font-family-mono, monospace);
  margin-left: auto;
}

.event-collapse {
  margin-top: 4px;
  margin-left: 28px;
}

/* Expandable content bodies */
.event-content {
  margin: 0;
  padding: 4px 0;
  font-size: 13px;
  line-height: 1.65;
  white-space: pre-wrap;
  word-break: break-word;
  color: var(--n-text-color-2);
  font-family: inherit;
}

.event-content--thinking {
  font-size: 12px;
  color: var(--n-text-color-3, #888);
  font-style: italic;
}

.tool-detail-label {
  font-size: 11px;
  color: var(--n-text-color-3, #999);
}

.tool-pre {
  margin: 0;
  padding: 8px;
  font-size: 11px;
  font-family: var(--n-font-family-mono, monospace);
  max-height: 300px;
  overflow: auto;
  background: var(--n-color-embedded, rgba(128, 128, 128, 0.05));
  border-radius: 4px;
  white-space: pre-wrap;
  word-break: break-all;
  line-height: 1.5;
}

.tool-pre--input {
  color: var(--n-text-color-2, #666);
}

.tool-pre--error {
  background: rgba(239, 68, 68, 0.08);
  color: #ef4444;
}

.live-badge--pulse {
  animation: pulse-badge 2s ease-in-out infinite;
}

@keyframes pulse-badge {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.4; }
}

.raw-logs-collapse {
  margin-top: 16px;
}

.log-content {
  background: #1e1e1e;
  color: #d4d4d4;
  padding: 16px;
  border-radius: 10px;
  max-height: 400px;
  overflow: auto;
  font-family: 'Consolas', 'Monaco', 'Courier New', monospace;
  font-size: 12px;
  white-space: pre-wrap;
  word-break: break-all;
  margin: 0;
}

.empty-state {
  padding: 24px 0;
}
</style>
