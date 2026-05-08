<template>
  <div class="event-item event-item--tool">
    <div class="event-header">
      <div class="event-icon" :style="{ color: getToolColor(row.toolCall.name) }">
        <n-icon size="15"><component :is="getToolIcon(row.toolCall.name)" /></n-icon>
      </div>
      <div class="event-info">
        <span class="event-name">{{ row.toolCall.name }}</span>
        <span v-if="summary" class="event-preview">{{ summary }}</span>
      </div>
      <n-tag v-if="row.toolCall.error" type="error" size="small" round>Error</n-tag>
      <span class="event-ts">{{ formatTimestamp(row.event.created_at) }}</span>
    </div>
    <n-collapse class="event-collapse" @update:expanded-names="(names) => emit('collapse-change', names)">
      <n-collapse-item v-if="hasDetailedToolInput" name="input">
        <template #header>
          <span class="tool-detail-label">{{ t('taskView.toolInput') }}</span>
        </template>
        <n-spin v-if="inputLoading" size="small" />
        <pre v-else class="tool-pre tool-pre--input">{{ inputDisplayText }}</pre>
      </n-collapse-item>
      <n-collapse-item v-if="hasToolEventOutput" name="output">
        <template #header>
          <span class="tool-detail-label">{{ t('taskView.toolOutput') }}</span>
        </template>
        <n-spin v-if="outputLoading" size="small" />
        <pre v-else class="tool-pre" :class="{ 'tool-pre--error': row.toolCall.error }">{{ outputDisplayText }}</pre>
      </n-collapse-item>
    </n-collapse>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { NCollapse, NCollapseItem, NIcon, NSpin, NTag } from 'naive-ui'
import { useI18n } from 'vue-i18n'
import { formatInput, formatTimestamp, getInputSummary, getToolColor, getToolIcon, hasDetailedInput, type NormalizedToolEventRow } from './taskProcessUtils'

const props = defineProps<{
  row: NormalizedToolEventRow
  inputLoaded: boolean
  outputLoaded: boolean
  inputLoading: boolean
  outputLoading: boolean
  inputFailed?: boolean
  outputFailed?: boolean
  inputExpandedText?: string
  outputExpandedText?: string
}>()

const emit = defineEmits<{
  (e: 'collapse-change', names: (string | number)[]): void
}>()

const { t } = useI18n()

const summary = computed(() => getInputSummary(props.row.toolCall))
const hasDetailedToolInput = computed(() => hasDetailedInput(props.row.toolCall))
const hasToolEventOutput = computed(() => props.row.toolCall.output !== null || !!props.row.toolCall.output_payload_id || !!props.row.toolCall.output_preview)
const inputDisplayText = computed(() => {
  if (props.inputLoaded) return props.inputExpandedText ?? ''
  if (props.inputFailed) return t('taskView.failedToLoadPayload')
  const hasInlineInput = !!props.row.toolCall.input && Object.keys(props.row.toolCall.input).length > 0
  const inlineInput = hasInlineInput ? formatInput(props.row.toolCall) : ''
  if (inlineInput) return inlineInput
  if (props.row.toolCall.input_payload_id) return t('taskView.archivedInputPending')
  return t('taskView.noToolInputCaptured')
})
const outputDisplayText = computed(() => {
  if (props.outputLoaded) return props.outputExpandedText ?? ''
  if (props.outputFailed) return t('taskView.failedToLoadPayload')
  if (props.row.toolCall.output_preview !== undefined) return props.row.toolCall.output_preview
  if (props.row.toolCall.output !== null && props.row.toolCall.output !== undefined) return props.row.toolCall.output
  if (props.row.toolCall.output_payload_id) return t('taskView.archivedOutputPending')
  return t('taskView.noToolOutputCaptured')
})
</script>

<style scoped>
.event-item {
  border-bottom: 1px solid var(--n-border-color, rgba(128, 128, 128, 0.1));
  padding: 6px 0;
}
.event-header {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  min-height: 30px;
}
.event-icon {
  display: flex;
  align-items: center;
  flex-shrink: 0;
  width: 20px;
  padding-top: 2px;
}
.event-info {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 2px;
  overflow: hidden;
  min-width: 0;
}
.event-name {
  font-weight: 500;
  font-size: 13px;
  flex-shrink: 0;
}
.event-preview {
  display: block;
  max-width: 100%;
  font-size: 12px;
  line-height: 1.35;
  color: var(--n-text-color-3, #999);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  word-break: break-all;
}
.event-ts {
  font-size: 11px;
  color: var(--n-text-color-3, #999);
  flex-shrink: 0;
  font-family: var(--n-font-family-mono, monospace);
  margin-left: auto;
}
.event-collapse {
  width: calc(100% - 16px);
  margin: 8px 8px 8px 8px;
  --n-item-margin: 8px 0 0 0;
  --n-title-padding: 8px 0;
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
  overflow-wrap: break-word;
  line-height: 1.5;
}
.tool-pre--input {
  color: var(--n-text-color-2, #666);
}
.tool-pre--error {
  background: rgba(239, 68, 68, 0.08);
  color: #ef4444;
}
</style>
