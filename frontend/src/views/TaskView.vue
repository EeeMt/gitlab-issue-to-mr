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
          <n-grid
            :cols="isMobile ? 2 : 4"
            :x-gap="16"
            :y-gap="16"
            class="task-view__summary"
            data-testid="task-view-summary"
            v-if="task"
          >
            <n-gi v-for="item in summaryItems" :key="item.label">
              <SummaryCard
                :label="item.label"
                :value="item.value"
                data-testid="task-view-summary-card"
                card-class="task-summary-card"
                label-class="task-summary-card__label"
                value-class="task-summary-card__value"
              />
            </n-gi>
          </n-grid>

          <n-grid :cols="isMobile ? 1 : 2" :x-gap="16" :y-gap="16">
            <n-gi>
              <n-card class="task-card" :bordered="false" data-testid="task-details-card">
                <template #header>
                  <div class="task-card__header">
                    <div>
                      <div class="task-card__title">{{ t('taskView.taskDetails') }}</div>
                      <div class="task-card__subtitle">{{ t('taskView.taskDetailsSubtitle') }}</div>
                    </div>
                  </div>
                </template>
                <n-descriptions :column="1" label-placement="left" v-if="task">
                  <n-descriptions-item :label="t('common.status')">
                    <n-tag :type="statusColors[task.status]">{{ t(`status.${task.status}`) }}</n-tag>
                  </n-descriptions-item>
                  <n-descriptions-item :label="t('common.project')">
                    <div>
                      <a v-if="task.project_url" :href="task.project_url" target="_blank" rel="noopener noreferrer" class="app-link">{{ projectDisplayName }}</a>
                      <span v-else>{{ projectDisplayName }}</span>
                    </div>
                    <div style="font-size: 12px; color: #888">ID: {{ task.project_id }}</div>
                  </n-descriptions-item>
                  <n-descriptions-item :label="t('common.issue')">
                    <a v-if="task.issue_iid && task.issue_url" :href="task.issue_url" target="_blank" rel="noopener noreferrer" class="app-link">!{{ task.issue_iid }}</a>
                    <span v-else>{{ task.issue_iid ? `!${task.issue_iid}` : '-' }}</span>
                  </n-descriptions-item>
                  <n-descriptions-item :label="t('common.priority')">{{ formatPriority(task.priority) }}</n-descriptions-item>
                  <n-descriptions-item :label="t('common.initiator')">
                    <n-tag v-if="task.initiator_username" :type="task.is_manual ? 'info' : 'success'" size="small" round>
                      <template #icon>
                        <n-icon :component="task.is_manual ? PersonOutline : LogoGitlab" />
                      </template>
                      {{ task.initiator_username }}
                    </n-tag>
                    <span v-else>-</span>
                  </n-descriptions-item>
                  <n-descriptions-item :label="t('common.branch')">
                    <a v-if="task.branch_name && task.branch_url" :href="task.branch_url" target="_blank" rel="noopener noreferrer" class="app-link">{{ task.branch_name }}</a>
                    <span v-else>{{ task.branch_name || '-' }}</span>
                  </n-descriptions-item>
                  <n-descriptions-item :label="t('common.targetBranch')">
                    <a v-if="task.target_branch && task.target_branch_url" :href="task.target_branch_url" target="_blank" rel="noopener noreferrer" class="app-link">{{ task.target_branch }}</a>
                    <span v-else>{{ task.target_branch }}</span>
                  </n-descriptions-item>
                  <n-descriptions-item :label="t('taskView.containerId')">
                    <n-tooltip v-if="task.container_id" trigger="hover" placement="top">
                      <template #trigger>
                        <code style="cursor: default; font-family: monospace; font-size: 12px;">{{ task.container_id.slice(0, 12) }}</code>
                      </template>
                      {{ task.container_id }}
                    </n-tooltip>
                    <span v-else>-</span>
                  </n-descriptions-item>
                  <n-descriptions-item :label="t('taskView.mrUrl')">
                    <a v-if="task.merge_request_url" :href="task.merge_request_url" target="_blank" rel="noopener noreferrer" class="app-link">{{ task.merge_request_url }}</a>
                    <n-tag v-else-if="task.target_branch === null" size="small" type="default" :bordered="false" style="color: #888; background: #f0f0f0;">
                      {{ t('taskView.noMrSkipped') }}
                    </n-tag>
                    <span v-else>-</span>
                  </n-descriptions-item>
                  <n-descriptions-item :label="t('common.changes')">
                    <span v-if="task.additions !== undefined || task.deletions !== undefined">
                      <span v-if="task.additions || task.deletions">
                        <span style="color: #18a053">+{{ task.additions || 0 }}</span>
                        <span style="color: #db3b21; margin-left: 8px">-{{ task.deletions || 0 }}</span>
                        <span style="color: #888; margin-left: 8px">({{ t('taskView.totalSuffix', { total: task.total_changes || 0 }) }})</span>
                      </span>
                      <span v-else>-</span>
                    </span>
                    <span v-else>-</span>
                  </n-descriptions-item>
                  <n-descriptions-item :label="t('taskView.tokenUsage')">
                    <span v-if="task.input_tokens != null || task.output_tokens != null">
                      <span style="color: #888">{{ t('taskView.inputTokens') }}:</span>
                      <span style="margin-left: 4px">{{ (task.input_tokens ?? 0).toLocaleString() }}</span>
                      <span style="color: #888; margin-left: 12px">{{ t('taskView.outputTokens') }}:</span>
                      <span style="margin-left: 4px">{{ (task.output_tokens ?? 0).toLocaleString() }}</span>
                    </span>
                    <span v-else>-</span>
                  </n-descriptions-item>
                  <n-descriptions-item :label="t('common.created')">{{ formatDate(task.created_at) }}</n-descriptions-item>
                  <n-descriptions-item :label="t('common.scheduled')">{{ task.scheduled_at ? formatDate(task.scheduled_at) : '-' }}</n-descriptions-item>
                  <n-descriptions-item :label="t('common.started')">{{ task.started_at ? formatDate(task.started_at) : '-' }}</n-descriptions-item>
                  <n-descriptions-item :label="t('common.completed')">{{ task.completed_at ? formatDate(task.completed_at) : '-' }}</n-descriptions-item>
                </n-descriptions>
              </n-card>
            </n-gi>

            <n-gi>
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

                  <div
                    v-if="task && ['failed', 'cancelled'].includes(task.status)"
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
                    v-if="task && ['failed', 'cancelled'].includes(task.status)"
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

                  <div v-if="!hasActions" class="task-actions__empty">
                    {{ t('taskView.noManualAction') }}
                  </div>
                </div>
              </n-card>

              <n-card class="task-card task-card--spaced" :bordered="false" v-if="task?.error_message">
                <template #header>
                  <div class="task-card__header">
                    <div>
                        <div class="task-card__title">{{ t('taskView.error') }}</div>
                        <div class="task-card__subtitle">{{ t('taskView.errorSubtitle') }}</div>
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
                    <div class="task-card__title">{{ t('taskView.userPrompt') }}</div>
                    <div class="task-card__subtitle">{{ t('taskView.userPromptSubtitle') }}</div>
                  </div>
                </div>
            </template>
            <n-text>{{ task.user_prompt }}</n-text>
          </n-card>

          <n-card class="task-card" :bordered="false">
            <template #header-extra>
              <n-space>
                <n-tag v-if="task?.status === 'running'" type="warning" size="small">{{ t('taskView.realTime') }}</n-tag>
                <n-button size="small" @click="refreshLogs">{{ t('common.refresh') }}</n-button>
              </n-space>
            </template>
            <template #header>
              <div class="task-card__header">
                <div>
                  <div class="task-card__title">{{ t('taskView.logs') }}</div>
                  <div class="task-card__subtitle">{{ t('taskView.logsSubtitle') }}</div>
                </div>
              </div>
            </template>
            <n-spin :show="logsLoading">
              <!-- DB log entries are streamed every ~10s during execution,
                   so the same <pre> works for both running and completed tasks. -->
              <pre
                class="log-content"
                v-if="renderedLogs"
                v-html="renderedLogs"
              ></pre>
              <pre class="log-content" v-else>{{ isActiveTaskStatus(task?.status) ? t('taskView.waitingForLogs') : t('taskView.noLogsAvailable') }}</pre>
            </n-spin>
          </n-card>
        </div>
      </n-spin>
    </n-space>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onBeforeUnmount, computed } from 'vue'
