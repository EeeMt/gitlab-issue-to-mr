<template>
  <n-card class="task-process-panel" :bordered="false">
    <template #header>
      <span class="panel-title">{{ t('taskView.taskProcess') }}</span>
      <n-tag v-if="isActive" type="success" size="small" round :class="{ 'live-badge--pulse': isActive }" style="margin-left: 8px">{{ t('taskView.realTime') }}</n-tag>
    </template>

    <!-- system_init banner -->
    <div v-if="systemInitEntry" class="system-init-banner">
      <n-icon size="14" class="system-init-banner__icon"><ServerOutline /></n-icon>
      <span v-if="systemInitEntry.model">{{ t('taskView.modelName') }}: <strong>{{ systemInitEntry.model }}</strong></span>
      <span v-if="systemInitEntry.model && systemInitEntry.cwd" class="system-init-banner__sep">|</span>
      <span v-if="systemInitEntry.cwd">CWD: <code class="system-init-banner__cwd">{{ systemInitEntry.cwd }}</code></span>
    </div>

    <!-- No structured logs: show tabs with empty events + optional raw -->
    <template v-if="!hasStructuredContent">
      <n-tabs v-model:value="activeTab" type="line" size="small" class="process-tabs">
        <n-tab-pane name="events" :tab="t('taskView.eventsTab')">
          <n-empty v-if="taskStatus === 'pending' || taskStatus === 'queued'" :description="t('taskView.taskNotStarted')" class="empty-state" />
          <n-empty v-else-if="!isActive && !terminalHtml" :description="t('taskView.noLogsAvailable')" class="empty-state" />
          <n-empty v-else :description="t('taskView.noProcessYet')" class="empty-state" />
        </n-tab-pane>
        <n-tab-pane name="raw" :tab="t('taskView.rawLogsTab')" :disabled="!terminalHtml">
          <pre v-if="terminalHtml" class="log-content" v-html="terminalHtml"></pre>
          <n-empty v-else description="暂无原始日志" />
        </n-tab-pane>
      </n-tabs>
    </template>

    <!-- Structured event stream with tabs -->
    <template v-else>
      <n-tabs v-model:value="activeTab" type="line" size="small" class="process-tabs">
        <n-tab-pane name="events" :tab="t('taskView.eventsTab')">
          <div class="event-stream" ref="eventStreamRef">
            <!-- Container assigned (first step) -->
            <div v-if="props.task?.container_id" class="event-item event-item--container">
              <div class="event-header">
                <div class="event-icon" style="color: #059669">
                  <n-icon size="15"><CubeOutline /></n-icon>
                </div>
                <div class="event-info">
                  <span class="event-name">{{ t('taskView.container') }}</span>
                </div>
              </div>
              <n-collapse class="event-collapse">
                <n-collapse-item name="detail">
                  <template #header>
                    <span class="tool-detail-label">{{ t('taskView.container') }}</span>
                  </template>
                  <div class="container-detail">
                    <span class="container-name">{{ props.task.container_name ?? '—' }}</span>
                    <span class="container-id-short">{{ props.task.container_id.slice(0, 12) }}</span>
                  </div>
                </n-collapse-item>
              </n-collapse>
            </div>

            <template v-for="(event, index) in sortedEvents" :key="index">
              <!-- thinking entry -->
              <div v-if="event.log_type === 'thinking'" class="event-item event-item--thinking"
                :ref="(el) => { collapseRefs[index] = el as HTMLElement }">
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
                <n-collapse class="event-collapse" @update:expanded-names="(names) => onCollapseChange(names, index)">
                  <n-collapse-item name="detail">
                    <template #header>
                      <span class="tool-detail-label">{{ t('taskView.fullText') }}</span>
                    </template>
                    <div class="event-content event-content--thinking markdown-content" v-html="renderMarkdown(parseTextMeta(event.metadata))"></div>
                  </n-collapse-item>
                </n-collapse>
              </div>

              <!-- assistant_text entry -->
              <div v-else-if="event.log_type === 'assistant_text'" class="event-item event-item--assistant"
                :ref="(el) => { collapseRefs[index] = el as HTMLElement }">
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
                <n-collapse class="event-collapse" @update:expanded-names="(names) => onCollapseChange(names, index)">
                  <n-collapse-item name="detail">
                    <template #header>
                      <span class="tool-detail-label">{{ t('taskView.fullText') }}</span>
                    </template>
                    <div class="event-content markdown-content" v-html="renderMarkdown(parseTextMeta(event.metadata))"></div>
                  </n-collapse-item>
                </n-collapse>
              </div>

              <!-- tool_call entry -->
              <div v-else-if="event.log_type === 'tool_call'" class="event-item event-item--tool"
                :ref="(el) => { collapseRefs[index] = el as HTMLElement }">
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
                <n-collapse class="event-collapse" @update:expanded-names="(names) => onCollapseChange(names, index)">
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
          </div>
        </n-tab-pane>
        <n-tab-pane name="raw" :tab="t('taskView.rawLogsTab')" :disabled="!terminalHtml">
          <pre v-if="terminalHtml" class="log-content" v-html="terminalHtml"></pre>
          <n-empty v-else description="暂无原始日志" />
        </n-tab-pane>
      </n-tabs>
    </template>
  </n-card>
