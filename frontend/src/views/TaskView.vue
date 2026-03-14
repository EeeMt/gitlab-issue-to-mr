<template>
  <div class="task-view">
    <n-space vertical :size="16">
      <div class="task-view__hero">
        <div>
          <div class="task-view__headline">
            <h2 class="task-view__title">Task #{{ taskId }}</h2>
            <n-tag v-if="task" :type="statusColors[task.status]" round>{{ task.status }}</n-tag>
          </div>
          <p class="task-view__subtitle">
            Inspect execution metadata, logs, and task control actions in one place.
          </p>
        </div>
        <n-button @click="refreshTask" :loading="loading">
          Refresh
        </n-button>
      </div>

      <n-spin :show="loading">
        <n-grid :cols="isMobile ? 2 : 4" :x-gap="16" :y-gap="16" class="task-view__summary" v-if="task">
          <n-gi v-for="item in summaryItems" :key="item.label">
            <n-card size="small" class="task-summary-card" :bordered="false">
              <div class="task-summary-card__label">{{ item.label }}</div>
              <div class="task-summary-card__value">{{ item.value }}</div>
            </n-card>
          </n-gi>
        </n-grid>

        <n-grid :cols="isMobile ? 1 : 2" :x-gap="16" :y-gap="16">
          <n-gi>
            <n-card class="task-card" :bordered="false">
              <template #header>
                <div class="task-card__header">
                  <div>
                    <div class="task-card__title">Task Details</div>
                    <div class="task-card__subtitle">Project, branch, timing, and merge request metadata</div>
                  </div>
                </div>
              </template>
              <n-descriptions :column="1" label-placement="left" v-if="task">
                <n-descriptions-item label="Status">
                  <n-tag :type="statusColors[task.status]">{{ task.status }}</n-tag>
                </n-descriptions-item>
                <n-descriptions-item label="Project">
                  <div>
                    <a v-if="task.project_url" :href="task.project_url" target="_blank" rel="noopener noreferrer" class="app-link">{{ projectDisplayName }}</a>
                    <span v-else>{{ projectDisplayName }}</span>
                  </div>
                  <div style="font-size: 12px; color: #888">ID: {{ task.project_id }}</div>
                </n-descriptions-item>
                <n-descriptions-item label="Issue">
                  <a v-if="task.issue_iid && task.issue_url" :href="task.issue_url" target="_blank" rel="noopener noreferrer" class="app-link">!{{ task.issue_iid }}</a>
                  <span v-else>{{ task.issue_iid ? `!${task.issue_iid}` : '-' }}</span>
                </n-descriptions-item>
                <n-descriptions-item label="Priority">{{ task.priority }}</n-descriptions-item>
                <n-descriptions-item label="Branch">
                  <a v-if="task.branch_name && task.branch_url" :href="task.branch_url" target="_blank" rel="noopener noreferrer" class="app-link">{{ task.branch_name }}</a>
                  <span v-else>{{ task.branch_name || '-' }}</span>
                </n-descriptions-item>
                <n-descriptions-item label="Target Branch">
                  <a v-if="task.target_branch && task.target_branch_url" :href="task.target_branch_url" target="_blank" rel="noopener noreferrer" class="app-link">{{ task.target_branch }}</a>
                  <span v-else>{{ task.target_branch }}</span>
                </n-descriptions-item>
                <n-descriptions-item label="Container ID">{{ task.container_id || '-' }}</n-descriptions-item>
                <n-descriptions-item label="MR URL">
                  <a v-if="task.merge_request_url" :href="task.merge_request_url" target="_blank" rel="noopener noreferrer" class="app-link">{{ task.merge_request_url }}</a>
                  <span v-else>-</span>
                </n-descriptions-item>
                <n-descriptions-item label="Changes">
                  <span v-if="task.additions !== undefined || task.deletions !== undefined">
                    <span v-if="task.additions || task.deletions">
                      <span style="color: #18a053">+{{ task.additions || 0 }}</span>
                      <span style="color: #db3b21; margin-left: 8px">-{{ task.deletions || 0 }}</span>
                      <span style="color: #888; margin-left: 8px">({{ task.total_changes || 0 }} total)</span>
                    </span>
                    <span v-else>-</span>
                  </span>
                  <span v-else>-</span>
                </n-descriptions-item>
                <n-descriptions-item label="Created">{{ formatDate(task.created_at) }}</n-descriptions-item>
                <n-descriptions-item label="Scheduled">{{ task.scheduled_at ? formatDate(task.scheduled_at) : '-' }}</n-descriptions-item>
                <n-descriptions-item label="Started">{{ task.started_at ? formatDate(task.started_at) : '-' }}</n-descriptions-item>
                <n-descriptions-item label="Completed">{{ task.completed_at ? formatDate(task.completed_at) : '-' }}</n-descriptions-item>
              </n-descriptions>
            </n-card>
          </n-gi>

          <n-gi>
            <n-card class="task-card" :bordered="false">
              <template #header>
                <div class="task-card__header">
                  <div>
                    <div class="task-card__title">Actions</div>
                    <div class="task-card__subtitle">Only actions valid for the current task state are shown</div>
                  </div>
                </div>
              </template>

              <div class="task-actions">
                <n-button
                  v-if="task && ['pending', 'queued', 'running'].includes(task.status)"
                  block
                  type="error"
                  @click="handleCancel"
                  :loading="actionLoading"
                >
                  Cancel Task
                </n-button>
                <n-button
                  v-if="task && ['failed', 'cancelled'].includes(task.status)"
                  block
                  type="warning"
                  @click="handleRetry"
                  :loading="actionLoading"
                >
                  Retry Task
                </n-button>
                <n-button
                  v-if="task && task.status === 'pending'"
                  block
                  type="info"
                  @click="handleExecute"
                  :loading="actionLoading"
                >
                  Execute Now
                </n-button>
                <div v-if="!hasActions" class="task-actions__empty">
                  No manual action is available for the current task state.
                </div>
              </div>
            </n-card>

            <n-card class="task-card task-card--spaced" :bordered="false" v-if="task?.error_message">
              <template #header>
                <div class="task-card__header">
                  <div>
                    <div class="task-card__title">Error</div>
                    <div class="task-card__subtitle">Most recent failure reported by the task runner</div>
                  </div>
                </div>
              </template>
              <n-alert type="error">{{ task.error_message }}</n-alert>
            </n-card>
          </n-gi>
        </n-grid>

        <n-card class="task-card" :bordered="false" v-if="task">
          <template #header>
            <div class="task-card__header">
              <div>
                <div class="task-card__title">User Prompt</div>
                <div class="task-card__subtitle">Original instruction captured for this task</div>
              </div>
            </div>
          </template>
          <n-text>{{ task.user_prompt }}</n-text>
        </n-card>

        <n-card class="task-card" :bordered="false">
          <template #header-extra>
            <n-space>
              <n-tag v-if="task?.status === 'running'" type="warning" size="small">Real-time</n-tag>
              <n-button size="small" @click="refreshLogs">Refresh</n-button>
            </n-space>
          </template>
          <template #header>
            <div class="task-card__header">
              <div>
                <div class="task-card__title">Logs</div>
                <div class="task-card__subtitle">Streaming container output for active tasks and stored logs otherwise</div>
              </div>
            </div>
          </template>
          <n-spin :show="logsLoading">
            <!-- Show container logs for running tasks -->
            <div v-if="task?.status === 'running' || task?.status === 'pending' || task?.status === 'queued'">
              <n-spin :show="containerLogsLoading">
                <pre class="log-content">{{ containerLogs || 'Waiting for logs...' }}</pre>
              </n-spin>
            </div>
            <!-- Show database logs for completed/failed tasks -->
            <div v-else>
              <pre class="log-content">{{ logs || 'No logs available' }}</pre>
            </div>
          </n-spin>
        </n-card>
      </n-spin>
    </n-space>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onBeforeUnmount, computed } from 'vue'
