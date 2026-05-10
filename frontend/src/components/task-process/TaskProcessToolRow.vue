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
    <div v-if="hasDetailedToolInput || hasToolEventOutput" class="tool-sections">
      <div class="tool-badge-row">
        <button
          v-if="hasDetailedToolInput"
          class="tool-badge"
          :class="{ 'tool-badge--active': showInput, 'tool-badge--loading': showInput && inputLoading }"
          :disabled="showInput && inputLoading"
          @click="toggleInput"
        >
          <span v-if="showInput && inputLoading" class="badge-spin-ring"></span>
          <n-icon v-else size="10" class="badge-chevron" :class="{ 'badge-chevron--open': showInput }">
            <ChevronForward />
          </n-icon>
          {{ t('taskView.toolInput') }}
        </button>
        <button
          v-if="hasToolEventOutput"
          class="tool-badge"
          :class="{ 'tool-badge--active': showOutput, 'tool-badge--error': row.toolCall.error, 'tool-badge--loading': showOutput && outputLoading }"
          :disabled="showOutput && outputLoading"
          @click="toggleOutput"
        >
          <span v-if="showOutput && outputLoading" class="badge-spin-ring"></span>
          <n-icon v-else size="10" class="badge-chevron" :class="{ 'badge-chevron--open': showOutput }">
            <ChevronForward />
          </n-icon>
          {{ t('taskView.toolOutput') }}
        </button>
      </div>
      <div ref="contentWrapper" class="tool-content-outer">
        <Transition
          name="tool-expand"
          @before-leave="onBeforeLeave"
          @leave="onLeave"
          @after-leave="onAfterLeave"
          @enter="onEnter"
          @after-enter="onAfterEnter"
        >
          <div v-if="showInput && hasDetailedToolInput" key="input" class="tool-content">
            <pre class="tool-pre tool-pre--input" :class="{ 'tool-pre--placeholder': inputIsPlaceholder }">{{ inputDisplayText }}</pre>
          </div>
          <div v-else-if="showOutput && hasToolEventOutput" key="output" class="tool-content">
            <pre class="tool-pre" :class="{ 'tool-pre--error': row.toolCall.error, 'tool-pre--placeholder': outputIsPlaceholder }">{{ outputDisplayText }}</pre>
          </div>
        </Transition>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { NIcon, NTag } from 'naive-ui'
import { ChevronForward } from '@vicons/ionicons5'
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

const showInput = ref(false)
const showOutput = ref(false)
const contentWrapper = ref<HTMLElement>()

function onBeforeLeave() {
  // Lock wrapper height before entering element is inserted
  const w = contentWrapper.value
  if (!w) return
  w.style.height = w.offsetHeight + 'px'
  w.style.overflow = 'hidden'
}

function onLeave(el: Element) {
  // Pull leaving element out of flow so entering element drives layout
  const h = el as HTMLElement
  h.style.position = 'absolute'
  h.style.width = '100%'
  h.style.top = '0'
  h.style.left = '0'
}

function onAfterLeave(el: Element) {
  const h = el as HTMLElement
  h.style.cssText = ''
  const w = contentWrapper.value
  if (!w) return
  if (!showInput.value && !showOutput.value) {
    // Closing: animate wrapper height to 0
    requestAnimationFrame(() => {
      w.style.transition = 'height 0.2s ease'
      w.style.height = '0'
    })
    setTimeout(() => {
      if (contentWrapper.value) contentWrapper.value.style.cssText = ''
    }, 220)
  }
}

function onEnter(el: Element) {
  const w = contentWrapper.value
  if (!w) return
  const newHeight = (el as HTMLElement).scrollHeight
  if (!w.style.height) {
    // Opening from nothing
    w.style.overflow = 'hidden'
    w.style.height = '0'
  }
  requestAnimationFrame(() => {
    w.style.transition = 'height 0.25s ease'
    w.style.height = newHeight + 'px'
  })
}

function onAfterEnter() {
  const w = contentWrapper.value
  if (!w) return
  w.style.cssText = ''
}

