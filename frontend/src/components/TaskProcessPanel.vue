<template>
  <n-card
    class="task-process-panel"
    :class="{ 'task-process-panel--running': taskStatus === 'running' }"
    :bordered="false"
  >
    <template #header>
      <div class="process-header">
        <div class="process-header__meta">
          <span class="panel-title">{{ t('taskView.taskProcess') }}</span>
          <n-tag v-if="isActive" type="success" size="small" round :class="{ 'live-badge--pulse': isActive }">{{ t('taskView.realTime') }}</n-tag>
          <span v-if="showFollowupReplayHint" class="followup-replay-hint">{{ t('taskView.followupReplayHint') }}</span>
          <span v-if="isActive && elapsedDisplay" class="elapsed-time">{{ elapsedDisplay }}</span>
        </div>
        <n-tabs v-model:value="activeTab" type="segment" size="small" class="process-tabs process-tabs--header">
          <n-tab name="events">
            <span class="event-tab-label">
              <span>{{ t('taskView.eventsTab') }}</span>
              <n-badge class="event-count-badge" :value="eventStreamCount" :max="999" :show-zero="true" />
            </span>
          </n-tab>
          <n-tab name="raw" :disabled="isRawTabDisabled">{{ t('taskView.rawLogsTab') }}</n-tab>
        </n-tabs>
      </div>
    </template>

    <TaskProcessSystemInitBanner
      v-if="runtimeInfoEntry"
      :entry="runtimeInfoEntry"
      :container-id="props.task?.container_id ?? null"
      :container-name="props.task?.container_name ?? null"
    />

    <div class="process-content">
      <template v-if="activeTab === 'events'">
        <template v-if="!hasStructuredContent">
          <div class="process-content__pane">
            <n-empty v-if="taskStatus === 'pending' || taskStatus === 'queued'" :description="t('taskView.taskNotStarted')" class="empty-state" />
            <n-empty v-else-if="!isActive && !terminalHtml" :description="t('taskView.noLogsAvailable')" class="empty-state" />
            <n-empty v-else :description="t('taskView.noProcessYet')" class="empty-state" />
          </div>
        </template>
        <div v-else class="process-content__pane">
          <n-scrollbar
            class="event-stream-scrollbar"
            trigger="hover"
            ref="eventStreamRef"
            :content-style="{ paddingRight: '12px' }"
            @scroll="onEventStreamScroll"
          >
            <div class="event-stream">
              <template v-for="(row, index) in processRows" :key="row.event.id">
                <div :ref="(el) => { collapseRefs[index] = el as HTMLElement }">
                  <TaskProcessTextRow
                    v-if="isTextRow(row)"
                    :row="asTextRow(row)"
                    :expanded-text="getExpandedText(asTextRow(row).textEntry)"
                    :loading="hasTextPayloadLoading(asTextRow(row).textEntry)"
                    :show-content="shouldShowTextContent(asTextRow(row).textEntry)"
                    @collapse-change="(names) => onCollapseChange(names, index)"
                  />
                  <TaskProcessToolRow
                    v-else-if="isToolRow(row)"
                    :row="asToolRow(row)"
                    :input-loaded="isPayloadLoaded(asToolRow(row).toolCall.input_payload_id ?? null)"
                    :output-loaded="isPayloadLoaded(asToolRow(row).toolCall.output_payload_id ?? null)"
                    :input-loading="isPayloadLoading(asToolRow(row).toolCall.input_payload_id ?? null)"
                    :output-loading="isPayloadLoading(asToolRow(row).toolCall.output_payload_id ?? null)"
                    :input-failed="hasPayloadLoadError(asToolRow(row).toolCall.input_payload_id ?? null)"
                    :output-failed="hasPayloadLoadError(asToolRow(row).toolCall.output_payload_id ?? null)"
                    :input-expanded-text="getExpandedPayloadText(asToolRow(row).toolCall.input_payload_id ?? null)"
                    :output-expanded-text="getExpandedPayloadText(asToolRow(row).toolCall.output_payload_id ?? null)"
                    @collapse-change="(names) => onCollapseChange(names, index)"
                  />
                  <div v-else-if="isCompactRow(row)" class="context-compact-divider">
                    <span class="context-compact-label">{{ t('taskView.contextCompacted') }}</span>
                  </div>
                </div>
              </template>
            </div>
          </n-scrollbar>
        </div>
      </template>
      <div v-else class="process-content__pane process-content__pane--raw">
        <TaskProcessRawPane ref="rawPaneRef" :terminal-html="terminalHtml" />
      </div>
    </div>

    <div v-if="!autoScroll && isActive" class="scroll-to-latest">
      <n-button size="small" type="primary" @click="scrollToLatest">
        <template #icon><n-icon><ArrowDownCircleOutline /></n-icon></template>
        {{ t('taskView.scrollToLatest') }}
      </n-button>
    </div>
  </n-card>
