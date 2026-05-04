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
        <pre v-if="inputLoaded" class="tool-pre">{{ inputExpandedText }}</pre>
        <n-spin v-else-if="inputLoading" size="small" />
        <pre v-else class="tool-pre tool-pre--input">{{ formatInput(row.toolCall) }}</pre>
      </n-collapse-item>
      <n-collapse-item v-if="hasToolEventOutput" name="output">
        <template #header>
          <span class="tool-detail-label">{{ t('taskView.toolOutput') }}</span>
        </template>
        <pre v-if="outputLoaded" class="tool-pre" :class="{ 'tool-pre--error': row.toolCall.error }">{{ outputExpandedText }}</pre>
        <n-spin v-else-if="outputLoading" size="small" />
        <pre v-else class="tool-pre" :class="{ 'tool-pre--error': row.toolCall.error }">{{ row.toolCall.output_preview ?? row.toolCall.output ?? '' }}</pre>
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
  inputExpandedText?: string
  outputExpandedText?: string
}>()

const emit = defineEmits<{
  (e: 'collapse-change', names: (string | number)[]): void
}>()

const { t } = useI18n()

const summary = computed(() => getInputSummary(props.row.toolCall))
const hasDetailedToolInput = computed(() => hasDetailedInput(props.row.toolCall))
const hasToolEventOutput = computed(() => props.row.toolCall.output !== null || !!props.row.toolCall.output_payload_id)
</script>

<style scoped>
.event-item {
  border-bottom: 1px solid var(--n-border-color, rgba(128, 128, 128, 0.1));
  padding: 6px 0;
}
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
  margin: 8px 0 8px 28px;
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
</style>
