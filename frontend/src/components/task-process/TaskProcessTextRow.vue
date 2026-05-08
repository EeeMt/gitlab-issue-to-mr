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
  if (entry.preview) {
    return entry.truncated ? entry.preview + '…' : entry.preview
  }
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
.event-content {
  margin: 0;
  padding: 8px;
  font-size: 13px;
  line-height: 1.65;
  white-space: pre-wrap;
  overflow-wrap: break-word;
  color: var(--n-text-color-2);
  font-family: inherit;
  background: var(--n-color-embedded, rgba(128, 128, 128, 0.05));
  border-radius: 4px;
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
