<template>
  <n-card
    class="task-process-panel"
    :class="{ 'task-process-panel--running': taskStatus === 'running' }"
    :bordered="false"
  >
    <template #header>
      <div class="process-header">
        <span class="panel-title">{{ t('taskView.taskProcess') }}</span>
        <n-tag v-if="isActive" type="success" size="small" round :class="{ 'live-badge--pulse': isActive }">{{ t('taskView.realTime') }}</n-tag>
        <span v-if="showFollowupReplayHint" class="followup-replay-hint">{{ t('taskView.followupReplayHint') }}</span>
        <span v-if="isActive && elapsedDisplay" class="elapsed-time">{{ elapsedDisplay }}</span>
      </div>
    </template>

    <TaskProcessSystemInitBanner
      v-if="runtimeInfoEntry"
      :entry="runtimeInfoEntry"
      :container-id="props.task?.container_id ?? null"
      :container-name="props.task?.container_name ?? null"
    />

    <template v-if="!hasStructuredContent">
      <n-tabs v-model:value="activeTab" type="line" size="small" class="process-tabs">
        <n-tab-pane name="events" :tab="t('taskView.eventsTab')">
          <n-empty v-if="taskStatus === 'pending' || taskStatus === 'queued'" :description="t('taskView.taskNotStarted')" class="empty-state" />
          <n-empty v-else-if="!isActive && !terminalHtml" :description="t('taskView.noLogsAvailable')" class="empty-state" />
          <n-empty v-else :description="t('taskView.noProcessYet')" class="empty-state" />
        </n-tab-pane>
        <n-tab-pane name="raw" :tab="t('taskView.rawLogsTab')" :disabled="!terminalHtml && !props.task?.container_id">
          <TaskProcessRawPane ref="rawPaneRef" :terminal-html="terminalHtml" />
        </n-tab-pane>
      </n-tabs>
    </template>

    <template v-else>
      <n-tabs v-model:value="activeTab" type="line" size="small" class="process-tabs">
        <n-tab-pane name="events" :tab="t('taskView.eventsTab')">
          <div class="event-stream" ref="eventStreamRef">
            <template v-for="(row, index) in processRows" :key="row.event.id">
              <div :ref="(el) => { collapseRefs[index] = el as HTMLElement }">
                <TaskProcessTextRow
                  v-if="isTextRow(row)"
                  :row="row"
                  :expanded-text="getExpandedText(row.textEntry)"
                  :loading="hasTextPayloadLoading(row.textEntry)"
                  :show-content="shouldShowTextContent(row.textEntry)"
                  @collapse-change="(names) => onCollapseChange(names, index)"
                />
                <TaskProcessToolRow
                  v-else-if="isToolRow(row)"
                  :row="row"
                  :input-loaded="isPayloadLoaded(row.toolCall.input_payload_id ?? null)"
                  :output-loaded="isPayloadLoaded(row.toolCall.output_payload_id ?? null)"
                  :input-loading="isPayloadLoading(row.toolCall.input_payload_id ?? null)"
                  :output-loading="isPayloadLoading(row.toolCall.output_payload_id ?? null)"
                  :input-failed="hasPayloadLoadError(row.toolCall.input_payload_id ?? null)"
                  :output-failed="hasPayloadLoadError(row.toolCall.output_payload_id ?? null)"
                  :input-expanded-text="getExpandedPayloadText(row.toolCall.input_payload_id ?? null)"
                  :output-expanded-text="getExpandedPayloadText(row.toolCall.output_payload_id ?? null)"
                  @collapse-change="(names) => onCollapseChange(names, index)"
                />
              </div>
            </template>
          </div>
        </n-tab-pane>
        <n-tab-pane name="raw" :tab="t('taskView.rawLogsTab')" :disabled="!terminalHtml && !props.task?.container_id">
          <TaskProcessRawPane ref="rawPaneRef" :terminal-html="terminalHtml" />
        </n-tab-pane>
      </n-tabs>
    </template>

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
import { NCard, NIcon, NTag, NEmpty, NTabs, NTabPane, NButton } from 'naive-ui'
import { useI18n } from 'vue-i18n'
import { formatDurationMs } from '../utils/format'
import { ArrowDownCircleOutline } from '@vicons/ionicons5'
import type { TaskLog, Task } from '../api'
import TaskProcessSystemInitBanner from './task-process/TaskProcessSystemInitBanner.vue'
import TaskProcessRawPane from './task-process/TaskProcessRawPane.vue'
import TaskProcessTextRow from './task-process/TaskProcessTextRow.vue'
import TaskProcessToolRow from './task-process/TaskProcessToolRow.vue'
import { normalizeTaskProcessRows, parseSystemInitEntry, isTextRow, isToolRow, type ParsedTextEntry } from './task-process/taskProcessUtils'
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
const eventStreamRef = ref<HTMLElement | null>(null)
const rawPaneRef = ref<{ logContentRef: HTMLElement | null } | null>(null)
const logContentRef = computed(() => rawPaneRef.value?.logContentRef ?? null)
const activeTab = ref<'events' | 'raw'>('events')
const collapseRefs = ref<(HTMLElement | null)[]>([])
const autoScroll = ref(true)
const elapsedMs = ref(0)

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
let isProgrammaticScroll = false