import { useRoute } from 'vue-router'
import { NButton, NSpace, NCard, NDescriptions, NDescriptionsItem, NTag, NGrid, NGi, NSpin, NAlert, NText, NDatePicker, NTooltip, useMessage, NIcon } from 'naive-ui'
import { PersonOutline, LogoGitlab } from '@vicons/ionicons5'
import { useI18n } from 'vue-i18n'
import { getTask, getTaskLogs, getTaskContainerLogs, cancelTask, retryTask, executeTask, rescheduleTask, type Task } from '../api'
import { authState, isAdmin, initializeAuth } from '../auth'
import PageHeader from '../components/PageHeader.vue'
import SummaryCard from '../components/SummaryCard.vue'
import { useBreakpoints } from '../composables/useBreakpoints'
import { formatDateTimeUtc8, parseUtcDate } from '../utils/datetime'
import AnsiToHtml from 'ansi-to-html'

const ansiConverter = new AnsiToHtml({ escapeXML: true })

const route = useRoute()
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
let pollTimer: number | null = null
let logEventSource: EventSource | null = null
let logStreamContainerId: string | null = null
const initialLoading = computed(() => loading.value && !hasLoadedOnce.value)

const renderedLogs = computed(() => {
  const text = logs.value
  if (!text) return ''
  return ansiConverter.toHtml(text)
})

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
  return task.value.project_path_with_namespace || task.value.project_name || t('dashboard.projectFallback', { id: task.value.project_id })
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
    { label: t('common.priority'), value: formatPriority(task.value.priority) },
    { label: t('common.targetBranch'), value: task.value.target_branch || '-' },
    { label: t('common.mergeRequest'), value: task.value.merge_request_url ? t('taskView.mergeRequestCreated') : task.value.target_branch === null ? t('taskView.noMrSkipped') : t('taskView.mergeRequestPending') },
    { label: `${t('common.changes')} (+/-)`, value: changeValue }
  ]
})