</template>

<script setup lang="ts">
import { computed, ref, watch, nextTick, onBeforeUnmount } from 'vue'
import { NCard, NIcon, NTag, NEmpty, NTabs, NTab, NButton, NBadge, NScrollbar } from 'naive-ui'
import type { ScrollbarInst } from 'naive-ui'
import { useI18n } from 'vue-i18n'
import { formatDurationMs } from '../utils/format'
import { ArrowDownCircleOutline } from '@vicons/ionicons5'
import type { TaskLog, Task } from '../api'
import TaskProcessSystemInitBanner from './task-process/TaskProcessSystemInitBanner.vue'
import TaskProcessRawPane from './task-process/TaskProcessRawPane.vue'
import TaskProcessTextRow from './task-process/TaskProcessTextRow.vue'
import TaskProcessToolRow from './task-process/TaskProcessToolRow.vue'
import { normalizeTaskProcessRows, parseSystemInitEntry, isTextRow, isToolRow, isCompactRow, type NormalizedTextEventRow, type NormalizedToolEventRow, type NormalizedTaskProcessRow, type ParsedTextEntry } from './task-process/taskProcessUtils'
import { useTaskPayloadExpansion } from './task-process/useTaskPayloadExpansion'
import { parseUtcDate } from '../utils/datetime'

const props = withDefaults(defineProps<{
  task: Task | null
  taskLogs: TaskLog[]
  isActive: boolean
  terminalHtml: string
  taskStatus: string
  showFollowupReplayHint?: boolean
}>(), {
  taskLogs: () => [],
  showFollowupReplayHint: false,
})

const emit = defineEmits<{
  (e: 'raw-tab-open'): void
  (e: 'raw-tab-close'): void
}>()

const { t } = useI18n()
const eventStreamRef = ref<ScrollbarInst | null>(null)

// Typed constant to force TypeScript to pick the `{ position }` overload of scrollTo
const SCROLL_TO_BOTTOM: { position: 'top' | 'bottom'; behavior: ScrollBehavior } = { position: 'bottom', behavior: 'smooth' }
const rawPaneRef = ref<{ logContentRef: HTMLElement | null } | null>(null)
const logContentRef = computed(() => rawPaneRef.value?.logContentRef ?? null)
const activeTab = ref<'events' | 'raw'>('events')
const collapseRefs = ref<(HTMLElement | null)[]>([])
const autoScroll = ref(true)
const elapsedMs = ref(0)
const expandedRowIndex = ref<number | null>(null)

const {
  expandedPayloads,
  loadingPayloads,
  payloadLoadErrors,
  loadPayload,
  isPayloadLoading,
  isPayloadLoaded,
  getExpandedPayloadText,
} = useTaskPayloadExpansion()

let elapsedTimer: ReturnType<typeof setInterval> | null = null
let programmaticScrollTimer: ReturnType<typeof setTimeout> | null = null
let lastRowScrollTimer: ReturnType<typeof setTimeout> | null = null
let isProgrammaticScroll = false

