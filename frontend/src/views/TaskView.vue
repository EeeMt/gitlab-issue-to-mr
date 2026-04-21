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
          <n-button @click="refreshTask" :loading="loading">
            {{ t('common.refresh') }}
          </n-button>
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
                  <div class="task-prompt-content">{{ task.user_prompt }}</div>
                </div>
              </n-card>
            </n-gi>
          </n-grid>

          <!-- Actions card -->
          <n-card class="task-card" :bordered="false" data-testid="task-actions-card">
                <template #header>
                  <div class="task-card__header">
                    <div>
                      <div class="task-card__title">{{ t('taskView.actions') }}</div>
                      <div class="task-card__subtitle">{{ t('taskView.actionsSubtitle') }}</div>
                    </div>
                  </div>
                </template>

                <div class="task-actions" data-testid="task-actions">
                  <div class="task-actions__intro" v-if="hasActions">
                    {{ t('taskView.actionsIntro') }}
                  </div>

                  <div v-if="hasActions && !canManageTask" class="task-actions__permission-note">
                    {{ t('taskView.actionPermissionHint') }}
                  </div>

                  <div
                    v-if="task && ['pending', 'queued', 'running'].includes(task.status)"
                    class="task-actions__item task-actions__item--error"
                  >
                    <div class="task-actions__meta">
                      <div class="task-actions__label">{{ t('taskView.cancelTask') }}</div>
                      <div class="task-actions__description">
                        {{ t('taskView.cancelTaskDescription') }}
                      </div>
                    </div>
                    <n-button
                      type="error"
                      secondary
                      strong
                      round
                      @click="handleCancel"
                      :loading="actionLoading"
                      :disabled="!canManageTask"
                    >
                      {{ t('common.cancel') }}
                    </n-button>
                  </div>

                  <!-- Existing active retry — link to it instead of showing retry buttons -->
                  <div
                    v-if="task && ['failed', 'cancelled'].includes(task.status) && activeRetryTask"
                    class="task-actions__item task-actions__item--info"
                  >
                    <div class="task-actions__meta">
                      <div class="task-actions__label">{{ t('taskView.retryExists') }}</div>
                      <div class="task-actions__description">
                        {{ t('taskView.retryExistsDescription') }}
                      </div>
                    </div>
                    <n-button
                      type="primary"
                      text
                      @click="router.push(`/tasks/${activeRetryTask.id}`)"
                    >
                      Task #{{ activeRetryTask.id }}
                    </n-button>
                  </div>

                  <div
                    v-if="task && ['failed', 'cancelled'].includes(task.status) && !activeRetryTask"
                    class="task-actions__item task-actions__item--warning"
                  >
                    <div class="task-actions__meta">
                      <div class="task-actions__label">{{ t('taskView.retryTask') }}</div>
                      <div class="task-actions__description">
                        {{ t('taskView.retryTaskDescription') }}
                      </div>
                    </div>
                    <n-button
                      type="warning"
                      secondary
                      strong
                      round
                      @click="handleRetry"
                      :loading="actionLoading"
                      :disabled="!canManageTask"
                    >
                      {{ t('common.retry') }}
                    </n-button>
                  </div>

                  <div
                    v-if="task && ['failed', 'cancelled'].includes(task.status) && !activeRetryTask"
                    class="task-actions__item task-actions__item--info"
                  >
                    <div class="task-actions__meta">
                      <div class="task-actions__label">{{ t('taskView.retryWithSchedule') }}</div>
                      <div class="task-actions__description">
                        {{ t('taskView.retryWithScheduleDescription') }}
                      </div>
                    </div>
                    <div class="task-actions__controls">
                      <n-date-picker
                        v-model:value="retryScheduleDatetime"
                        type="datetime"
                        class="task-actions__date-picker"
                        :placeholder="t('taskView.selectRescheduleTime')"
                        :is-date-disabled="isScheduledDateDisabled"
                        :disabled="!canManageTask"
                      />
                      <n-button
                        type="info"
                        secondary
                        strong
                        round
                        @click="handleRetryWithSchedule"
                        :loading="actionLoading"
                        :disabled="!canManageTask || retryScheduleDatetime === null"
                      >
                        {{ t('taskView.scheduleRetry') }}
                      </n-button>
                    </div>
                  </div>

                  <div
                    v-if="task && canReschedule"
                    class="task-actions__item task-actions__item--info"
                  >
                    <div class="task-actions__meta">
                      <div class="task-actions__label">{{ t('taskView.rescheduleTask') }}</div>
                      <div class="task-actions__description">
                        {{ t('taskView.rescheduleTaskDescription') }}
                      </div>
                    </div>
                    <div class="task-actions__controls">
                      <n-date-picker
                        v-model:value="rescheduleDatetime"
                        type="datetime"
                        class="task-actions__date-picker"
                        :placeholder="t('taskView.selectRescheduleTime')"
                        :is-date-disabled="isScheduledDateDisabled"
                        :disabled="!canManageTask"
                      />
                      <n-button
                        secondary
                        round
                        :loading="scheduledTasksLoading"
                        @click="openScheduleDrawer"
                        :disabled="!canManageTask"
                      >
                        <template #icon><n-icon :component="CalendarOutline" /></template>
                        {{ t('taskView.viewScheduleHeatmap') }}
                      </n-button>
                      <n-button
                        type="info"
                        secondary
                        strong
                        round
                        @click="handleReschedule"
                        :loading="actionLoading"
                        :disabled="!canManageTask || rescheduleDatetime === null"
                      >
                        {{ t('taskView.saveScheduledTime') }}
                      </n-button>
                    </div>
                  </div>

                  <div
                    v-if="task && task.status === 'pending'"
                    class="task-actions__item task-actions__item--info"
                  >
                    <div class="task-actions__meta">
                      <div class="task-actions__label">{{ t('taskView.executeNow') }}</div>
                      <div class="task-actions__description">
                        {{ t('taskView.executeNowDescription') }}
                      </div>
                    </div>
                    <n-button
                      type="info"
                      secondary
                      strong
                      round
                      @click="handleExecute"
                      :loading="actionLoading"
                      :disabled="!canManageTask"
                    >
                      {{ t('common.execute') }}
                    </n-button>
                  </div>

                  <!-- QUEUED info -->
                  <div
                    v-if="task && task.status === 'queued'"
                    class="task-actions__item task-actions__item--info"
                  >
                    <div class="task-actions__meta">
                      <div class="task-actions__label">{{ t('taskView.queuedStatus') }}</div>
                      <div class="task-actions__description">
                        {{ t('taskView.queuedStatusDescription') }}
                      </div>
                    </div>
                    <n-tag type="info" round>{{ t('status.queued') }}</n-tag>
                  </div>

                  <div v-if="!hasActions" class="task-actions__empty">
                    {{ t('taskView.noManualAction') }}
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
            @raw-tab-open="onRawTabOpen"
            @raw-tab-close="onRawTabClose"
          />

          <!-- Result Panel (only for terminal tasks) -->
          <TaskResultPanel v-if="task && isTerminal" :task="task" />
        </div>
      </n-spin>
    </n-space>
  </div>

  <!-- Schedule Heatmap Drawer -->
  <n-drawer v-model:show="showScheduleDrawer" :width="isMobile ? '100%' : 580" placement="right">
    <n-drawer-content :title="t('taskView.schedulePreviewTitle')" closable>
      <n-spin v-if="scheduledTasksLoading" />
      <template v-else>
        <p style="margin-bottom: 12px; color: rgba(15, 23, 42, 0.58); font-size: 13px;">
          {{ t('taskView.schedulePreviewHint') }}
        </p>
        <HeatmapChart
          :tasks="scheduledTasksForPreview"
          :selected-ms="rescheduleDatetime"
          :max-per-slot="slotMaxTasks"
          :enforce-capacity="slotEnforce"
          @cell-click="handleScheduleHeatmapCellClick"
        />
      </template>
    </n-drawer-content>
  </n-drawer>
