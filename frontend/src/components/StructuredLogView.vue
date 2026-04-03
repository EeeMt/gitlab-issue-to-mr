<template>
  <div class="structured-log-view">
    <!-- Token summary row -->
    <div
      v-if="inputTokens !== null || outputTokens !== null"
      class="structured-log-view__tokens"
    >
      <span>{{ t('taskView.inputTokens') }}: {{ (inputTokens ?? 0).toLocaleString() }}</span>
      <span class="structured-log-view__tokens-sep">/</span>
      <span>{{ t('taskView.outputTokens') }}: {{ (outputTokens ?? 0).toLocaleString() }}</span>
      <span class="structured-log-view__tokens-sep">/</span>
      <span>{{ t('taskView.totalTokens') }}: {{ ((inputTokens ?? 0) + (outputTokens ?? 0)).toLocaleString() }}</span>
    </div>

    <!-- Empty state -->
    <n-empty
      v-if="toolCalls.length === 0 && !isActive"
      :description="t('taskView.noToolCalls')"
      class="structured-log-view__empty"
    />

    <!-- Tool call list -->
    <div class="structured-log-view__list">
      <div
        v-for="(call, index) in toolCalls"
        :key="index"
        class="tool-call-item"
        :class="{ 'tool-call-item--error': call.error }"
      >
        <!-- Row header -->
        <div class="tool-call-item__header">
          <div class="tool-call-item__icon" :style="{ color: getToolColor(call.name) }">
            <n-icon size="16">
              <component :is="getToolIcon(call.name)" />
            </n-icon>
          </div>
          <div class="tool-call-item__info">
            <span class="tool-call-item__name">{{ call.name }}</span>
            <span v-if="getInputSummary(call)" class="tool-call-item__summary">{{ getInputSummary(call) }}</span>
          </div>
          <n-tag v-if="call.error" type="error" size="small" round>Error</n-tag>
          <span v-if="call.timestamp" class="tool-call-item__ts">{{ formatTimestamp(call.timestamp) }}</span>
        </div>

        <!-- Collapsible details: input + output -->
        <n-collapse class="tool-call-item__collapse">
          <!-- Full input parameters -->
          <n-collapse-item v-if="hasDetailedInput(call)" name="input">
            <template #header>
              <span class="tool-call-item__detail-label">{{ t('taskView.toolInput') }}</span>
            </template>
            <pre class="tool-call-item__pre tool-call-item__pre--input">{{ formatInput(call) }}</pre>
          </n-collapse-item>
          <!-- Output -->
          <n-collapse-item v-if="call.output" name="output">
            <template #header>
              <span class="tool-call-item__detail-label">{{ t('taskView.toolOutput') }}</span>
            </template>
            <pre
              class="tool-call-item__pre"
              :class="{ 'tool-call-item__pre--error': call.error }"
            >{{ call.output }}</pre>
          </n-collapse-item>
        </n-collapse>
      </div>

      <!-- Live indicator: task still running -->
      <div v-if="isActive" class="tool-call-live">
        <n-spin size="small" />
        <span class="tool-call-live__label">{{ t('taskView.timelineRunning') }}</span>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { NIcon, NTag, NEmpty, NCollapse, NCollapseItem, NSpin } from 'naive-ui'
import { useI18n } from 'vue-i18n'
import {
  TerminalOutline,
  CreateOutline,
  DocumentTextOutline,
  PencilOutline,
  SearchOutline,
  ExtensionPuzzleOutline
} from '@vicons/ionicons5'
import type { Component } from 'vue'
import type { ToolCall } from '../api'

defineProps<{
  toolCalls: ToolCall[]
  inputTokens: number | null
  outputTokens: number | null
  isActive?: boolean
}>()

const { t } = useI18n()

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

/** Returns true when the input has enough detail to warrant an expandable section. */
function hasDetailedInput(call: ToolCall): boolean {
  const input = call.input
  if (Object.keys(input).length === 0) return false
  // For file-path tools, only show input section when there's more than just the path
  if (['Read', 'Glob', 'Grep'].includes(call.name) && Object.keys(input).length <= 2) return false
  return true
}

/** Format the full input as readable text for the expanded section. */
function formatInput(call: ToolCall): string {
  const input = call.input
  switch (call.name) {
    case 'Bash':
      return typeof input.command === 'string' ? input.command : JSON.stringify(input, null, 2)
    case 'Write':
    case 'MultiEdit':
      // For file writes show path + content
      return JSON.stringify(input, null, 2)
    case 'Edit': {
      // Show path, old_str, new_str clearly
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

/** Format ISO timestamp as HH:MM:SS. */
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
</script>

<style scoped>
.structured-log-view {
  font-size: 13px;
}

.structured-log-view__tokens {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 8px;
  margin-bottom: 12px;
  background: var(--n-color-embedded, rgba(128, 128, 128, 0.06));
  border-radius: 6px;
  font-size: 12px;
  color: var(--n-text-color-3, #999);
}

.structured-log-view__tokens-sep {
  opacity: 0.4;
}

.structured-log-view__empty {
  padding: 24px 0;
}

.structured-log-view__list {
  display: flex;
  flex-direction: column;
}

.tool-call-item {
  border-bottom: 1px solid var(--n-border-color, rgba(128, 128, 128, 0.12));
  padding: 8px 0;
}

.tool-call-item:last-child {
  border-bottom: none;
}

.tool-call-item__header {
  display: flex;
  align-items: center;
  gap: 8px;
  min-height: 28px;
}

.tool-call-item__icon {
  display: flex;
  align-items: center;
  flex-shrink: 0;
  width: 20px;
}

.tool-call-item__info {
  flex: 1;
  display: flex;
  align-items: baseline;
  gap: 8px;
  overflow: hidden;
}

.tool-call-item__name {
  font-weight: 600;
  font-size: 12px;
  flex-shrink: 0;
  font-family: var(--n-font-family-mono, 'JetBrains Mono', 'Fira Code', monospace);
}

.tool-call-item__summary {
  font-size: 11px;
  color: var(--n-text-color-3, #999);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-family: var(--n-font-family-mono, 'JetBrains Mono', 'Fira Code', monospace);
}

.tool-call-item__ts {
  font-size: 11px;
  color: var(--n-text-color-3, #999);
  flex-shrink: 0;
  font-family: var(--n-font-family-mono, 'JetBrains Mono', 'Fira Code', monospace);
  margin-left: auto;
}

.tool-call-item__collapse {
  margin-top: 4px;
  margin-left: 28px;
}

.tool-call-item__detail-label {
  font-size: 11px;
  color: var(--n-text-color-3, #999);
}

.tool-call-item__pre {
  margin: 0;
  padding: 8px;
  font-size: 11px;
  font-family: var(--n-font-family-mono, 'JetBrains Mono', 'Fira Code', monospace);
  max-height: 300px;
  overflow: auto;
  background: var(--n-color-embedded, rgba(128, 128, 128, 0.05));
  border-radius: 4px;
  white-space: pre-wrap;
  word-break: break-all;
  line-height: 1.5;
}

.tool-call-item__pre--error {
  background: rgba(239, 68, 68, 0.08);
  color: #ef4444;
}

.tool-call-item__pre--input {
  background: var(--n-color-embedded, rgba(128, 128, 128, 0.05));
  color: var(--n-text-color-2, #666);
}

.tool-call-live {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 0 4px;
  color: var(--n-text-color-3, #999);
}

.tool-call-live__label {
  font-size: 12px;
}
</style>
