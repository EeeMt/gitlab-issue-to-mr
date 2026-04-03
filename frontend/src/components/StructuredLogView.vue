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
      v-if="toolCalls.length === 0"
      :description="t('taskView.noToolCalls')"
      class="structured-log-view__empty"
    />

    <!-- Tool call list -->
    <div v-else class="structured-log-view__list">
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
        </div>

        <!-- Collapsible output -->
        <n-collapse v-if="call.output" class="tool-call-item__collapse">
          <n-collapse-item name="output">
            <template #header>
              <span class="tool-call-item__output-label">Output</span>
            </template>
            <pre
              class="tool-call-item__pre"
              :class="{ 'tool-call-item__pre--error': call.error }"
            >{{ call.output }}</pre>
          </n-collapse-item>
        </n-collapse>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { NIcon, NTag, NEmpty, NCollapse, NCollapseItem } from 'naive-ui'
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

.tool-call-item__collapse {
  margin-top: 4px;
  margin-left: 28px;
}

.tool-call-item__output-label {
  font-size: 11px;
  color: var(--n-text-color-3, #999);
}

.tool-call-item__pre {
  margin: 0;
  padding: 8px;
  font-size: 11px;
  font-family: var(--n-font-family-mono, 'JetBrains Mono', 'Fira Code', monospace);
  max-height: 200px;
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
</style>