const processRows = computed(() => normalizeTaskProcessRows(props.taskLogs))

// vue-tsc does not narrow the type inside v-if/v-else-if chains when there are 3+ branches,
// so we use explicit cast helpers that are safe because rendering is guarded by the matching v-if.
function asTextRow(row: NormalizedTaskProcessRow): NormalizedTextEventRow { return row as NormalizedTextEventRow }
function asToolRow(row: NormalizedTaskProcessRow): NormalizedToolEventRow { return row as NormalizedToolEventRow }
const systemInitEntry = computed(() => parseSystemInitEntry(props.taskLogs))
const runtimeInfoEntry = computed(() => {
  if (systemInitEntry.value) return systemInitEntry.value
  if (props.task?.container_id) return { model: null, cwd: null }
  return null
})
const hasStructuredContent = computed(() => processRows.value.length > 0)
const eventStreamCount = computed(() => processRows.value.filter(r => !isCompactRow(r)).length)
const isRawTabDisabled = computed(() => !props.terminalHtml && !props.task?.container_id)
const elapsedDisplay = computed(() => (!props.isActive || elapsedMs.value <= 0 ? '' : formatDurationMs(elapsedMs.value)))

function getExpandedText(entry: ParsedTextEntry): string {
  if (entry.payloadId) {
    if (payloadLoadErrors[entry.payloadId]) return t('taskView.failedToLoadPayload')
    return expandedPayloads.value[entry.payloadId] ?? ''
  }
  return entry.text
}

function hasTextPayloadLoading(entry: ParsedTextEntry): boolean {
  return entry.payloadId !== null && loadingPayloads.value.has(entry.payloadId)
}

function shouldShowTextContent(entry: ParsedTextEntry): boolean {
  return entry.payloadId === null || expandedPayloads.value[entry.payloadId] !== undefined || !!payloadLoadErrors[entry.payloadId]
}

function hasPayloadLoadError(payloadId: number | null): boolean {
  return payloadId !== null && !!payloadLoadErrors[payloadId]
}

function onCollapseChange(expandedNames: (string | number)[], index: number) {
  const isExpanding = expandedNames.length > 0
  expandedRowIndex.value = isExpanding ? index : null

  if (!isExpanding) return

  const isLastRow = index === processRows.value.length - 1

  nextTick(() => {
    if (isLastRow) {
      // Wait for the CSS grid expand animation (220ms) to finish, then scroll to bottom
      if (lastRowScrollTimer) clearTimeout(lastRowScrollTimer)
      lastRowScrollTimer = setTimeout(() => {
        if (eventStreamRef.value) {
          setProgrammaticScroll()
          eventStreamRef.value.scrollTo(SCROLL_TO_BOTTOM)
        }
      }, 260)
    } else {
      const collapseEl = collapseRefs.value[index]
      if (collapseEl && typeof collapseEl.scrollIntoView === 'function') {
        collapseEl.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
      }
    }
  })

  const row = processRows.value[index]
  if (!row) return

  const taskId = props.task?.id ?? 0
  if (row.kind === 'tool_call') {
    const inputPayloadId = row.toolCall.input_payload_id ?? null
    const outputPayloadId = row.toolCall.output_payload_id ?? null
    if (expandedNames.includes('input') && inputPayloadId) loadPayload(taskId, inputPayloadId)
    if (expandedNames.includes('output') && outputPayloadId) loadPayload(taskId, outputPayloadId)
    return
  }

  if (expandedNames.includes('detail') && isTextRow(row) && row.textEntry.payloadId) {
    loadPayload(taskId, row.textEntry.payloadId)
  }
}

function updateElapsed() {
  if (!props.task?.started_at) return
  try {
    const ms = Date.now() - parseUtcDate(props.task.started_at).getTime()
    elapsedMs.value = ms > 0 ? ms : 0
  } catch {
    elapsedMs.value = 0
  }
}