import { useRoute } from 'vue-router'
import { NButton, NSpace, NCard, NDescriptions, NDescriptionsItem, NTag, NGrid, NGi, NSpin, NAlert, NText, useMessage } from 'naive-ui'
import { useWindowSize } from '@vueuse/core'
import { getTask, getTaskLogs, getTaskContainerLogs, cancelTask, retryTask, executeTask, type Task } from '../api'
import { formatDateTimeUtc8 } from '../utils/datetime'

const route = useRoute()
const message = useMessage()
const { width } = useWindowSize()
const isMobile = computed(() => width.value < 768)

const taskId = computed(() => Number(route.params.id))

const task = ref<Task | null>(null)
const logs = ref('')
const containerLogs = ref('')
const loading = ref(false)
const logsLoading = ref(false)
const containerLogsLoading = ref(false)
const actionLoading = ref(false)
const taskRequestInFlight = ref(false)
const containerRequestInFlight = ref(false)
let pollTimer: number | null = null
let logEventSource: EventSource | null = null
let logStreamContainerId: string | null = null

const statusColors: Record<string, 'default' | 'info' | 'warning' | 'success' | 'error'> = {
  pending: 'default',
  queued: 'info',
  running: 'warning',
  completed: 'success',
  failed: 'error',
  cancelled: 'default'
}

const projectDisplayName = computed(() => {
  if (!task.value) return '-'
  return task.value.project_path_with_namespace || task.value.project_name || `Project #${task.value.project_id}`
})

const summaryItems = computed(() => {
  if (!task.value) {
    return []
  }

  const changeValue =
    task.value.additions !== undefined || task.value.deletions !== undefined
      ? `${task.value.additions || 0} / ${task.value.deletions || 0}`
      : '-'

  return [
    { label: 'Priority', value: task.value.priority || '-' },
    { label: 'Target Branch', value: task.value.target_branch || '-' },
    { label: 'Merge Request', value: task.value.merge_request_url ? 'Created' : 'Pending' },
    { label: 'Changes (+/-)', value: changeValue }
  ]
})