const hasActions = computed(() => {
  if (!task.value) return false
  return ['pending', 'queued', 'running', 'failed', 'cancelled'].includes(task.value.status)
})

const canReschedule = computed(() => task.value?.status === 'pending' && !!task.value?.scheduled_at)
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

function formatDate(dateStr: string): string {
  return formatDateTimeUtc8(dateStr)
}

function formatPriority(priority?: string | number | null): string {
  if (priority === null || priority === undefined || priority === '') {
    return '-'
  }

  const normalized = String(priority).toLowerCase().trim()

  if (normalized === '0' || normalized === 'p0') return 'P0'
  if (normalized === '1' || normalized === 'p1') return 'P1'
  if (normalized === '2' || normalized === 'p2') return 'P2'

  return String(priority)
}

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
    // If we never received data, this is likely an auth failure (403) — close
    // the stream to avoid infinite reconnect loops for non-admin users.
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
    // Only sync the date picker when loading for the first time or when scheduled_at
    // changed externally (not during user editing).
    if (!hasLoadedOnce.value || task.value?.scheduled_at !== previousScheduledAt) {
      syncRescheduleDatetime()
    }
    connectLogStream()

    if (isActiveTaskStatus(previousStatus) && !isActiveTaskStatus(task.value.status)) {
      await fetchLogs()
    }
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
    message.success(t('taskView.taskCancelled'))
    refreshTask()
  } catch (error) {
    message.error(t('taskView.failedToCancelTask'))
  } finally {
    actionLoading.value = false
  }
}

async function handleRetry() {
  actionLoading.value = true
  try {
    await retryTask(taskId.value)
    message.success(t('taskView.taskRetryScheduled'))
    refreshTask()
  } catch (error) {
    message.error(t('taskView.failedToRetryTask'))
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
    await retryTask(taskId.value, new Date(retryScheduleDatetime.value).toISOString())
    retryScheduleDatetime.value = null
    message.success(t('taskView.taskRetryRescheduled'))
    refreshTask()
  } catch (error) {
    message.error(t('taskView.failedToRetryTask'))
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
  } catch (error) {
    message.error(t('taskView.failedToRescheduleTask'))
  } finally {
    actionLoading.value = false
  }
}

onMounted(async () => {
  await initializeAuth()
  await fetchTask()
  if (isActiveTaskStatus(task.value?.status)) {
    await fetchContainerLogs()
  }
  await fetchLogs()
  // Auto-refresh for active tasks; skip when tab is not visible.
  pollTimer = window.setInterval(() => {
    if (document.visibilityState !== 'visible') return
 
    if (isActiveTaskStatus(task.value?.status)) {
      fetchTask()
      if (!logEventSource) {
        fetchContainerLogs()
      }
      fetchLogs()  // Poll DB logs so non-admin users see streaming chunks
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

/* Summary cards are rendered inside SummaryCard's scope; use :deep() to cross the boundary */
:deep(.task-summary-card) {
  min-height: 100%;
}

:deep(.task-summary-card__label) {
  text-align: center;
}

:deep(.task-summary-card__value) {
  text-align: center;
  word-break: break-word;
}

.task-card {
  border-radius: var(--app-card-radius);
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