watch(() => props.isActive, (active) => {
  if (active) {
    updateElapsed()
    elapsedTimer = setInterval(updateElapsed, 1000)
  } else {
    if (elapsedTimer) {
      clearInterval(elapsedTimer)
      elapsedTimer = null
    }
    elapsedMs.value = 0
  }
}, { immediate: true })

watch(activeTab, (val) => {
  autoScroll.value = true
  if (val === 'raw') emit('raw-tab-open')
  else emit('raw-tab-close')
})

watch(isRawTabDisabled, (disabled) => {
  if (disabled && activeTab.value === 'raw') activeTab.value = 'events'
}, { immediate: true })

function setProgrammaticScroll() {
  isProgrammaticScroll = true
  if (programmaticScrollTimer) clearTimeout(programmaticScrollTimer)
  programmaticScrollTimer = setTimeout(() => { isProgrammaticScroll = false }, 300)
}

function onEventStreamScroll(e: Event) {
  if (isProgrammaticScroll) return
  const el = e.target as HTMLElement
  autoScroll.value = el.scrollHeight - el.scrollTop - el.clientHeight <= 50
}

function onLogContentScroll() {
  if (isProgrammaticScroll || !logContentRef.value) return
  const el = logContentRef.value
  autoScroll.value = el.scrollHeight - el.scrollTop - el.clientHeight <= 50
}

watch(logContentRef, (el, oldEl) => {
  oldEl?.removeEventListener('scroll', onLogContentScroll)
  el?.addEventListener('scroll', onLogContentScroll)
})

function scrollToLatest() {
  autoScroll.value = true
  setProgrammaticScroll()
  nextTick(() => {
    eventStreamRef.value?.scrollTo(SCROLL_TO_BOTTOM)
    logContentRef.value?.scrollTo?.({ top: logContentRef.value.scrollHeight, behavior: 'smooth' })
  })
}

watch(processRows, async () => {
  if (!props.isActive || !autoScroll.value) return
  await nextTick()
  if (eventStreamRef.value) {
    setProgrammaticScroll()
    eventStreamRef.value.scrollTo(SCROLL_TO_BOTTOM)
  }
})

// When payload content loads into an already-expanded last row, scroll to reveal it
watch(expandedPayloads, async () => {
  if (expandedRowIndex.value !== processRows.value.length - 1) return
  await nextTick()
  if (eventStreamRef.value) {
    setProgrammaticScroll()
    eventStreamRef.value.scrollTo(SCROLL_TO_BOTTOM)
  }
})

watch(() => props.terminalHtml, async () => {
  if (!props.isActive || !autoScroll.value) return
  await nextTick()
  if (logContentRef.value) {
    setProgrammaticScroll()
    logContentRef.value.scrollTo?.({ top: logContentRef.value.scrollHeight, behavior: 'smooth' })
  }
})

onBeforeUnmount(() => {
  if (elapsedTimer) clearInterval(elapsedTimer)
  logContentRef.value?.removeEventListener('scroll', onLogContentScroll)
  if (programmaticScrollTimer) clearTimeout(programmaticScrollTimer)
  if (lastRowScrollTimer) clearTimeout(lastRowScrollTimer)
})

defineExpose({ onCollapseChange, activeTab })
</script>