const hasActions = computed(() => {
  if (!task.value) return false
  return ['pending', 'queued', 'running', 'failed', 'cancelled'].includes(task.value.status)
})

function formatDate(dateStr: string): string {
  return formatDateTimeUtc8(dateStr)
}

function isActiveTaskStatus(status?: string | null): boolean {
  return status === 'running' || status === 'pending' || status === 'queued'
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

  closeLogStream()
  containerLogs.value = ''
  containerLogsLoading.value = true
  logStreamContainerId = containerId
  logEventSource = new EventSource(`/api/containers/${containerId}/logs`)

  logEventSource.onmessage = (event) => {
    containerLogsLoading.value = false
    const chunk = event.data.endsWith('\n') ? event.data : `${event.data}\n`
    containerLogs.value = trimLogBuffer(containerLogs.value + chunk)
  }

  logEventSource.onerror = () => {
    containerLogsLoading.value = false
    if (!isActiveTaskStatus(task.value?.status) || task.value?.container_id !== logStreamContainerId) {
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
    connectLogStream()

    if (isActiveTaskStatus(previousStatus) && !isActiveTaskStatus(task.value.status)) {
      await fetchLogs()
    }
  } catch (error) {
    message.error('Failed to fetch task')
  } finally {
    loading.value = false
    taskRequestInFlight.value = false
  }
}

async function fetchLogs() {
  logsLoading.value = true
  try {
    const logEntries = await getTaskLogs(taskId.value)
    logs.value = logEntries.map(l => `[${l.created_at}] [${l.log_level}] ${l.message}`).join('\n')
  } catch (error) {
    logs.value = 'Failed to fetch logs'
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
    containerLogs.value = 'Failed to fetch container logs'
  } finally {
    containerLogsLoading.value = false
    containerRequestInFlight.value = false
  }
}

async function refreshTask() {
  await fetchTask()
  if (isActiveTaskStatus(task.value?.status)) {
    await fetchContainerLogs()
    return
  }
  await fetchLogs()
}

async function refreshLogs() {
  if (isActiveTaskStatus(task.value?.status)) {
    await fetchContainerLogs()
    return
  }
  await fetchLogs()
}

async function handleCancel() {
  actionLoading.value = true
  try {
    await cancelTask(taskId.value)
    message.success('Task cancelled')
    refreshTask()
  } catch (error) {
    message.error('Failed to cancel task')
  } finally {
    actionLoading.value = false
  }
}

async function handleRetry() {
  actionLoading.value = true
  try {
    await retryTask(taskId.value)
    message.success('Task retry scheduled')
    refreshTask()
  } catch (error) {
    message.error('Failed to retry task')
  } finally {
    actionLoading.value = false
  }
}

async function handleExecute() {
  actionLoading.value = true
  try {
    await executeTask(taskId.value)
    message.success('Task execution started')
    refreshTask()
  } catch (error) {
    message.error('Failed to execute task')
  } finally {
    actionLoading.value = false
  }
}

onMounted(async () => {
  await fetchTask()
  if (isActiveTaskStatus(task.value?.status)) {
    await fetchContainerLogs()
  } else {
    await fetchLogs()
  }
  // Auto-refresh for active tasks; skip when tab is not visible.
  pollTimer = window.setInterval(() => {
    if (document.visibilityState !== 'visible') return
 
    if (isActiveTaskStatus(task.value?.status)) {
      fetchTask()
      if (!logEventSource) {
        fetchContainerLogs()
      }
    } else {
      closeLogStream()
    }
  }, 5000)
})

onBeforeUnmount(() => {
  closeLogStream()
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
  font-family: 'Consolas', 'Monaco', monospace;
  font-size: 12px;
  white-space: pre-wrap;
  word-break: break-all;
}
.task-view {
  max-width: 1240px;
}

.task-view__hero {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  flex-wrap: wrap;
  gap: 16px;
}

.task-view__headline {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 10px;
}

.task-view__title {
  margin: 0;
  font-size: 28px;
  line-height: 1.2;
}

.task-view__subtitle {
  margin: 8px 0 0;
  color: rgba(15, 23, 42, 0.68);
  max-width: 760px;
}

.task-summary-card {
  border-radius: 12px;
  background: linear-gradient(180deg, rgba(32, 128, 240, 0.06), rgba(32, 128, 240, 0.02));
}

.task-summary-card__label {
  margin-bottom: 8px;
  font-size: 12px;
  color: rgba(15, 23, 42, 0.6);
}

.task-summary-card__value {
  font-size: 20px;
  font-weight: 600;
  color: var(--n-text-color-1);
  word-break: break-word;
}

.task-card {
  border-radius: 18px;
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

.task-actions__empty {
  padding: 12px 14px;
  border-radius: 12px;
  background: rgba(15, 23, 42, 0.04);
  color: rgba(15, 23, 42, 0.64);
}

@media (max-width: 768px) {
  .task-view__hero,
  .task-card__header {
    flex-direction: column;
    align-items: flex-start;
  }

  .task-view__title {
    font-size: 24px;
  }
}
</style>