</template>

<script setup lang="ts">
import { ref, onMounted, onBeforeUnmount, computed, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { NButton, NSpace, NCard, NTag, NGrid, NGi, NSpin, NDatePicker, NDrawer, NDrawerContent, NIcon, useMessage } from 'naive-ui'
import { useI18n } from 'vue-i18n'
import { getTask, getTaskLogs, getTaskContainerLogs, cancelTask, retryTask, executeTask, rescheduleTask, streamTaskLogs, getScheduledTasks, getConfig, getIssue, type Task, type TaskLog } from '../api'
import { authState, isAdmin, initializeAuth } from '../auth'
import PageHeader from '../components/PageHeader.vue'
import TaskMetadataPanel from '../components/TaskMetadataPanel.vue'
import TaskProcessPanel from '../components/TaskProcessPanel.vue'
import TaskResultPanel from '../components/TaskResultPanel.vue'
import { useBreakpoints } from '../composables/useBreakpoints'
import { parseUtcDate } from '../utils/datetime'
import { extractSlotErrorMessage } from '../utils/slotError'
import { CalendarOutline } from '@vicons/ionicons5'
import HeatmapChart from '../components/HeatmapChart.vue'
import AnsiToHtml from 'ansi-to-html'

const ansiConverter = new AnsiToHtml({ escapeXML: true })

const route = useRoute()
const router = useRouter()
const message = useMessage()
const { t } = useI18n()
const { isMobile } = useBreakpoints()

const taskId = computed(() => Number(route.params.id))

const task = ref<Task | null>(null)
const logs = ref('')
const containerLogs = ref('')
const loading = ref(false)
const hasLoadedOnce = ref(false)
const logsLoading = ref(false)
const containerLogsLoading = ref(false)
const actionLoading = ref(false)
const taskRequestInFlight = ref(false)
const containerRequestInFlight = ref(false)
const rescheduleDatetime = ref<number | null>(null)
const retryScheduleDatetime = ref<number | null>(null)
const showScheduleDrawer = ref(false)
const scheduledTasksForPreview = ref<Task[]>([])
const scheduledTasksLoading = ref(false)
const slotMaxTasks = ref(0)
const slotEnforce = ref(false)
const taskLogs = ref<TaskLog[]>([])
const activeRetryTask = ref<Task | null>(null)
let pollTimer: number | null = null
let logEventSource: EventSource | null = null
let logStreamContainerId: string | null = null
let structuredLogSse: EventSource | null = null
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
  return ['pending', 'queued', 'running', 'failed', 'cancelled'].includes(task.value.status)
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

function syncRescheduleDatetime() {
  rescheduleDatetime.value = task.value?.scheduled_at ? parseUtcDate(task.value.scheduled_at).getTime() : null
}

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
    const issueId = task.value.issue?.id
    if (issueId) {
      const issueData = await getIssue(issueId)
      if (issueData.tasks) {
        // Find the latest retry task for this task (any status)
        const retryMatch = issueData.tasks
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
}

function connectStructuredLogStream() {
  if (typeof EventSource === 'undefined') return
  if (!isActiveTaskStatus(task.value?.status)) return
  if (structuredLogSse) return // already connected

  const sinceId = taskLogs.value.length > 0
    ? Math.max(...taskLogs.value.map(l => l.id ?? 0))
    : 0

  structuredLogSse = streamTaskLogs(
    taskId.value,
    sinceId,
    (log) => {
      // Avoid duplicates (safety check)
      if (!taskLogs.value.some(l => l.id === log.id)) {
        taskLogs.value = [...taskLogs.value, log]
      }
    },
    () => {
      // SSE signaled task is done
      closeStructuredLogStream()
      fetchTask()
      fetchLogs()
    },
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
    const previousScheduledAt = task.value?.scheduled_at
    task.value = await getTask(taskId.value)
    if (!hasLoadedOnce.value || task.value?.scheduled_at !== previousScheduledAt) {
      syncRescheduleDatetime()
    }

    if (isActiveTaskStatus(previousStatus) && !isActiveTaskStatus(task.value.status)) {
      await fetchLogs()
    }

    // Auto-retry detection: task restarted (non-active → active) while we were watching.
    // Clear stale in-memory logs so the event stream starts fresh.
    if (!isActiveTaskStatus(previousStatus) && isActiveTaskStatus(task.value.status)) {
      resetLogsState()
      connectStructuredLogStream()
    }

    await checkActiveRetry()
  } catch (error) {
    message.error(t('taskView.failedToFetchTask'))
  } finally {
    hasLoadedOnce.value = true
    loading.value = false
    taskRequestInFlight.value = false
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

async function fetchContainerLogs() {
  if (containerRequestInFlight.value) return
  if (!task.value?.container_id) {
    containerLogs.value = ''
    return
  }
  if (typeof EventSource !== 'undefined' && isActiveTaskStatus(task.value.status)) {
    connectLogStream()
    return
  }
  containerRequestInFlight.value = true
  containerLogsLoading.value = true
  try {
    const result = await getTaskContainerLogs(taskId.value)
    containerLogs.value = result.logs
  } catch (error) {
    containerLogs.value = t('taskView.failedToFetchContainerLogs')
  } finally {
    containerLogsLoading.value = false
    containerRequestInFlight.value = false
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
    // Fetch once for completed tasks (DB fallback handles gone containers)
    await fetchContainerLogs()
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

function resetLogsState() {
  taskLogs.value = []
  logs.value = ''
  containerLogs.value = ''
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

async function handleReschedule() {
  if (!rescheduleDatetime.value) {
    message.error(t('taskView.selectRescheduleTime'))
    return
  }

  if (rescheduleDatetime.value <= Date.now()) {
    message.error(t('taskView.rescheduleTimeFuture'))
    return
  }

  actionLoading.value = true
  try {
    task.value = await rescheduleTask(taskId.value, {
      scheduled_datetime: new Date(rescheduleDatetime.value).toISOString()
    })
    syncRescheduleDatetime()
    message.success(t('taskView.taskRescheduled'))
  } catch (error: any) {
    message.error(extractSlotErrorMessage(error, t, 'taskView.failedToRescheduleTask'))
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
  rescheduleDatetime.value = startMs
  showScheduleDrawer.value = false
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

.task-card--equal :deep(.n-card__content) {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.task-prompt-wrap {
  flex: 1;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

.task-prompt-content {
  white-space: pre-wrap;
  line-height: 1.6;
  color: rgba(15, 23, 42, 0.82);
  background: rgba(15, 23, 42, 0.035);
  border-radius: 8px;
  padding: 12px 14px;
  overflow-y: auto;
  max-height: 320px;
  flex: 1;
}

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

.task-actions {
  display: grid;
  gap: 12px;
}

.task-actions__intro {
  padding: 14px 16px;
  border-radius: 14px;
  background: rgba(15, 23, 42, 0.035);
  color: rgba(15, 23, 42, 0.66);
  line-height: 1.5;
}

.task-actions__permission-note {
  padding: 12px 14px;
  border-radius: 14px;
  background: rgba(240, 160, 32, 0.08);
  color: rgba(163, 94, 12, 0.92);
  line-height: 1.5;
}

.task-actions__item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 16px;
  padding: 16px 18px;
  border-radius: 16px;
  border: 1px solid transparent;
  background: rgba(248, 250, 252, 0.9);
}

.task-actions__item--error {
  border-color: rgba(208, 48, 80, 0.14);
  background: linear-gradient(180deg, rgba(208, 48, 80, 0.06), rgba(208, 48, 80, 0.02));
}

.task-actions__item--warning {
  border-color: rgba(240, 160, 32, 0.16);
  background: linear-gradient(180deg, rgba(240, 160, 32, 0.07), rgba(240, 160, 32, 0.025));
}

.task-actions__item--info {
  border-color: rgba(32, 128, 240, 0.16);
  background: linear-gradient(180deg, rgba(32, 128, 240, 0.07), rgba(32, 128, 240, 0.025));
}

.task-actions__meta {
  min-width: 0;
}

.task-actions__controls {
  display: flex;
  flex-direction: column;
  gap: 10px;
  width: fit-content;
  max-width: 100%;
  flex-shrink: 0;
}

.task-actions__controls :deep(.n-button) {
  width: 100%;
}

.task-actions__label {
  font-size: 15px;
  font-weight: 600;
  color: var(--n-text-color-1);
}

.task-actions__description {
  margin-top: 6px;
  font-size: 13px;
  line-height: 1.55;
  color: rgba(15, 23, 42, 0.64);
}

.task-actions__empty {
  padding: 14px 16px;
  border-radius: 14px;
  background: rgba(15, 23, 42, 0.04);
  color: rgba(15, 23, 42, 0.64);
}

@media (max-width: 768px) {
  .task-view__actions {
    width: 100%;
    justify-content: flex-start;
  }

  .task-card__header {
    flex-direction: column;
    align-items: flex-start;
  }

  .task-actions__item {
    flex-direction: column;
    align-items: stretch;
  }

  .task-actions__controls {
    justify-items: stretch;
  }
}
</style>
