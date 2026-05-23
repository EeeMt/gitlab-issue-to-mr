<template>
  <div class="task-view" data-testid="task-view-page">
    <n-space vertical :size="16">
      <PageHeader
        data-testid="task-view-header"
        root-class="task-view__hero"
        subtitle-class="task-view__subtitle"
        actions-class="task-view__actions"
        :subtitle="t('taskView.subtitle')"
      >
        <template #title>
          <h2 class="task-view__title">{{ t('taskView.title', { id: taskId }) }}</h2>
          <n-tag v-if="task" :type="statusColors[task.status]" round>{{ t(`status.${task.status}`) }}</n-tag>
        </template>
        <template #actions>
          <div class="task-actions task-actions--header" data-testid="task-actions">
            <div class="task-actions__toolbar">
              <n-button
                v-if="task && ['pending', 'queued', 'running'].includes(task.status)"
                class="task-actions__command task-actions__command--danger"
                type="error"
                secondary
                strong
                @click="handleCancel"
                :title="t('taskView.cancelTaskDescription')"
                :loading="actionLoading"
                :disabled="!canManageTask"
              >
                <template #icon><n-icon :component="CloseCircleOutline" /></template>
                {{ t('common.cancel') }}
              </n-button>

              <div
                v-if="task && ['failed', 'cancelled'].includes(task.status) && activeRetryTask"
                class="task-actions__linked-task"
              >
                <span>{{ t('taskView.retryExists') }}</span>
                <n-button
                  type="primary"
                  text
                  @click="router.push(`/tasks/${activeRetryTask.id}`)"
                >
                  <template #icon><n-icon :component="OpenOutline" /></template>
                  Task #{{ activeRetryTask.id }}
                </n-button>
              </div>

              <n-button
                v-if="task && ['failed', 'cancelled'].includes(task.status) && !activeRetryTask"
                class="task-actions__command task-actions__command--retry"
                type="warning"
                secondary
                strong
                @click="handleRetry"
                :title="t('taskView.retryTaskDescription')"
                :loading="actionLoading"
                :disabled="!canManageTask"
              >
                <template #icon><n-icon :component="RefreshOutline" /></template>
                {{ t('common.retry') }}
              </n-button>

              <n-button
                v-if="task && ['failed', 'cancelled'].includes(task.status) && !activeRetryTask"
                class="task-actions__command task-actions__command--primary"
                :class="{ 'task-actions__command--active': showScheduleDrawer }"
                type="info"
                secondary
                strong
                @click="openScheduleDrawer()"
                :title="t('taskView.retryWithScheduleDescription')"
                :disabled="!canManageTask"
              >
                <template #icon><n-icon :component="CalendarOutline" /></template>
                {{ t('taskView.retryWithSchedule') }}
              </n-button>

              <n-button
                v-if="task && canReschedule"
                class="task-actions__command task-actions__command--primary"
                type="info"
                secondary
                strong
                @click="showRescheduleDrawer = true"
                :title="t('taskView.rescheduleTaskDescription')"
                :disabled="!canManageTask"
              >
                <template #icon><n-icon :component="TimeOutline" /></template>
                {{ t('taskView.rescheduleTask') }}
              </n-button>

              <n-button
                v-if="task && task.status === 'pending'"
                class="task-actions__command task-actions__command--primary"
                type="info"
                secondary
                strong
                @click="handleExecute"
                :title="t('taskView.executeNowDescription')"
                :loading="actionLoading"
                :disabled="!canManageTask"
              >
                <template #icon><n-icon :component="PlayOutline" /></template>
                {{ t('common.execute') }}
              </n-button>

              <n-button
                v-if="task && ['pending', 'queued'].includes(task.status)"
                class="task-actions__command task-actions__command--neutral"
                type="default"
                secondary
                strong
                @click="showEditDrawer = true"
                :disabled="!canManageTask"
                :title="t('taskView.editTask')"
              >
                <template #icon><n-icon :component="CreateOutline" /></template>
                {{ t('taskView.editTask') }}
              </n-button>

              <n-button
                v-if="archiveMetadata"
                class="task-actions__command task-actions__command--neutral"
                type="primary"
                secondary
                strong
                :disabled="!archiveMetadata.file_exists"
                :title="archiveMetadata.file_exists ? t('taskView.runtimeArchiveDescription') : t('taskView.archiveFileExpiredDescription')"
                @click="handleDownloadArchive"
                :loading="archiveDownloadLoading"
              >
                <template #icon><n-icon :component="DownloadOutline" /></template>
                {{ t('taskView.downloadRuntimeArchive') }}
              </n-button>

              <span v-if="task && !hasActions" class="task-actions__empty task-actions__empty--header">
                {{ t('taskView.noManualAction') }}
              </span>

              <n-button
                class="task-actions__command task-actions__command--neutral task-actions__command--refresh"
                secondary
                strong
                @click="refreshTask"
                :loading="loading"
              >
                <template #icon><n-icon :component="RefreshOutline" /></template>
                {{ t('common.refresh') }}
              </n-button>
            </div>
          </div>
        </template>
      </PageHeader>

      <n-spin :show="initialLoading">
        <div class="task-view__content">
          <!-- Top row: Metadata Panel + User Prompt side-by-side -->
          <n-grid :cols="task?.user_prompt ? (isMobile ? 1 : 2) : 1" :x-gap="16" :y-gap="16">
            <n-gi>
              <TaskMetadataPanel v-if="task" :task="task" />
            </n-gi>
            <n-gi v-if="task?.user_prompt">
              <n-card class="task-card task-card--equal" :bordered="false" data-testid="task-prompt-card">
                <template #header>
                  <div class="task-card__header">
                    <div class="task-card__title">{{ t('taskView.userPrompt') }}</div>
                  </div>
                </template>
                <div class="task-prompt-wrap">
                  <n-scrollbar trigger="hover" style="max-height: 320px">
                    <div class="task-prompt-content markdown-content" v-html="renderedUserPrompt"></div>
                  </n-scrollbar>
                </div>
              </n-card>
            </n-gi>
          </n-grid>

          <!-- Action detail panel: only shown when an action needs extra context or inline inputs. -->
          <n-card v-if="hasActionDetails" class="task-card task-card--actions" :bordered="false" data-testid="task-actions-card">
            <div class="task-actions task-actions--details">
              <div v-if="hasActions && !canManageTask" class="task-actions__permission-note">
                {{ t('taskView.actionPermissionHint') }}
              </div>

              <div
                v-if="archiveMetadata && !archiveMetadata.file_exists"
                class="task-actions__state-note task-actions__state-note--warning"
              >
                <n-tag type="warning" size="small" :bordered="false">
                  {{ t('taskView.archiveFileExpired') }}
                </n-tag>
                <span>{{ t('taskView.archiveFileExpiredDescription') }}</span>
              </div>

              <div
                v-if="task && task.status === 'queued'"
                class="task-actions__state-note"
              >
                <n-tag type="info" size="small" :bordered="false">{{ t('status.queued') }}</n-tag>
                <span>{{ t('taskView.queuedStatusDescription') }}</span>
              </div>

              <div
                v-if="task && ['failed', 'cancelled'].includes(task.status) && activeRetryTask"
                class="task-actions__state-note"
              >
                <span>{{ t('taskView.retryExistsDescription') }}</span>
              </div>

            </div>
          </n-card>

          <!-- Process Panel -->
          <TaskProcessPanel
            :task="task ?? null"
            :task-logs="taskLogs"
            :is-active="isActiveTaskStatus(task?.status)"
            :terminal-html="terminalLogHtml"
            :task-status="task?.status ?? ''"
            :show-followup-replay-hint="showFollowupReplayHint"
            @raw-tab-open="onRawTabOpen"
            @raw-tab-close="onRawTabClose"
          />

          <!-- Result Panel (only for terminal tasks) -->
          <TaskResultPanel v-if="task && isTerminal" :task="task" @status-overridden="refreshTask" />
        </div>
      </n-spin>
    </n-space>
  </div>

  <!-- Schedule Drawer (retry with schedule) -->
  <n-drawer v-model:show="showScheduleDrawer" :width="isMobile ? '100%' : 680" placement="right">
    <n-drawer-content :title="t('taskView.retryWithSchedule')" closable>
      <n-spin v-if="scheduledTasksLoading" />
      <div v-else class="task-schedule-drawer">
        <div class="task-schedule-drawer__form">
          <div>
            <div class="task-actions__label">{{ t('taskView.retryWithSchedule') }}</div>
            <div class="task-actions__description">{{ t('taskView.retryWithScheduleDescription') }}</div>
          </div>
          <n-date-picker
            v-model:value="retryScheduleDatetime"
            type="datetime"
            class="task-actions__date-picker"
            :placeholder="t('taskView.selectRescheduleTime')"
            :is-date-disabled="isScheduledDateDisabled"
            :disabled="!canManageTask"
          />
        </div>

        <p class="task-schedule-drawer__hint">
          {{ t('taskView.schedulePreviewHint') }}
        </p>

        <HeatmapChart
          :tasks="scheduledTasksForPreview"
          :selected-ms="retryScheduleDatetime"
          :max-per-slot="slotMaxTasks"
          :enforce-capacity="slotEnforce"
          @cell-click="handleScheduleHeatmapCellClick"
        />

        <div class="task-schedule-drawer__actions">
          <n-button class="task-actions__command task-actions__command--neutral" @click="showScheduleDrawer = false">
            {{ t('common.cancel') }}
          </n-button>
          <n-button
            class="task-actions__command task-actions__command--primary"
            type="info"
            secondary
            strong
            @click="handleRetryWithSchedule"
            :loading="actionLoading"
            :disabled="!canManageTask || retryScheduleDatetime === null"
          >
            {{ t('taskView.scheduleRetry') }}
          </n-button>
        </div>
      </div>
    </n-drawer-content>
  </n-drawer>

  <TaskFormDrawer
    v-model:show="showEditDrawer"
    mode="edit"
    :task="task ?? undefined"
    @updated="task = $event"
  />

  <RescheduleDrawer
    v-model:show="showRescheduleDrawer"
    :task="task ?? undefined"
    @rescheduled="task = $event"
  />
