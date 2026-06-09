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
          :class="{ 'tool-badge--active': showDetail, 'tool-badge--loading': isDetailBusy }"
          :disabled="isDetailBusy"
          @click="toggleDetail"
        >
          <span v-if="isDetailBusy" class="badge-spin-ring"></span>
          <n-icon v-else size="10" class="badge-chevron" :class="{ 'badge-chevron--open': showDetail }">
            <ChevronForward />
          </n-icon>
          {{ t('taskView.fullText') }}
        </button>
      </div>
      <div class="tool-expand-track" :class="{ 'tool-expand-track--open': showDetail }">
        <div class="tool-expand-body">
          <div class="tool-content">
            <div
              v-if="showContent && renderedHtml"
              class="event-content markdown-content"
              :class="[
                'event-content--fadein',
                { 'event-content--thinking': row.kind === 'thinking' }
              ]"
              v-html="renderedHtml"
            ></div>
            <div v-else-if="showContent && !trimmedExpandedText" class="event-content event-content--placeholder">{{ t('taskView.emptyContent') }}</div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
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
const renderedHtml = ref('')
const renderedSource = ref('')

const trimmedExpandedText = computed(() => props.expandedText.trim())
// Busy only while waiting for the API payload — rendering is now synchronous
const isDetailBusy = computed(() => showDetail.value && props.loading)

function syncRender() {
  const text = trimmedExpandedText.value
  if (!text) {
    renderedHtml.value = ''
    renderedSource.value = ''
    return
  }
  if (renderedSource.value === text) return
  renderedHtml.value = renderMarkdown(text)
  renderedSource.value = text
}

// Pre-render eagerly whenever text is available, regardless of open/close state.
// markdown-it is synchronous and fast (<1 ms for typical sizes), so no RAF needed.
watch([trimmedExpandedText, () => props.showContent], ([text, ready]) => {
  if (ready && text) syncRender()
  else if (!text) {
    renderedHtml.value = ''
    renderedSource.value = ''
  }
}, { immediate: true })

function toggleDetail() {
  if (!showDetail.value) {
    // Ensure content is rendered before the expand animation starts.
    if (props.showContent && trimmedExpandedText.value) syncRender()
  }
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

onBeforeUnmount(() => {
  renderedHtml.value = ''
  renderedSource.value = ''
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
/* CSS grid expand trick: zero layout-reflow height animation */
.tool-expand-track {
  display: grid;
  grid-template-rows: 0fr;
  transition: grid-template-rows 0.22s ease;
}
.tool-expand-track--open {
  grid-template-rows: 1fr;
}
.tool-expand-body {
  overflow: hidden;
  min-height: 0;
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
/* markdown-it rendered content */
.markdown-content :deep(p) {
  margin: 0 0 0.6em;
}
.markdown-content :deep(p:last-child) {
  margin-bottom: 0;
}
.markdown-content :deep(h1),
.markdown-content :deep(h2),
.markdown-content :deep(h3),
.markdown-content :deep(h4) {
  margin: 0.8em 0 0.4em;
  font-weight: 600;
  line-height: 1.3;
}
.markdown-content :deep(h1) { font-size: 1.25em; }
.markdown-content :deep(h2) { font-size: 1.1em; }
.markdown-content :deep(h3) { font-size: 1em; }
.markdown-content :deep(ul),
.markdown-content :deep(ol) {
  margin: 0.4em 0;
  padding-left: 1.5em;
}
.markdown-content :deep(li) {
  margin: 0.15em 0;
}
.markdown-content :deep(blockquote) {
  margin: 0.5em 0;
  padding: 0.2em 0.8em;
  border-left: 3px solid var(--n-border-color, rgba(128,128,128,0.35));
  color: var(--n-text-color-3, #888);
}
.markdown-content :deep(a) {
  color: var(--n-primary-color, #18a058);
  text-decoration: none;
}
.markdown-content :deep(a:hover) {
  text-decoration: underline;
}
/* inline code */
.markdown-content :deep(code) {
  font-family: var(--n-font-family-mono, monospace);
  font-size: 0.88em;
  background: rgba(128, 128, 128, 0.12);
  border-radius: 3px;
  padding: 0.1em 0.35em;
}
/* fenced code blocks */
.markdown-content :deep(pre.md-code-block) {
  margin: 0.5em 0;
  padding: 10px 12px;
  background: rgba(0, 0, 0, 0.06);
  border-radius: 5px;
  overflow-x: auto;
  font-family: var(--n-font-family-mono, monospace);
  font-size: 0.85em;
  line-height: 1.55;
  white-space: pre;
}
.markdown-content :deep(pre.md-code-block code) {
  background: none;
  padding: 0;
  border-radius: 0;
  font-size: inherit;
  color: inherit;
}
/* highlight.js token colors (minimal, theme-agnostic) */
.markdown-content :deep(.hljs-keyword) { color: #c678dd; }
.markdown-content :deep(.hljs-string) { color: #98c379; }
.markdown-content :deep(.hljs-number) { color: #d19a66; }
.markdown-content :deep(.hljs-comment) { color: #5c6370; font-style: italic; }
.markdown-content :deep(.hljs-function),
.markdown-content :deep(.hljs-title) { color: #61afef; }
.markdown-content :deep(.hljs-variable),
.markdown-content :deep(.hljs-attr) { color: #e06c75; }
.markdown-content :deep(.hljs-built_in) { color: #56b6c2; }
.markdown-content :deep(.hljs-literal) { color: #d19a66; }
/* tables */
.markdown-content :deep(table) {
  width: 100%;
  border-collapse: collapse;
  margin: 0.6em 0;
  font-size: 0.9em;
  overflow-x: auto;
  display: block;
}
.markdown-content :deep(th),
.markdown-content :deep(td) {
  border: 1px solid var(--n-border-color, rgba(128, 128, 128, 0.25));
  padding: 5px 10px;
  text-align: left;
}
.markdown-content :deep(th) {
  background: rgba(128, 128, 128, 0.08);
  font-weight: 600;
}
.markdown-content :deep(tr:nth-child(even) td) {
  background: rgba(128, 128, 128, 0.04);
}
.markdown-content :deep(hr) {
  border: none;
  border-top: 1px solid var(--n-border-color, rgba(128, 128, 128, 0.2));
  margin: 0.8em 0;
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
/* Fade-in for content that arrives after the panel is already open (payload case) */
@keyframes content-fadein {
  from { opacity: 0; }
  to   { opacity: 1; }
}
.event-content--fadein {
  animation: content-fadein 0.18s ease;
}
</style>