function emitCollapseChange() {
  const names: string[] = []
  if (showInput.value) names.push('input')
  if (showOutput.value) names.push('output')
  emit('collapse-change', names)
}

function toggleInput() {
  showInput.value = !showInput.value
  if (showInput.value) showOutput.value = false
  emitCollapseChange()
}

function toggleOutput() {
  showOutput.value = !showOutput.value
  if (showOutput.value) showInput.value = false
  emitCollapseChange()
}

const summary = computed(() => getInputSummary(props.row.toolCall))
const hasDetailedToolInput = computed(() => hasDetailedInput(props.row.toolCall))
const hasToolEventOutput = computed(() => props.row.toolCall.output !== null || !!props.row.toolCall.output_payload_id || !!props.row.toolCall.output_preview)
const inputDisplayText = computed(() => {
  if (props.inputLoaded) {
    const text = (props.inputExpandedText ?? '').trim()
    return text || t('taskView.emptyContent')
  }
  if (props.inputFailed) return t('taskView.failedToLoadPayload')
  // While fetching the archived payload, show a loading message instead of stale preview
  if (props.inputLoading) return t('taskView.archivedInputPending')
  const hasInlineInput = !!props.row.toolCall.input && Object.keys(props.row.toolCall.input).length > 0
  const inlineInput = hasInlineInput ? formatInput(props.row.toolCall).trim() : ''
  if (inlineInput) return inlineInput
  if (props.row.toolCall.input_payload_id) return t('taskView.archivedInputPending')
  return t('taskView.noToolInputCaptured')
})
const outputDisplayText = computed(() => {
  if (props.outputLoaded) {
    const text = (props.outputExpandedText ?? '').trim()
    return text || t('taskView.emptyContent')
  }
  if (props.outputFailed) return t('taskView.failedToLoadPayload')
  // While fetching the archived payload, show a loading message instead of stale preview
  if (props.outputLoading) return t('taskView.archivedOutputPending')
  // No payload — inline content is the real data, show it directly
  if (props.row.toolCall.output_preview !== undefined) {
    const preview = props.row.toolCall.output_preview?.trim() ?? ''
    if (preview) return preview
  }
  if (props.row.toolCall.output !== null && props.row.toolCall.output !== undefined) {
    const text = props.row.toolCall.output.trim()
    if (text) return text
  }
  if (props.row.toolCall.output_payload_id) return t('taskView.archivedOutputPending')
  return t('taskView.noToolOutputCaptured')
})
const inputIsPlaceholder = computed(() => {
  if (props.inputLoaded) return !(props.inputExpandedText ?? '').trim()
  if (props.inputFailed) return false
  if (props.inputLoading) return true
  // No payload — inline content is real, only treat as placeholder if there's nothing to show
  if (!props.row.toolCall.input_payload_id) {
    const hasInlineInput = !!props.row.toolCall.input && Object.keys(props.row.toolCall.input).length > 0
    return !hasInlineInput
  }
  return false
})
const outputIsPlaceholder = computed(() => {
  if (props.outputLoaded) return !(props.outputExpandedText ?? '').trim()
  if (props.outputFailed) return false
  if (props.outputLoading) return true
  // No payload — inline content is real, only treat as placeholder if there's nothing to show
  if (!props.row.toolCall.output_payload_id) {
    const hasInlineContent =
      !!(props.row.toolCall.output_preview?.trim()) ||
      (props.row.toolCall.output !== null &&
        props.row.toolCall.output !== undefined &&
        !!(props.row.toolCall.output.trim()))
    return !hasInlineContent
  }
  return false
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
.tool-badge--error.tool-badge--active {
  color: #ef4444;
  border-color: #ef4444;
  background: rgba(239, 68, 68, 0.05);
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
.tool-content-outer {
  position: relative;
}
.tool-content {
  margin-top: 6px;
}
.tool-expand-enter-active,
.tool-expand-leave-active {
  transition: opacity 0.08s ease;
}
.tool-expand-enter-from,
.tool-expand-leave-to {
  opacity: 0;
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
.tool-pre--placeholder {
  font-style: italic;
  opacity: 0.4;
}
</style>