</template>

<script setup lang="ts">
import { ref, onMounted, onBeforeUnmount, computed, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { NButton, NSpace, NCard, NTag, NGrid, NGi, NSpin, NDatePicker, NDrawer, NDrawerContent, NIcon, NScrollbar, useMessage } from 'naive-ui'
import { useI18n } from 'vue-i18n'
import { getTask, getTaskLogs, getTaskContainerLogs, cancelTask, retryTask, executeTask, streamTaskLogs, getScheduledTasks, getConfig, getIssue, getTaskArchive, downloadTaskArchive, type Task, type TaskLog } from '../api'
import { authState, isAdmin, initializeAuth } from '../auth'
import { renderMarkdown } from '../components/task-process/taskProcessUtils'
import PageHeader from '../components/PageHeader.vue'
import TaskMetadataPanel from '../components/TaskMetadataPanel.vue'
import TaskProcessPanel from '../components/TaskProcessPanel.vue'
import TaskResultPanel from '../components/TaskResultPanel.vue'
import { useBreakpoints } from '../composables/useBreakpoints'
import {
  CalendarOutline,
  CloseCircleOutline,
  CreateOutline,
  DownloadOutline,
  OpenOutline,
  PlayOutline,
  RefreshOutline,
  TimeOutline,
} from '@vicons/ionicons5'
import HeatmapChart from '../components/HeatmapChart.vue'
import TaskFormDrawer from '../components/TaskFormDrawer.vue'
import RescheduleDrawer from '../components/RescheduleDrawer.vue'
import AnsiToHtml from 'ansi-to-html'

const ansiConverter = new AnsiToHtml({ escapeXML: true })

const route = useRoute()
const router = useRouter()
const message = useMessage()
const { t } = useI18n()
const { isMobile } = useBreakpoints()

const taskId = computed(() => Number(route.params.id))
const renderedUserPrompt = computed(() => renderMarkdown(task.value?.user_prompt ?? ''))

const task = ref<Task | null>(null)
const logs = ref('')
const containerLogs = ref('')
const loading = ref(false)
const hasLoadedOnce = ref(false)
const logsLoading = ref(false)
const containerLogsLoading = ref(false)
const actionLoading = ref(false)
const taskRequestInFlight = ref(false)
const retryScheduleDatetime = ref<number | null>(null)
const showScheduleDrawer = ref(false)
const showEditDrawer = ref(false)
const showRescheduleDrawer = ref(false)
const scheduledTasksForPreview = ref<Task[]>([])
const scheduledTasksLoading = ref(false)
const slotMaxTasks = ref(0)
const slotEnforce = ref(false)
const taskLogs = ref<TaskLog[]>([])
const activeRetryTask = ref<Task | null>(null)
const issueTasks = ref<Task[]>([])
const archiveMetadata = ref<{ archive_name: string; archive_size_bytes: number; created_at: string; file_exists: boolean } | null>(null)
const archiveDownloadLoading = ref(false)
let pollTimer: number | null = null
let logEventSource: EventSource | null = null
let logStreamContainerId: string | null = null
let structuredLogSse: EventSource | null = null
// Buffer for logs arriving faster than one-per-tick (e.g. during fast-forward
// catch-up).  Flushed as a single reactive update via queueMicrotask to avoid
// O(n²) array copies when hundreds of SSE events arrive in rapid succession.
let _pendingLogBuffer: TaskLog[] = []
let _logFlushScheduled = false
const initialLoading = computed(() => loading.value && !hasLoadedOnce.value)

const terminalLogHtml = computed(() => {
  // For completed/failed tasks: use structured logs formatted as text
  // For active tasks: use live container logs streamed via SSE
  const text = containerLogs.value || logs.value
  if (!text) return ''
  return ansiConverter.toHtml(text)
})

const isTerminal = computed(() =>
  task.value?.status === 'completed' || task.value?.status === 'failed'
)

const statusColors: Record<string, 'default' | 'info' | 'warning' | 'success' | 'error'> = {
  pending: 'default',
  queued: 'info',
  running: 'warning',
  completed: 'success',
  failed: 'error',
  cancelled: 'default'
}

const hasActions = computed(() => {
  if (!task.value) return false
  if (archiveMetadata.value) return true
  return ['pending', 'queued', 'running', 'failed', 'cancelled'].includes(task.value.status)
})

const hasActionDetails = computed(() => {
  if (!task.value) return false

  const retryHasContext = ['failed', 'cancelled'].includes(task.value.status) && !!activeRetryTask.value

  return (
    (hasActions.value && !canManageTask.value) ||
    (!!archiveMetadata.value && !archiveMetadata.value.file_exists) ||
    task.value.status === 'queued' ||
    retryHasContext
  )
})

const canReschedule = computed(() => {
  const s = task.value?.status
  if (s === 'queued') return true
  return s === 'pending' && !!task.value?.scheduled_at
})
const canManageTask = computed(() => {
  if (!task.value) return false
  if (!authState.oidcEnabled) return true
  if (!authState.user) return false
  if (isAdmin.value) return true

  return (
    (task.value.initiator_user_id !== null && task.value.initiator_user_id === authState.user.id)
    || (
      task.value.initiator_gitlab_user_id !== null
      && task.value.initiator_gitlab_user_id === authState.user.gitlab_user_id
    )
  )
})

const showFollowupReplayHint = computed(() => {
  if (!task.value?.issue_id) return false
  const tasks = [...issueTasks.value].sort((a, b) => {
    const createdDelta = new Date(a.created_at).getTime() - new Date(b.created_at).getTime()
    return createdDelta !== 0 ? createdDelta : a.id - b.id
  })
  const currentIndex = tasks.findIndex((item) => item.id === task.value?.id)
  return currentIndex > 0
})


function isScheduledDateDisabled(timestamp: number): boolean {
  const candidate = new Date(timestamp)
  const today = new Date()

  candidate.setHours(0, 0, 0, 0)
  today.setHours(0, 0, 0, 0)

  return candidate.getTime() < today.getTime()
}

function isActiveTaskStatus(status?: string | null): boolean {
  return status === 'running' || status === 'pending' || status === 'queued'
}

async function checkActiveRetry() {
  if (!task.value || !['failed', 'cancelled'].includes(task.value.status)) {
    activeRetryTask.value = null
    return
  }
  try {
    const issueId = task.value.issue_id ?? task.value.issue?.id
    if (issueId) {
      if (issueTasks.value.length > 0) {
        // Find the latest retry task for this task (any status)
        const retryMatch = issueTasks.value
          .filter(t => t.retry_source_task_id === task.value!.id)
          .sort((a, b) => b.id - a.id)[0]
        activeRetryTask.value = retryMatch ?? null
      } else {
        activeRetryTask.value = null
      }
    } else {
      activeRetryTask.value = null
    }
  } catch {
    activeRetryTask.value = null
  }
}

async function refreshIssueTasks() {
  const issueId = task.value?.issue_id ?? task.value?.issue?.id
  if (!issueId) {
    issueTasks.value = []
    return
  }
  try {
    const issueData = await getIssue(issueId)
    issueTasks.value = issueData.tasks ?? []
  } catch {
    issueTasks.value = []
  }
}

function trimLogBuffer(content: string): string {
  const maxLogSize = 200_000
  return content.length > maxLogSize ? content.slice(-maxLogSize) : content
}

function closeLogStream() {
  if (logEventSource) {
    logEventSource.close()
    logEventSource = null
  }
  logStreamContainerId = null
}

function closeStructuredLogStream() {
  if (structuredLogSse) {
    structuredLogSse.close()
    structuredLogSse = null
  }
  // Discard any buffered logs that haven't been flushed yet.
  _pendingLogBuffer.length = 0
  _logFlushScheduled = false
}

function connectStructuredLogStream() {
  if (typeof EventSource === 'undefined') return
  if (!isActiveTaskStatus(task.value?.status)) return
  if (structuredLogSse) return // already connected

  const sinceId = taskLogs.value.length > 0
    ? Math.max(...taskLogs.value.map(l => l.id ?? 0))
    : 0

  // Shared handler: merge an updated log entry into taskLogs by id.
  const mergeLogUpdate = (log: TaskLog) => {
    const idx = taskLogs.value.findIndex(l => l.id === log.id)
    if (idx !== -1) {
      const updated = [...taskLogs.value]
      updated[idx] = log
      taskLogs.value = updated
    }
  }

  structuredLogSse = streamTaskLogs(
    taskId.value,
    sinceId,
    (log) => {
      // Buffer the incoming log and schedule a single microtask flush to avoid
      // O(n²) array copies when many SSE events arrive back-to-back.
      _pendingLogBuffer.push(log)
      if (!_logFlushScheduled) {
        _logFlushScheduled = true
        queueMicrotask(() => {
          _logFlushScheduled = false
          if (_pendingLogBuffer.length === 0) return
          const incoming = _pendingLogBuffer.splice(0)
          const current = taskLogs.value
          const idSet = new Set(current.map(l => l.id))
          const toAdd = incoming.filter(l => !idSet.has(l.id))
          if (toAdd.length > 0) {
            taskLogs.value = [...current, ...toAdd]
          }
          // Handle duplicates (updates) for any that already exist.
          incoming.filter(l => idSet.has(l.id)).forEach(mergeLogUpdate)
        })
      }
    },
    () => {
      // SSE signaled task is done
      closeStructuredLogStream()
      fetchTask()
      fetchLogs()
    },
    // "update" events carry in-place metadata changes (e.g. output_payload_id
    // added to an existing tool_call log row by the worker).
    mergeLogUpdate,
  )

  structuredLogSse.onerror = () => {
    // Don't auto-reconnect — the poll timer will call connectStructuredLogStream() again in 5s
    closeStructuredLogStream()
  }
}

function connectLogStream() {
  if (typeof EventSource === 'undefined') return

  const containerId = task.value?.container_id
  if (!containerId || !isActiveTaskStatus(task.value?.status)) {
    closeLogStream()
    return
  }

  if (logEventSource && logStreamContainerId === containerId) {
    return
  }

  const previousContainerId = logStreamContainerId
  closeLogStream()
  // Only clear logs when connecting to a different container (not a reconnect to the same)
  if (previousContainerId !== containerId) {
    containerLogs.value = ''
  }
  containerLogsLoading.value = true
  logStreamContainerId = containerId
  let receivedFirstMessage = false
  logEventSource = new EventSource(`/api/containers/${containerId}/logs`)

  logEventSource.onmessage = (event) => {
    receivedFirstMessage = true
    containerLogsLoading.value = false
    const chunk = event.data.endsWith('\n') ? event.data : `${event.data}\n`
    containerLogs.value = trimLogBuffer(containerLogs.value + chunk)
  }

  logEventSource.onerror = () => {
    containerLogsLoading.value = false
    const likelyAuthFailure = !receivedFirstMessage
    if (likelyAuthFailure || !isActiveTaskStatus(task.value?.status) || task.value?.container_id !== logStreamContainerId) {
      closeLogStream()
    }
  }
}

async function fetchTask() {
  if (taskRequestInFlight.value) return
  taskRequestInFlight.value = true
  loading.value = true
  try {
    const previousStatus = task.value?.status
    task.value = await getTask(taskId.value)

    if (isActiveTaskStatus(previousStatus) && !isActiveTaskStatus(task.value.status)) {
      await fetchLogs()
    }

    // Auto-retry detection: task restarted (non-active → active) while we were watching.
    // Clear stale in-memory logs so the event stream starts fresh.
    if (!isActiveTaskStatus(previousStatus) && isActiveTaskStatus(task.value.status)) {
      resetLogsState()
      connectStructuredLogStream()
    }

    await refreshIssueTasks()
    await checkActiveRetry()
    void fetchArchiveMetadata()
  } catch (error) {
    message.error(t('taskView.failedToFetchTask'))
  } finally {
    hasLoadedOnce.value = true
    loading.value = false
    taskRequestInFlight.value = false
  }
}

async function fetchArchiveMetadata() {
  if (!task.value || !isTerminal.value) {
    archiveMetadata.value = null
    return
  }
  try {
    archiveMetadata.value = await getTaskArchive(taskId.value)
  } catch {
    archiveMetadata.value = null
  }
}

async function fetchLogs() {
  logsLoading.value = true
  try {
    const logEntries = await getTaskLogs(taskId.value)
    taskLogs.value = logEntries
    logs.value = logEntries.map(l => `[${l.created_at}] [${l.log_level}] ${l.message}`).join('\n')
  } catch (error) {
    logs.value = t('taskView.failedToFetchLogs')
  } finally {
    logsLoading.value = false
  }
}

async function refreshTask() {
  await fetchTask()
  if (!isActiveTaskStatus(task.value?.status)) {
    await fetchLogs()
  }
}

async function onRawTabOpen() {
  if (isActiveTaskStatus(task.value?.status)) {
    // Fetch stored DB chunks first to show historical content, then connect live SSE
    if (!containerLogs.value && task.value?.container_id) {
      try {
        const result = await getTaskContainerLogs(taskId.value, 'db')
        if (result.logs) containerLogs.value = result.logs
      } catch {
        // Ignore — live SSE will fill content
      }
    }
    connectLogStream()
  } else {
    // For completed/failed/cancelled tasks, always read from DB (TaskRawLogChunk → TaskLog fallback)
    containerLogsLoading.value = true
    try {
      const result = await getTaskContainerLogs(taskId.value, 'db')
      containerLogs.value = result.logs
    } catch (error) {
      containerLogs.value = t('taskView.failedToFetchContainerLogs')
    } finally {
      containerLogsLoading.value = false
    }
  }
}

function onRawTabClose() {
  // Close SSE when leaving raw tab to free the backend thread
  closeLogStream()
}

async function handleCancel() {
  actionLoading.value = true
  try {
    await cancelTask(taskId.value)
    message.success(t('taskView.taskCancelled'))
    refreshTask()
  } catch (error) {
    message.error(t('taskView.failedToCancelTask'))
  } finally {
    actionLoading.value = false
  }
}

async function handleDownloadArchive() {
  if (!archiveMetadata.value?.file_exists) return
  archiveDownloadLoading.value = true
  try {
    const blob = await downloadTaskArchive(taskId.value)
    const url = URL.createObjectURL(blob)
    try {
      const anchor = document.createElement('a')
      anchor.href = url
      anchor.download = archiveMetadata.value.archive_name
      document.body.appendChild(anchor)
      anchor.click()
      anchor.remove()
    } finally {
      URL.revokeObjectURL(url)
    }
  } catch {
    message.error(t('taskView.failedToDownloadRuntimeArchive'))
  } finally {
    archiveDownloadLoading.value = false
  }
}

function resetLogsState() {
  taskLogs.value = []
  logs.value = ''
  containerLogs.value = ''
  archiveMetadata.value = null
  closeStructuredLogStream()
  closeLogStream()
}

async function handleRetry() {
  actionLoading.value = true
  try {
    const newTask = await retryTask(taskId.value)
    resetLogsState()
    message.success(t('taskView.taskRetryScheduled'))
    router.push(`/tasks/${newTask.id}`)
  } catch (error: any) {
    if (error?.response?.status === 409) {
      message.warning(t('taskView.retryAlreadyExists'))
      await checkActiveRetry()
    } else {
      message.error(t('taskView.failedToRetryTask'))
    }
  } finally {
    actionLoading.value = false
  }
}

async function handleRetryWithSchedule() {
  if (!retryScheduleDatetime.value) {
    message.error(t('taskView.selectRescheduleTime'))
    return
  }
  if (retryScheduleDatetime.value <= Date.now()) {
    message.error(t('taskView.rescheduleTimeFuture'))
    return
  }
  actionLoading.value = true
  try {
    const newTask = await retryTask(taskId.value, new Date(retryScheduleDatetime.value).toISOString())
    retryScheduleDatetime.value = null
    showScheduleDrawer.value = false
    resetLogsState()
    message.success(t('taskView.taskRetryRescheduled'))
    router.push(`/tasks/${newTask.id}`)
  } catch (error: any) {
    if (error?.response?.status === 409) {
      message.warning(t('taskView.retryAlreadyExists'))
      await checkActiveRetry()
    } else {
      message.error(t('taskView.failedToRetryTask'))
    }
  } finally {
    actionLoading.value = false
  }
}

async function handleExecute() {
  actionLoading.value = true
  try {
    await executeTask(taskId.value)
    message.success(t('taskView.taskExecutionStarted'))
    refreshTask()
  } catch (error) {
    message.error(t('taskView.failedToExecuteTask'))
  } finally {
    actionLoading.value = false
  }
}


async function openScheduleDrawer() {
  showScheduleDrawer.value = true
  scheduledTasksLoading.value = true
  try {
    scheduledTasksForPreview.value = await getScheduledTasks()
  } catch {
    scheduledTasksForPreview.value = []
  } finally {
    scheduledTasksLoading.value = false
  }
  try {
    const config = await getConfig()
    slotMaxTasks.value = config.runtime?.slot_max_tasks ?? 0
    slotEnforce.value = config.runtime?.slot_max_tasks_enforce ?? false
  } catch { /* ignore */ }
}

function handleScheduleHeatmapCellClick(startMs: number) {
  retryScheduleDatetime.value = startMs
}

onMounted(async () => {
  await initializeAuth()
  await fetchTask()
  await fetchLogs()
  if (isActiveTaskStatus(task.value?.status)) {
    connectStructuredLogStream()
  }
  pollTimer = window.setInterval(() => {
    if (document.visibilityState !== 'visible') return

    if (isActiveTaskStatus(task.value?.status)) {
      fetchTask()
      if (!structuredLogSse) connectStructuredLogStream() // reconnect if disconnected
    } else {
      closeLogStream()
      closeStructuredLogStream()
    }
  }, 5000)
})

watch(
  () => route.params.id,
  (newId, oldId) => {
    if (newId && newId !== oldId) {
      resetLogsState()
      task.value = null
      activeRetryTask.value = null
      issueTasks.value = []
      archiveMetadata.value = null
      showRescheduleDrawer.value = false
      showScheduleDrawer.value = false
      hasLoadedOnce.value = false
      fetchTask()
    }
  }
)

onBeforeUnmount(() => {
  closeLogStream()
  closeStructuredLogStream()
  if (pollTimer !== null) {
    clearInterval(pollTimer)
    pollTimer = null
  }
})
</script>

<style scoped>
.log-content {
  background: #1e1e1e;
  color: #d4d4d4;
  padding: 16px;
  border-radius: 12px;
  max-height: 400px;
  overflow: auto;
  font-family: 'Consolas', 'Monaco', 'Courier New', monospace, 'Apple Color Emoji', 'Segoe UI Emoji', 'Noto Color Emoji';
  font-size: 12px;
  white-space: pre-wrap;
  word-break: break-all;
}

.task-view {
  max-width: var(--app-page-max-width);
}

.task-view__actions {
  display: inline-flex;
  align-items: center;
  justify-content: flex-end;
  gap: 8px;
  flex-wrap: wrap;
  flex: 1 1 360px;
}

.task-view__content {
  display: grid;
  gap: 20px;
}

.task-view__title {
  margin: 0;
  font-size: var(--app-page-title-size);
  line-height: 1.2;
}

.task-card {
  border-radius: var(--app-card-radius);
}

.task-card--equal {
  height: 100%;
  display: flex;
  flex-direction: column;
}

.task-card--equal :deep(.n-card-content) {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.task-prompt-wrap {
  background: rgba(15, 23, 42, 0.035);
  border-radius: 8px;
  overflow: hidden;
}

.task-prompt-content {
  padding: 12px 14px;
  line-height: 1.6;
  color: rgba(15, 23, 42, 0.82);
}
.task-prompt-content :deep(p) { margin: 0 0 0.6em; }
.task-prompt-content :deep(p:last-child) { margin-bottom: 0; }
.task-prompt-content :deep(h1),
.task-prompt-content :deep(h2),
.task-prompt-content :deep(h3),
.task-prompt-content :deep(h4) { margin: 0.8em 0 0.4em; font-weight: 600; line-height: 1.3; }
.task-prompt-content :deep(h1) { font-size: 1.25em; }
.task-prompt-content :deep(h2) { font-size: 1.1em; }
.task-prompt-content :deep(h3) { font-size: 1em; }
.task-prompt-content :deep(ul),
.task-prompt-content :deep(ol) { margin: 0.4em 0; padding-left: 1.5em; }
.task-prompt-content :deep(li) { margin: 0.15em 0; }
.task-prompt-content :deep(blockquote) {
  margin: 0.5em 0; padding: 0.2em 0.8em;
  border-left: 3px solid rgba(128,128,128,0.35);
  color: rgba(15, 23, 42, 0.5);
}
.task-prompt-content :deep(a) { color: var(--n-primary-color, #18a058); text-decoration: none; }
.task-prompt-content :deep(a:hover) { text-decoration: underline; }
.task-prompt-content :deep(code) {
  font-family: var(--n-font-family-mono, monospace);
  font-size: 0.88em; background: rgba(128,128,128,0.12);
  border-radius: 3px; padding: 0.1em 0.35em;
}
.task-prompt-content :deep(pre.md-code-block) {
  margin: 0.5em 0; padding: 10px 12px;
  background: rgba(0,0,0,0.06); border-radius: 5px;
  overflow-x: auto; font-family: var(--n-font-family-mono, monospace);
  font-size: 0.85em; line-height: 1.55; white-space: pre;
}
.task-prompt-content :deep(pre.md-code-block code) { background: none; padding: 0; border-radius: 0; font-size: inherit; color: inherit; }
.task-prompt-content :deep(table) { width: 100%; border-collapse: collapse; margin: 0.6em 0; font-size: 0.9em; overflow-x: auto; display: block; }
.task-prompt-content :deep(th),
.task-prompt-content :deep(td) { border: 1px solid rgba(128,128,128,0.25); padding: 5px 10px; text-align: left; }
.task-prompt-content :deep(th) { background: rgba(128,128,128,0.08); font-weight: 600; }
.task-prompt-content :deep(tr:nth-child(even) td) { background: rgba(128,128,128,0.04); }
.task-prompt-content :deep(hr) { border: none; border-top: 1px solid rgba(128,128,128,0.2); margin: 0.8em 0; }

.task-card--spaced {
  margin-top: 16px;
}

.task-card__header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 12px;
}

.task-card__title {
  font-size: 18px;
  font-weight: 600;
}

.task-card__subtitle {
  margin-top: 4px;
  font-size: 13px;
  color: rgba(15, 23, 42, 0.58);
}

.task-card--actions :deep(.n-card-content) {
  padding-top: 12px;
}

.task-card--actions {
  order: -1;
}

.task-actions {
  display: grid;
  gap: 10px;
}

.task-actions--header {
  width: 100%;
}

.task-actions__toolbar {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  flex-wrap: wrap;
  gap: 8px;
  min-height: 34px;
}

.task-actions__command {
  flex: 0 0 auto;
  --n-height: 34px !important;
  --n-padding: 0 12px !important;
  --n-font-weight: 400 !important;
  --n-border-radius: 10px !important;
  --n-ripple-color: rgba(37, 99, 235, 0.18) !important;
}

.task-actions__command--neutral {
  --n-color: rgba(255, 255, 255, 0.68) !important;
  --n-color-hover: rgba(248, 250, 252, 0.96) !important;
  --n-color-focus: rgba(248, 250, 252, 0.96) !important;
  --n-color-pressed: rgba(241, 245, 249, 0.96) !important;
  --n-color-disabled: rgba(248, 250, 252, 0.58) !important;
  --n-text-color: rgba(51, 65, 85, 0.92) !important;
  --n-text-color-hover: rgba(30, 41, 59, 0.96) !important;
  --n-text-color-focus: rgba(30, 41, 59, 0.96) !important;
  --n-text-color-pressed: rgba(15, 23, 42, 0.98) !important;
  --n-text-color-disabled: rgba(100, 116, 139, 0.52) !important;
  --n-border: 1px solid rgba(15, 23, 42, 0.12) !important;
  --n-border-hover: 1px solid rgba(15, 23, 42, 0.18) !important;
  --n-border-focus: 1px solid rgba(37, 99, 235, 0.28) !important;
  --n-border-pressed: 1px solid rgba(15, 23, 42, 0.22) !important;
  --n-border-disabled: 1px solid rgba(15, 23, 42, 0.08) !important;
}

.task-actions__command--primary {
  --n-color: rgba(32, 128, 240, 0.08) !important;
  --n-color-hover: rgba(32, 128, 240, 0.12) !important;
  --n-color-focus: rgba(32, 128, 240, 0.12) !important;
  --n-color-pressed: rgba(32, 128, 240, 0.16) !important;
  --n-color-disabled: rgba(32, 128, 240, 0.05) !important;
  --n-text-color: #1d4ed8 !important;
  --n-text-color-hover: #1e40af !important;
  --n-text-color-focus: #1e40af !important;
  --n-text-color-pressed: #1e3a8a !important;
  --n-text-color-disabled: rgba(29, 78, 216, 0.42) !important;
  --n-border: 1px solid rgba(32, 128, 240, 0.18) !important;
  --n-border-hover: 1px solid rgba(32, 128, 240, 0.28) !important;
  --n-border-focus: 1px solid rgba(32, 128, 240, 0.32) !important;
  --n-border-pressed: 1px solid rgba(32, 128, 240, 0.36) !important;
  --n-border-disabled: 1px solid rgba(32, 128, 240, 0.1) !important;
  --n-ripple-color: rgba(32, 128, 240, 0.2) !important;
}

.task-actions__command--retry {
  --n-color: rgba(217, 119, 6, 0.08) !important;
  --n-color-hover: rgba(217, 119, 6, 0.12) !important;
  --n-color-focus: rgba(217, 119, 6, 0.12) !important;
  --n-color-pressed: rgba(217, 119, 6, 0.16) !important;
  --n-color-disabled: rgba(217, 119, 6, 0.05) !important;
  --n-text-color: #a16207 !important;
  --n-text-color-hover: #854d0e !important;
  --n-text-color-focus: #854d0e !important;
  --n-text-color-pressed: #713f12 !important;
  --n-text-color-disabled: rgba(161, 98, 7, 0.42) !important;
  --n-border: 1px solid rgba(217, 119, 6, 0.18) !important;
  --n-border-hover: 1px solid rgba(217, 119, 6, 0.28) !important;
  --n-border-focus: 1px solid rgba(217, 119, 6, 0.32) !important;
  --n-border-pressed: 1px solid rgba(217, 119, 6, 0.36) !important;
  --n-border-disabled: 1px solid rgba(217, 119, 6, 0.1) !important;
  --n-ripple-color: rgba(217, 119, 6, 0.18) !important;
}

.task-actions__command--danger {
  --n-color: rgba(208, 48, 80, 0.07) !important;
  --n-color-hover: rgba(208, 48, 80, 0.1) !important;
  --n-color-focus: rgba(208, 48, 80, 0.1) !important;
  --n-color-pressed: rgba(208, 48, 80, 0.14) !important;
  --n-color-disabled: rgba(208, 48, 80, 0.04) !important;
  --n-text-color: #b42342 !important;
  --n-text-color-hover: #9f1d38 !important;
  --n-text-color-focus: #9f1d38 !important;
  --n-text-color-pressed: #88172f !important;
  --n-text-color-disabled: rgba(180, 35, 66, 0.42) !important;
  --n-border: 1px solid rgba(208, 48, 80, 0.18) !important;
  --n-border-hover: 1px solid rgba(208, 48, 80, 0.28) !important;
  --n-border-focus: 1px solid rgba(208, 48, 80, 0.32) !important;
  --n-border-pressed: 1px solid rgba(208, 48, 80, 0.36) !important;
  --n-border-disabled: 1px solid rgba(208, 48, 80, 0.1) !important;
  --n-ripple-color: rgba(208, 48, 80, 0.18) !important;
}

.task-actions__command--active {
  --n-color: rgba(32, 128, 240, 0.14) !important;
  --n-border: 1px solid rgba(32, 128, 240, 0.34) !important;
  box-shadow: 0 0 0 2px rgba(32, 128, 240, 0.08);
}

.task-actions__command--refresh {
  margin-left: 2px;
}

.task-actions__linked-task {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  min-height: 34px;
  padding: 0 10px;
  border: 1px solid rgba(32, 128, 240, 0.16);
  border-radius: 8px;
  background: rgba(32, 128, 240, 0.06);
  color: rgba(15, 23, 42, 0.72);
  font-size: 13px;
  white-space: nowrap;
}

.task-actions__permission-note {
  padding: 8px 10px;
  border-radius: 8px;
  background: rgba(240, 160, 32, 0.075);
  color: rgba(163, 94, 12, 0.92);
  font-size: 13px;
  line-height: 1.45;
}

.task-actions__state-note {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  padding: 8px 10px;
  border-radius: 8px;
  background: rgba(15, 23, 42, 0.035);
  color: rgba(15, 23, 42, 0.66);
  font-size: 13px;
  line-height: 1.45;
}

.task-actions__state-note--warning {
  background: rgba(240, 160, 32, 0.075);
  color: rgba(163, 94, 12, 0.92);
}

.task-actions__label {
  font-size: 15px;
  font-weight: 600;
  color: var(--n-text-color-1);
}

.task-actions__description {
  margin-top: 4px;
  font-size: 13px;
  line-height: 1.45;
  color: rgba(15, 23, 42, 0.64);
}

.task-actions__empty {
  display: inline-flex;
  align-items: center;
  width: fit-content;
  max-width: 100%;
  padding: 8px 10px;
  border-radius: 8px;
  background: rgba(15, 23, 42, 0.04);
  color: rgba(15, 23, 42, 0.64);
  font-size: 13px;
}

.task-actions__empty--header {
  min-height: 34px;
}

.task-actions__date-picker {
  width: 100%;
}

.task-schedule-drawer {
  display: grid;
  gap: 14px;
}

.task-schedule-drawer__form {
  display: grid;
  gap: 12px;
  padding-bottom: 2px;
}

.task-schedule-drawer__form .task-actions__date-picker {
  width: min(100%, 200px);
}

.task-schedule-drawer__hint {
  margin: 0;
  color: rgba(15, 23, 42, 0.58);
  font-size: 13px;
  line-height: 1.45;
}

.task-schedule-drawer__actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  flex-wrap: wrap;
  padding-top: 2px;
}

@media (max-width: 768px) {
  .task-view__actions {
    width: 100%;
    justify-content: flex-start;
    flex-basis: auto;
  }

  .task-card__header {
    flex-direction: column;
    align-items: flex-start;
  }

  .task-actions__toolbar {
    align-items: stretch;
    justify-content: flex-start;
  }

  .task-actions__command,
  .task-actions__linked-task {
    flex: 1 1 150px;
    justify-content: center;
  }

  .task-schedule-drawer__form .task-actions__date-picker {
    width: 100%;
  }

  .task-schedule-drawer__actions :deep(.n-button) {
    flex: 1 1 140px;
  }
}
</style>
