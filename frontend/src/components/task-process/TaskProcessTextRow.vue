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
    <div class="tool-sections">
      <div class="tool-badge-row">
        <button
          class="tool-badge"
          :class="{ 'tool-badge--active': showDetail, 'tool-badge--loading': showDetail && loading }"
          :disabled="showDetail && loading"
          @click="toggleDetail"
        >
          <span v-if="showDetail && loading" class="badge-spin-ring"></span>
          <n-icon v-else size="10" class="badge-chevron" :class="{ 'badge-chevron--open': showDetail }">
            <ChevronForward />
          </n-icon>
          {{ t('taskView.fullText') }}
        </button>
      </div>
      <Transition
        name="tool-expand"
        @enter="onExpandEnter"
        @after-enter="onExpandAfterEnter"
        @leave="onExpandLeave"
        @after-leave="onExpandAfterLeave"
      >
        <div v-if="showDetail" class="tool-content">
          <div v-if="showContent && expandedText.trim()" class="event-content markdown-content" :class="{ 'event-content--thinking': row.kind === 'thinking' }" v-html="renderMarkdown(expandedText.trim())"></div>
          <div v-else-if="showContent" class="event-content event-content--placeholder">{{ t('taskView.emptyContent') }}</div>
        </div>
      </Transition>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { NIcon } from 'naive-ui'
import { BulbOutline, ChatboxOutline, ChevronForward } from '@vicons/ionicons5'
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

const showDetail = ref(false)

function onExpandEnter(el: Element) {
  const h = el as HTMLElement
  const naturalHeight = h.scrollHeight
  h.style.height = '0'
  h.style.overflow = 'hidden'
  requestAnimationFrame(() => {
    h.style.height = naturalHeight + 'px'
  })
}
function onExpandAfterEnter(el: Element) {
  const h = el as HTMLElement
  h.style.height = ''
  h.style.overflow = ''
}
function onExpandLeave(el: Element) {
  const h = el as HTMLElement
  h.style.height = h.scrollHeight + 'px'
  h.style.overflow = 'hidden'
  requestAnimationFrame(() => {
    h.style.height = '0'
  })
}
function onExpandAfterLeave(el: Element) {
  const h = el as HTMLElement
  h.style.height = ''
  h.style.overflow = ''
}

function toggleDetail() {
  showDetail.value = !showDetail.value
  emit('collapse-change', showDetail.value ? ['detail'] : [])
}

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
.tool-sections {
  margin: 4px 8px 2px 28px;
}
.tool-badge-row {
  display: flex;
  gap: 6px;
}
.tool-badge {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  padding: 2px 7px 2px 5px;
  font-size: 11px;
  color: var(--n-text-color-3, #999);
  background: transparent;
  border: 1px solid var(--n-border-color, rgba(128, 128, 128, 0.2));
  border-radius: 3px;
  cursor: pointer;
  transition: color 0.15s, border-color 0.15s, background 0.15s;
  font-family: inherit;
  line-height: 1.6;
}
.tool-badge:hover {
  color: var(--n-text-color, inherit);
  border-color: rgba(128, 128, 128, 0.4);
}
.tool-badge--active {
  color: var(--n-primary-color, #18a058);
  border-color: var(--n-primary-color, #18a058);
  background: rgba(24, 160, 88, 0.05);
}
.badge-chevron {
  transition: transform 0.15s ease;
  flex-shrink: 0;
}
.badge-chevron--open {
  transform: rotate(90deg);
}
.tool-badge:disabled,
.tool-badge--loading {
  cursor: not-allowed;
  pointer-events: none;
}
.badge-spin-ring {
  display: inline-block;
  width: 9px;
  height: 9px;
  border-radius: 50%;
  border: 1.5px solid currentColor;
  border-top-color: transparent;
  flex-shrink: 0;
  animation: badge-rotate 0.7s linear infinite;
}
@keyframes badge-rotate {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}
.tool-content {
  margin-top: 6px;
}
.tool-expand-enter-active {
  transition: opacity 0.2s ease, height 0.25s ease;
  overflow: hidden;
}
.tool-expand-leave-active {
  transition: opacity 0.15s ease, height 0.2s ease;
  overflow: hidden;
}
.tool-expand-enter-from,
.tool-expand-leave-to {
  opacity: 0;
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
.event-content--placeholder {
  font-style: italic;
  opacity: 0.4;
  padding: 4px 0;
}
</style>