</template>

<script setup lang="ts">
import { computed, ref, watch, nextTick } from 'vue'
import { NCard, NCollapse, NCollapseItem, NIcon, NTag, NEmpty, NTabs, NTabPane } from 'naive-ui'
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
  ChatboxOutline,
  CubeOutline
} from '@vicons/ionicons5'
import type { Component } from 'vue'
import type { TaskLog, ToolCall, Task } from '../api'

const props = defineProps<{
  task: Task | null
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
    // Timestamps from API are UTC but lack 'Z' suffix — append it
    const isoUtc = iso.endsWith('Z') || /[+-]\d{2}:\d{2}$/.test(iso) ? iso : iso + 'Z'
    const d = new Date(isoUtc)
    // Display in UTC+8 (Asia/Shanghai)
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

// ── Auto-scroll ref ───────────────────────────────────────────────────────────

const eventStreamRef = ref<HTMLElement | null>(null)
const activeTab = ref<'events' | 'raw'>('events')
const collapseRefs = ref<(HTMLElement | null)[]>([])

function onCollapseChange(expandedNames: (string | number)[], index: number) {
  if (expandedNames.length > 0) {
    nextTick(() => {
      collapseRefs.value[index]?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
    })
  }
}

// ── Markdown renderer ─────────────────────────────────────────────────────────

function renderMarkdown(text: string): string {
  if (!text) return ''
  // Escape HTML entities first
  let html = text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')

  // Code blocks (``` ... ```)
  html = html.replace(/```[\w]*\n?([\s\S]*?)```/g, (_, code) =>
    `<pre class="md-code-block"><code>${code}</code></pre>`
  )

  // Inline code
  html = html.replace(/`([^`]+)`/g, '<code class="md-inline-code">$1</code>')

  // Headers
  html = html.replace(/^### (.+)$/gm, '<h3>$1</h3>')
  html = html.replace(/^## (.+)$/gm, '<h2>$1</h2>')
  html = html.replace(/^# (.+)$/gm, '<h1>$1</h1>')

  // Bold
  html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
  html = html.replace(/__(.+?)__/g, '<strong>$1</strong>')

  // Italic
  html = html.replace(/\*(.+?)\*/g, '<em>$1</em>')
  html = html.replace(/_(.+?)_/g, '<em>$1</em>')

  // Unordered lists (lines starting with - or *)
  html = html.replace(/^[*-] (.+)$/gm, '<li>$1</li>')
  html = html.replace(/(<li>.*<\/li>)/s, '<ul>$1</ul>')

  // Line breaks (preserve newlines)
  html = html.replace(/\n/g, '<br>')

  return html
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

// ── Auto-scroll watch (after sortedEvents is defined) ─────────────────────────

watch(sortedEvents, async () => {
  if (!props.isActive) return
  await nextTick()
  if (eventStreamRef.value) {
    eventStreamRef.value.scrollTo({ top: eventStreamRef.value.scrollHeight, behavior: 'smooth' })
  }
})
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

.markdown-content {
  white-space: normal;
}

.markdown-content h1,
.markdown-content h2,
.markdown-content h3 {
  font-weight: 600;
  margin: 8px 0 4px;
  line-height: 1.4;
}

.markdown-content h1 { font-size: 16px; }
.markdown-content h2 { font-size: 14px; }
.markdown-content h3 { font-size: 13px; }

.markdown-content strong { font-weight: 600; }
.markdown-content em { font-style: italic; }

.markdown-content ul {
  padding-left: 18px;
  margin: 4px 0;
  list-style: disc;
}

.markdown-content li { margin: 2px 0; }

.markdown-content :deep(.md-code-block) {
  margin: 6px 0;
  padding: 8px;
  font-size: 11px;
  font-family: var(--n-font-family-mono, monospace);
  background: var(--n-color-embedded, rgba(128, 128, 128, 0.08));
  border-radius: 4px;
  overflow-x: auto;
  white-space: pre;
}

.markdown-content :deep(.md-inline-code) {
  font-family: var(--n-font-family-mono, monospace);
  font-size: 12px;
  background: rgba(128, 128, 128, 0.1);
  padding: 1px 4px;
  border-radius: 3px;
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

.process-tabs {
  margin-top: 0;
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

.container-detail {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.container-name {
  font-family: var(--n-font-family-mono, 'JetBrains Mono', monospace);
  font-size: 13px;
  color: var(--n-text-color-1);
}

.container-id-short {
  font-family: var(--n-font-family-mono, 'JetBrains Mono', monospace);
  font-size: 11px;
  color: var(--n-text-color-3, #999);
  background: rgba(128, 128, 128, 0.08);
  padding: 1px 6px;
  border-radius: 4px;
}
</style>