const processRows = computed(() => normalizeTaskProcessRows(props.taskLogs))
const systemInitEntry = computed(() => parseSystemInitEntry(props.taskLogs))
const runtimeInfoEntry = computed(() => {
  if (systemInitEntry.value) return systemInitEntry.value
  if (props.task?.container_id) return { model: null, cwd: null }
  return null
})
const hasStructuredContent = computed(() => processRows.value.length > 0)
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
  if (expandedNames.length === 0) return

  nextTick(() => {
    const collapseEl = collapseRefs.value[index]
    if (collapseEl && typeof collapseEl.scrollIntoView === 'function') {
      collapseEl.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
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

  if (expandedNames.includes('detail') && row.textEntry.payloadId) {
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

function setProgrammaticScroll() {
  isProgrammaticScroll = true
  if (programmaticScrollTimer) clearTimeout(programmaticScrollTimer)
  programmaticScrollTimer = setTimeout(() => { isProgrammaticScroll = false }, 300)
}

function onEventStreamScroll() {
  if (isProgrammaticScroll || !eventStreamRef.value) return
  const el = eventStreamRef.value
  autoScroll.value = el.scrollHeight - el.scrollTop - el.clientHeight <= 50
}

function onLogContentScroll() {
  if (isProgrammaticScroll || !logContentRef.value) return
  const el = logContentRef.value
  autoScroll.value = el.scrollHeight - el.scrollTop - el.clientHeight <= 50
}

watch(eventStreamRef, (el, oldEl) => {
  oldEl?.removeEventListener('scroll', onEventStreamScroll)
  el?.addEventListener('scroll', onEventStreamScroll)
})

watch(logContentRef, (el, oldEl) => {
  oldEl?.removeEventListener('scroll', onLogContentScroll)
  el?.addEventListener('scroll', onLogContentScroll)
})

function scrollToLatest() {
  autoScroll.value = true
  setProgrammaticScroll()
  nextTick(() => {
    eventStreamRef.value?.scrollTo?.({ top: eventStreamRef.value.scrollHeight, behavior: 'smooth' })
    logContentRef.value?.scrollTo?.({ top: logContentRef.value.scrollHeight, behavior: 'smooth' })
  })
}

watch(processRows, async () => {
  if (!props.isActive || !autoScroll.value) return
  await nextTick()
  if (eventStreamRef.value) {
    setProgrammaticScroll()
    eventStreamRef.value.scrollTo?.({ top: eventStreamRef.value.scrollHeight, behavior: 'smooth' })
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
  eventStreamRef.value?.removeEventListener('scroll', onEventStreamScroll)
  logContentRef.value?.removeEventListener('scroll', onLogContentScroll)
  if (programmaticScrollTimer) clearTimeout(programmaticScrollTimer)
})

defineExpose({ onCollapseChange })
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
  gap: 8px;
  min-width: 0;
}
.followup-replay-hint {
  min-width: 0;
  color: var(--n-text-color-3, #6b7280);
  font-size: 12px;
  font-weight: 400;
  line-height: 1.4;
}
.elapsed-time {
  margin-left: auto;
  font-size: 12px;
  color: var(--n-text-color-3, #999);
  font-family: var(--n-font-family-mono, monospace);
  background: rgba(128, 128, 128, 0.08);
  padding: 2px 10px;
  border-radius: 10px;
}
.event-stream {
  display: flex;
  flex-direction: column;
  overflow-x: hidden;
  overflow-y: auto;
  min-width: 0;
  max-height: 600px;
  padding-right: 4px;
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
  margin: 8px 0 8px 28px;
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
.empty-state {
  padding: 24px 0;
}
.scroll-to-latest {
  position: absolute;
  bottom: 16px;
  right: 16px;
  z-index: 10;
}
</style>
