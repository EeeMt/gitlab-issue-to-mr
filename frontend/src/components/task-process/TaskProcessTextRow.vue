<template>
  <div class="event-item" :class="row.kind === 'thinking' ? 'event-item--thinking' : 'event-item--assistant'">
    <div class="event-header">
      <div class="event-icon" :style="{ color: row.kind === 'thinking' ? '#888' : '#0284c7' }">
        <n-icon size="15"><component :is="row.kind === 'thinking' ? BulbOutline : ChatboxOutline" /></n-icon>
      </div>
      <div class="event-info">
        <span class="event-name">{{ row.kind === 'thinking' ? t('taskView.thinkingLabel') : t('taskView.assistantLabel') }}</span>
        <span v-if="preview" class="event-preview">{{ preview }}</span>
      </div>
      <span class="event-ts">{{ formatTimestamp(row.event.created_at) }}</span>
    </div>
    <n-collapse class="event-collapse" @update:expanded-names="(names) => emit('collapse-change', names)">
      <n-collapse-item name="detail">
        <template #header>
          <span class="tool-detail-label">{{ t('taskView.fullText') }}</span>
        </template>
        <n-spin v-if="loading" size="small" />
        <div v-else-if="showContent" class="event-content markdown-content" :class="{ 'event-content--thinking': row.kind === 'thinking' }" v-html="renderMarkdown(expandedText)"></div>
      </n-collapse-item>
    </n-collapse>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { NCollapse, NCollapseItem, NIcon, NSpin } from 'naive-ui'
import { BulbOutline, ChatboxOutline } from '@vicons/ionicons5'
import { useI18n } from 'vue-i18n'
import { formatTimestamp, renderMarkdown, type NormalizedTextEventRow } from './taskProcessUtils'

const props = defineProps<{
  row: NormalizedTextEventRow
  expandedText: string
  loading: boolean
  showContent: boolean
}>()

const emit = defineEmits<{
  (e: 'collapse-change', names: (string | number)[]): void
}>()

const { t } = useI18n()

const preview = computed(() => {
  const entry = props.row.textEntry
  if (entry.text) return entry.text.slice(0, 120)
  if (entry.payloadId && entry.charCount) return `${t('taskView.fullText')} (${entry.charCount})`
  if (entry.payloadId) return t('taskView.fullText')
  return ''
})
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
.event-content--thinking {
  font-size: 12px;
  color: var(--n-text-color-3, #888);
  font-style: italic;
}
.tool-detail-label {
  font-size: 11px;
  color: var(--n-text-color-3, #999);
}
</style>