<style scoped>
.task-process-panel {
  position: relative;
  border-radius: var(--app-card-radius);
  overflow: hidden;
  min-width: 0;
}
.task-process-panel--running {
  border: 1px solid rgba(34, 197, 94, 0.28);
  animation: pulse-panel-glow 2.2s ease-in-out infinite;
}
.task-process-panel--running::before {
  content: '';
  position: absolute;
  inset: 0;
  pointer-events: none;
  border-radius: inherit;
  background: radial-gradient(circle at top right, rgba(74, 222, 128, 0.07), transparent 58%);
}
.panel-title {
  font-size: 18px;
  font-weight: 600;
}
.process-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: nowrap;
  min-width: 0;
}
.process-header__meta {
  display: flex;
  flex: 1 1 0;
  align-items: center;
  gap: 8px;
  min-width: 0;
}
.followup-replay-hint {
  min-width: 0;
  color: var(--n-text-color-3, #6b7280);
  font-size: 12px;
  font-weight: 400;
  line-height: 1.4;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.elapsed-time {
  flex: 0 0 auto;
  font-size: 12px;
  color: var(--n-text-color-3, #999);
  font-family: var(--n-font-family-mono, monospace);
  background: rgba(128, 128, 128, 0.08);
  padding: 2px 10px;
  border-radius: 10px;
}
.process-content {
  height: clamp(320px, 52vh, 520px);
  min-width: 0;
}
.process-content__pane {
  display: flex;
  flex-direction: column;
  min-width: 0;
  height: 100%;
}
.event-stream-scrollbar {
  flex: 1 1 auto;
  min-height: 0;
  height: 100%;
}

.event-stream {
  display: flex;
  flex-direction: column;
  min-width: 0;
}
.event-item {
  border-bottom: 1px solid var(--n-border-color, rgba(128, 128, 128, 0.1));
  padding: 6px 0;
}
.event-item:last-child {
  border-bottom: none;
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
  overflow: hidden;
  color: var(--n-text-color-3, #999);
  font-size: 12px;
  line-height: 1.35;
  text-overflow: ellipsis;
  white-space: nowrap;
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
.live-badge--pulse {
  animation: pulse-badge 2s ease-in-out infinite;
}
@keyframes pulse-panel-glow {
  0%,
  100% {
    box-shadow:
      0 0 0 1px rgba(34, 197, 94, 0.14),
      0 0 18px rgba(34, 197, 94, 0.12),
      0 0 34px rgba(16, 185, 129, 0.1);
  }
  50% {
    box-shadow:
      0 0 0 1px rgba(74, 222, 128, 0.3),
      0 0 26px rgba(74, 222, 128, 0.22),
      0 0 52px rgba(16, 185, 129, 0.18);
  }
}
@keyframes pulse-badge {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.4; }
}
.process-tabs {
  margin-top: 0;
}
.process-tabs--header {
  flex: 0 0 264px;
  width: 264px;
  min-width: 0;
}
:deep(.process-tabs .n-tabs-rail) {
  border-radius: 14px;
}
:deep(.process-tabs .n-tabs-capsule) {
  border-radius: 12px;
}
.event-tab-label {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
}
.event-count-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  line-height: 1;
}
:deep(.event-count-badge .n-badge-sup) {
  position: static;
  transform: none;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 20px;
  height: 18px;
  padding: 0 6px;
  border-radius: 999px;
  border: 1px solid rgba(100, 116, 139, 0.22);
  background: rgba(100, 116, 139, 0.14);
  box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.28);
  color: #475569;
  font-size: 11px;
  font-weight: 700;
  line-height: 1;
}
:deep(.process-content .log-content) {
  flex: 1 1 auto;
  width: 100%;
  height: 100%;
  max-height: none;
  box-sizing: border-box;
}
.empty-state {
  display: flex;
  flex: 1 1 auto;
  align-items: center;
  justify-content: center;
  padding: 24px 0;
}
.context-compact-divider {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 0;
  margin: 2px 0;
  color: var(--n-text-color-3, #94a3b8);
  font-size: 11px;
  font-weight: 500;
  letter-spacing: 0.04em;
  text-transform: uppercase;
}
.context-compact-divider::before,
.context-compact-divider::after {
  content: '';
  flex: 1;
  height: 1px;
  background: var(--n-border-color, rgba(128, 128, 128, 0.15));
}
.context-compact-label {
  flex-shrink: 0;
  padding: 0 4px;
}
.scroll-to-latest {
  position: absolute;
  bottom: 16px;
  right: 16px;
  z-index: 10;
}
</style>
