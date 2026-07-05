<template>
  <div class="task-view" data-testid="task-view-page">
    <n-space vertical :size="16">
      <PageHeader
        data-testid="task-view-header"
        root-class="task-view__hero"
        subtitle-class="task-view__subtitle"
        actions-class="task-view__actions"
      >
        <template #title>
          <h2 class="task-view__title">{{ t('taskView.title', { id: taskId }) }}</h2>
          <n-tag v-if="task" :type="statusColors[task.status]" round>{{ t(`status.${task.status}`) }}</n-tag>
        </template>
        <template v-if="task" #subtitle>
          <div class="task-view__context">
            <a
              v-if="task.project_url"
              :href="task.project_url"
              target="_blank"
              rel="noopener noreferrer"
              class="app-link"
            >{{ taskProjectName }}</a>
            <span v-else>{{ taskProjectName }}</span>
            <span aria-hidden="true">·</span>
            <router-link v-if="task.issue" :to="`/issues/${task.issue.id}`" class="app-link">
              #{{ task.issue.id }} {{ task.issue.title }}
            </router-link>
            <span v-else>{{ t('taskView.manualTask') }}</span>
            <span aria-hidden="true">·</span>
            <span>{{ taskModeLabel }}</span>
            <span aria-hidden="true">·</span>
            <span>{{ t('common.created') }} {{ formatDateTimeUtc8(task.created_at) }}</span>
          </div>
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
                type="primary"
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
                v-if="task?.status === 'pending'"
                class="task-actions__command task-actions__command--primary"
                type="primary"
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

              <n-button
                v-if="task?.status === 'completed'"
                class="task-actions__command task-actions__command--danger"
                type="error"
                secondary
                strong
                :disabled="!canManageTask"
                @click="openOverrideModal('failed')"
              >
                <template #icon><n-icon :component="CloseCircleOutline" /></template>
                {{ t('taskView.markAsFailed') }}
              </n-button>

              <n-button
                v-if="task?.status === 'failed'"
                class="task-actions__command task-actions__command--neutral"
                type="success"
                secondary
                strong
                :disabled="!canManageTask"
                @click="openOverrideModal('completed')"
              >
                <template #icon><n-icon :component="CheckmarkCircleOutline" /></template>
                {{ t('taskView.markAsCompleted') }}
              </n-button>

              <n-tooltip trigger="hover">
                <template #trigger>
                  <n-button
                    class="task-actions__command task-actions__command--neutral task-actions__command--refresh"
                    circle
                    secondary
                    strong
                    :aria-label="t('common.refresh')"
                    @click="refreshTask"
                    :loading="loading"
                  >
                    <template #icon><n-icon :component="RefreshOutline" /></template>
                  </n-button>
                </template>
                {{ t('common.refresh') }}
              </n-tooltip>
            </div>
          </div>
        </template>
      </PageHeader>

      <n-spin :show="initialLoading">
        <div class="task-view__content">
          <div class="task-workbench">
            <main class="task-workbench__main">
              <n-card
                v-if="task && !isTerminal"
                class="task-card task-execution-overview"
                :class="`task-execution-overview--${task.status}`"
                :bordered="false"
                data-testid="task-execution-overview"
              >
                <div class="execution-overview__content">
                  <div class="execution-overview__status-line">
                    <span class="execution-overview__pulse" aria-hidden="true"></span>
                    <span>{{ t('taskView.currentExecution') }}</span>
                  </div>
                  <h3>{{ executionStateTitle }}</h3>
                  <p>{{ executionStateDescription }}</p>
                  <div v-if="executionStateTime" class="execution-overview__meta">
                    <n-icon :component="TimeOutline" size="14" />
                    <span>{{ executionStateTime }}</span>
                  </div>
                </div>
              </n-card>

              <TaskResultPanel
                v-if="task && isTerminal"
                :task="task"
                :delivery-summary-log="deliverySummaryLog"
                :last-assistant-log="lastAssistantLog"
              />

              <n-card
                v-if="task?.user_prompt"
                class="task-card task-prompt-card"
                :bordered="false"
                data-testid="task-prompt-card"
              >
                <template #header>
                  <div class="task-card__header">
                    <div>
                      <div class="task-card__eyebrow">{{ t('taskView.executionInput') }}</div>
                      <div class="task-card__title">{{ t('taskView.runInstruction') }}</div>
                    </div>
                    <div class="task-prompt-card__controls">
                      <div
                        class="task-prompt-view-switch"
                        role="tablist"
                        :aria-label="`${t('taskView.userPrompt')} / ${t('taskView.finalRunPrompt')}`"
                      >
                        <button
                          id="task-prompt-user-tab"
                          type="button"
                          class="task-prompt-view-switch__button"
                          :class="{ 'task-prompt-view-switch__button--active': promptView === 'user' }"
                          role="tab"
                          :aria-selected="promptView === 'user'"
                          aria-controls="task-prompt-panel"
                          @click="promptView = 'user'"
                        >{{ t('taskView.userPrompt') }}</button>
                        <button
                          id="task-prompt-final-tab"
                          type="button"
                          class="task-prompt-view-switch__button"
                          :class="{ 'task-prompt-view-switch__button--active': promptView === 'final' }"
                          role="tab"
                          :aria-selected="promptView === 'final'"
                          aria-controls="task-prompt-panel"
                          @click="promptView = 'final'"
                        >{{ t('taskView.finalRunPrompt') }}</button>
                      </div>
                      <n-tooltip trigger="hover" content-style="font-size: 12px">
                        <template #trigger>
                          <n-button
                            size="small"
                            secondary
                            circle
                            :aria-label="t('taskView.copySource')"
                            @click="copyPromptSource"
                          >
                            <template #icon>
                              <n-icon :component="CopyOutline" />
                            </template>
                          </n-button>
                        </template>
                        {{ t('taskView.copySource') }}
                      </n-tooltip>
                      <n-tooltip trigger="hover">
                        <template #trigger>
                          <n-button
                            class="task-prompt-height-toggle"
                            size="small"
                            secondary
                            circle
                            :aria-label="promptFullHeight ? t('taskView.halfHeight') : t('taskView.fullHeight')"
                            @click="promptFullHeight = !promptFullHeight"
                          >
                            <template #icon>
                              <n-icon :component="promptFullHeight ? ChevronUpOutline : ChevronDownOutline" />
                            </template>
                          </n-button>
                        </template>
                        {{ promptFullHeight ? t('taskView.halfHeight') : t('taskView.fullHeight') }}
                      </n-tooltip>
                    </div>
                  </div>
                </template>
                <div
                  id="task-prompt-panel"
                  class="task-prompt-wrap"
                  :class="{ 'task-prompt-wrap--full': promptFullHeight }"
                  role="tabpanel"
                  :aria-labelledby="promptView === 'user' ? 'task-prompt-user-tab' : 'task-prompt-final-tab'"
                >
                  <n-scrollbar trigger="hover">
                    <div class="task-prompt-content markdown-content" v-html="renderedSelectedPrompt"></div>
                  </n-scrollbar>
                </div>
              </n-card>

              <TaskProcessPanel
                :task="task ?? null"
                :task-logs="taskLogs"
                :is-active="isActiveTaskStatus(task?.status)"
                :terminal-html="terminalLogHtml"
                :task-status="task?.status ?? ''"
                @raw-tab-open="onRawTabOpen"
                @raw-tab-close="onRawTabClose"
              />
            </main>

            <aside class="task-workbench__aside">
              <TaskMetadataPanel v-if="task" :task="task" />

              <TaskRunMetrics
                v-if="task && isTerminal"
                :task="task"
                :context-compact-count="contextCompactCount"
                :skill-usage-stats="skillUsageStats"
              />

              <n-card
                v-if="hasActionDetails"
                class="task-card task-card--actions"
                :bordered="false"
                data-testid="task-actions-card"
              >
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
                    v-if="task && ['failed', 'cancelled'].includes(task.status) && activeRetryTask"
                    class="task-actions__state-note"
                  >
                    <span>{{ t('taskView.retryExistsDescription') }}</span>
                  </div>
                </div>
              </n-card>

              <TaskContinuationPanel
                v-if="task && isTerminal"
                :task="task"
                :can-append-followup-task="canAppendFollowupTask"
                @append-followup-task="showCreateDrawer = true"
              />
            </aside>
          </div>
        </div>
      </n-spin>
    </n-space>
  </div>

  <n-modal
    v-model:show="showOverrideModal"
    preset="card"
    class="config-editor-modal"
    :style="{ width: '480px', maxWidth: 'calc(100vw - 32px)' }"
    :closable="!overrideLoading"
    :mask-closable="!overrideLoading"
  >
    <template #header>
      <span>{{ overrideTargetStatus === 'failed' ? t('taskView.markAsFailed') : t('taskView.markAsCompleted') }}</span>
    </template>
    <n-space vertical :size="16">
      <p class="task-override-modal__description">
        {{ overrideTargetStatus === 'failed' ? t('taskView.markAsFailedConfirm') : t('taskView.markAsCompletedConfirm') }}
      </p>
      <n-input
        v-model:value="overrideReason"
        type="textarea"
        :rows="3"
        :placeholder="t('taskView.overrideReasonPlaceholder')"
        :disabled="overrideLoading"
      />
      <div class="task-override-modal__actions">
        <n-button secondary :disabled="overrideLoading" @click="showOverrideModal = false">
          {{ t('common.cancel') }}
        </n-button>
        <n-button
          :type="overrideTargetStatus === 'failed' ? 'error' : 'success'"
          :loading="overrideLoading"
          @click="confirmOverride"
        >
          {{ t('common.confirm') }}
        </n-button>
      </div>
    </n-space>
  </n-modal>

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

  <TaskFormDrawer
    v-model:show="showCreateDrawer"
    mode="create"
    :issue-id="task?.issue_id"
    :issue-description="issueDescription"
    :default-worker-profile-id="issueDefaultWorkerProfileId"
    :default-provider-id="issueDefaultProviderId"
    data-testid="task-view-create-task-drawer"
    @created="handleAppendTaskCreated"
  />

  <RescheduleDrawer
    v-model:show="showRescheduleDrawer"
    :task="task ?? undefined"
    hide-summary
    @rescheduled="task = $event"
  />
</template>

<script setup lang="ts">
import { ref, onMounted, onBeforeUnmount, computed, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { NButton, NSpace, NCard, NTag, NSpin, NDatePicker, NDrawer, NDrawerContent, NIcon, NInput, NModal, NScrollbar, NTooltip, useMessage } from 'naive-ui'
import { useI18n } from 'vue-i18n'
import { getTask, getTaskLogs, getIssue, getTaskArchive, type Issue, type Task, type TaskLog } from '../api'
import { authState, isAdmin, initializeAuth } from '../auth'
import { renderMarkdown, summarizeSkillUsage } from '../components/task-process/taskProcessUtils'
import PageHeader from '../components/PageHeader.vue'
import TaskMetadataPanel from '../components/TaskMetadataPanel.vue'
import TaskProcessPanel from '../components/TaskProcessPanel.vue'
import TaskResultPanel from '../components/TaskResultPanel.vue'
import TaskRunMetrics from '../components/TaskRunMetrics.vue'
import TaskContinuationPanel from '../components/TaskContinuationPanel.vue'
import { useBreakpoints } from '../composables/useBreakpoints'
import {
  CalendarOutline,
  CheckmarkCircleOutline,
  ChevronDownOutline,
  ChevronUpOutline,
  CloseCircleOutline,
  CopyOutline,
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
import { formatDateTimeUtc8 } from '../utils/datetime'
import { useTaskScheduleContext } from '../features/tasks/useTaskScheduleContext'
import {
  isActiveTaskStatus,
  useTaskLogStreams,
} from '../features/tasks/useTaskLogStreams'
import {
  useTaskViewActions,
  type TaskArchiveMetadata,
} from '../features/tasks/useTaskViewActions'

const ansiConverter = new AnsiToHtml({ escapeXML: true })

const route = useRoute()
const router = useRouter()
const message = useMessage()
const { t } = useI18n()
const { isMobile } = useBreakpoints()

const taskId = computed(() => Number(route.params.id))
const promptView = ref<'user' | 'final'>('user')
const promptFullHeight = ref(false)
const renderedSelectedPrompt = computed(() => {
  if (promptView.value === 'user') return renderMarkdown(task.value?.user_prompt ?? '')
  return renderMarkdown(task.value?.rendered_prompt?.trim() || t('taskView.noFinalRunPrompt'))
})

function copyPromptSource() {
  const source = promptView.value === 'user'
    ? (task.value?.user_prompt ?? '')
    : (task.value?.rendered_prompt ?? '')
  navigator.clipboard.writeText(source)
  message.success(t('taskView.copied'))
}

const task = ref<Task | null>(null)
const logs = ref('')
const containerLogs = ref('')
const loading = ref(false)
const hasLoadedOnce = ref(false)
const logsLoading = ref(false)
const containerLogsLoading = ref(false)
const {
  scheduledTasks: scheduledTasksForPreview,
  scheduledTasksLoading,
  slotMaxTasks,
  slotEnforce,
  loadScheduleContext,
} = useTaskScheduleContext()
const taskLogs = ref<TaskLog[]>([])
const activeRetryTask = ref<Task | null>(null)
const issueTasks = ref<Task[]>([])
const issueDescription = ref<string | undefined>(undefined)
const issueStatus = ref<Issue['status'] | null>(null)
const issueDefaultWorkerProfileId = ref<number | null>(null)
const issueDefaultProviderId = ref<number | null>(null)
const archiveMetadata = ref<TaskArchiveMetadata | null>(null)
let pollTimer: number | null = null
let taskRequestGeneration = 0
let logRequestGeneration = 0
const {
  closeLogStream,
  closeStructuredLogStream,
  shouldStreamRawLogs,
  connectStructuredLogStream,
  fetchRawLogSnapshot,
  reconnectLogStream,
  onRawTabOpen,
  onRawTabClose,
  resetLogStreams,
  hasRawLogStream,
  hasStructuredLogStream,
  isRawLogTabOpen,
} = useTaskLogStreams({
  taskId,
  task,
  taskLogs,
  containerLogs,
  containerLogsLoading,
  translate: t,
  onStructuredDone: () => {
    void fetchTask()
    void fetchLogs()
  },
  onRawDone: () => {
    void fetchTask()
  },
})
const {
  actionLoading,
  archiveDownloadLoading,
  confirmOverride,
  handleAppendTaskCreated,
  handleCancel,
  handleDownloadArchive,
  handleExecute,
  handleRetry,
  handleRetryWithSchedule,
  handleScheduleHeatmapCellClick,
  openOverrideModal,
  openScheduleDrawer,
  overrideLoading,
  overrideReason,
  overrideTargetStatus,
  retryScheduleDatetime,
  showCreateDrawer,
  showEditDrawer,
  showOverrideModal,
  showRescheduleDrawer,
  showScheduleDrawer,
} = useTaskViewActions({
  taskId,
  task,
  archiveMetadata,
  refreshTask: () => refreshTask(),
  resetLogsState: () => resetLogsState(),
  checkActiveRetry: () => checkActiveRetry(),
  loadScheduleContext,
})
watch(taskId, () => {
  promptView.value = 'user'
  promptFullHeight.value = false
})
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

const contextCompactCount = computed(() =>
  taskLogs.value.filter(l => l.log_type === 'context_compact').length
)

const skillUsageStats = computed(() =>
  summarizeSkillUsage(taskLogs.value)
)

const lastAssistantLog = computed(() =>
  [...taskLogs.value].reverse().find(l => l.log_type === 'assistant_text') ?? null
)

const deliverySummaryLog = computed(() =>
  [...taskLogs.value].reverse().find(l => l.log_type === 'delivery_summary') ?? null
)

const taskProjectName = computed(() => {
  if (!task.value) return '-'
  return task.value.project_path_with_namespace
    || task.value.project_name
    || `Project #${task.value.project_id}`
})

const taskModeLabel = computed(() =>
  task.value?.task_mode === 'plan'
    ? t('taskView.taskModePlan')
    : t('taskView.taskModeExecute')
)

const executionStateTitle = computed(() => {
  if (!task.value) return ''
  return t(`taskView.executionState.${task.value.status}Title`)
})

const executionStateDescription = computed(() => {
  if (!task.value) return ''
  return t(`taskView.executionState.${task.value.status}Description`)
})

const executionStateTime = computed(() => {
  if (!task.value) return ''
  if (task.value.status === 'pending' && task.value.scheduled_at) {
    return `${t('common.scheduledAt')} ${formatDateTimeUtc8(task.value.scheduled_at)}`
  }
  if (task.value.status === 'running' && task.value.started_at) {
    return `${t('common.started')} ${formatDateTimeUtc8(task.value.started_at)}`
  }
  if (task.value.status === 'cancelled' && task.value.completed_at) {
    return `${t('common.completed')} ${formatDateTimeUtc8(task.value.completed_at)}`
  }
  return ''
})

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
  return ['pending', 'queued', 'running', 'completed', 'failed', 'cancelled'].includes(task.value.status)
})

const hasActionDetails = computed(() => {
  if (!task.value) return false

  const retryHasContext = ['failed', 'cancelled'].includes(task.value.status) && !!activeRetryTask.value

  return (
    (hasActions.value && !canManageTask.value) ||
    (!!archiveMetadata.value && !archiveMetadata.value.file_exists) ||
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

const latestIssueTask = computed(() => {
  return issueTasks.value.reduce<Task | null>((latest, item) => {
    if (!latest) return item
    const createdDelta = new Date(item.created_at).getTime() - new Date(latest.created_at).getTime()
    if (createdDelta !== 0) return createdDelta > 0 ? item : latest
    return item.id > latest.id ? item : latest
  }, null)
})

const isLatestIssueTask = computed(() =>
  latestIssueTask.value?.id === task.value?.id
)

const canAppendFollowupTask = computed(() =>
  isTerminal.value
  && isLatestIssueTask.value
  && issueStatus.value !== 'closed'
  && canManageTask.value
)


function isScheduledDateDisabled(timestamp: number): boolean {
  const candidate = new Date(timestamp)
  const today = new Date()

  candidate.setHours(0, 0, 0, 0)
  today.setHours(0, 0, 0, 0)

  return candidate.getTime() < today.getTime()
}

async function checkActiveRetry() {
  if (!task.value || !['failed', 'cancelled'].includes(task.value.status)) {
    activeRetryTask.value = null
    return
  }
  try {
    const issueId = task.value.issue_id
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

async function refreshIssueTasks(requestedTaskId: number) {
  const issueId = task.value?.issue_id
  if (!issueId) {
    issueTasks.value = []
    issueDescription.value = undefined
    issueStatus.value = null
    issueDefaultWorkerProfileId.value = null
    issueDefaultProviderId.value = null
    return
  }
  try {
    const issueData = await getIssue(issueId)
    if (requestedTaskId !== taskId.value || task.value?.issue_id !== issueId) return
    issueTasks.value = issueData.tasks ?? []
    issueDescription.value = issueData.description ?? undefined
    issueStatus.value = issueData.status ?? null
    issueDefaultWorkerProfileId.value = issueData.default_worker_profile_id ?? null
    issueDefaultProviderId.value = issueData.default_provider_id ?? null
  } catch {
    if (requestedTaskId !== taskId.value || task.value?.issue_id !== issueId) return
    issueTasks.value = []
    issueDescription.value = undefined
    issueStatus.value = null
    issueDefaultWorkerProfileId.value = null
    issueDefaultProviderId.value = null
  }
}

async function fetchTask(): Promise<boolean> {
  const requestGeneration = ++taskRequestGeneration
  const requestedTaskId = taskId.value
  loading.value = true
  try {
    const previousStatus = task.value?.status
    const fetchedTask = await getTask(requestedTaskId)
    if (requestGeneration !== taskRequestGeneration || requestedTaskId !== taskId.value) {
      return false
    }
    task.value = fetchedTask

    if (isActiveTaskStatus(previousStatus) && !isActiveTaskStatus(task.value.status)) {
      await fetchLogs()
      if (requestGeneration !== taskRequestGeneration || requestedTaskId !== taskId.value) {
        return false
      }
      if (isRawLogTabOpen()) await fetchRawLogSnapshot()
      if (requestGeneration !== taskRequestGeneration || requestedTaskId !== taskId.value) {
        return false
      }
    }

    // Auto-retry detection: task restarted (non-active → active) while we were watching.
    // Clear stale in-memory logs so the event stream starts fresh.
    if (!isActiveTaskStatus(previousStatus) && isActiveTaskStatus(task.value.status)) {
      resetLogsState()
      connectStructuredLogStream()
    }

    await refreshIssueTasks(requestedTaskId)
    if (requestGeneration !== taskRequestGeneration || requestedTaskId !== taskId.value) {
      return false
    }
    await checkActiveRetry()
    void fetchArchiveMetadata(requestedTaskId)
    return true
  } catch {
    if (requestGeneration === taskRequestGeneration && requestedTaskId === taskId.value) {
      message.error(t('taskView.failedToFetchTask'))
    }
    return false
  } finally {
    if (requestGeneration === taskRequestGeneration) {
      hasLoadedOnce.value = true
      loading.value = false
    }
  }
}

async function fetchArchiveMetadata(requestedTaskId = taskId.value) {
  if (!task.value || task.value.id !== requestedTaskId || !isTerminal.value) {
    if (requestedTaskId === taskId.value) archiveMetadata.value = null
    return
  }
  try {
    const metadata = await getTaskArchive(requestedTaskId)
    if (requestedTaskId === taskId.value && task.value?.id === requestedTaskId) {
      archiveMetadata.value = metadata
    }
  } catch {
    if (requestedTaskId === taskId.value && task.value?.id === requestedTaskId) {
      archiveMetadata.value = null
    }
  }
}

async function fetchLogs(): Promise<boolean> {
  const requestGeneration = ++logRequestGeneration
  const requestedTaskId = taskId.value
  logsLoading.value = true
  try {
    const logEntries = await getTaskLogs(requestedTaskId)
    if (requestGeneration !== logRequestGeneration || requestedTaskId !== taskId.value) {
      return false
    }
    taskLogs.value = logEntries
    logs.value = logEntries.map(l => `[${l.created_at}] [${l.log_level}] ${l.message}`).join('\n')
    return true
  } catch {
    if (requestGeneration === logRequestGeneration && requestedTaskId === taskId.value) {
      logs.value = t('taskView.failedToFetchLogs')
    }
    return false
  } finally {
    if (requestGeneration === logRequestGeneration) {
      logsLoading.value = false
    }
  }
}

async function refreshTask() {
  const requestedTaskId = taskId.value
  const loaded = await fetchTask()
  if (loaded && requestedTaskId === taskId.value && !isActiveTaskStatus(task.value?.status)) {
    await fetchLogs()
  }
}

async function loadTaskView() {
  const requestedTaskId = taskId.value
  const loaded = await fetchTask()
  if (!loaded || requestedTaskId !== taskId.value) return
  await fetchLogs()
  if (requestedTaskId === taskId.value && isActiveTaskStatus(task.value?.status)) {
    connectStructuredLogStream()
  }
}

function resetLogsState() {
  logRequestGeneration += 1
  taskLogs.value = []
  logs.value = ''
  containerLogs.value = ''
  archiveMetadata.value = null
  resetLogStreams()
}

onMounted(async () => {
  await initializeAuth()
  await loadTaskView()
  pollTimer = window.setInterval(() => {
    if (document.visibilityState !== 'visible') return

    if (isActiveTaskStatus(task.value?.status)) {
      fetchTask()
      if (!hasStructuredLogStream()) connectStructuredLogStream()
      if (isRawLogTabOpen() && !hasRawLogStream()) void reconnectLogStream()
    } else {
      closeStructuredLogStream()
      if (isRawLogTabOpen() && shouldStreamRawLogs()) {
        if (!hasRawLogStream()) void reconnectLogStream()
      } else {
        closeLogStream()
      }
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
      issueDescription.value = undefined
      issueStatus.value = null
      archiveMetadata.value = null
      showCreateDrawer.value = false
      showRescheduleDrawer.value = false
      showScheduleDrawer.value = false
      hasLoadedOnce.value = false
      void loadTaskView()
    }
  }
)

onBeforeUnmount(() => {
  taskRequestGeneration += 1
  logRequestGeneration += 1
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
  border-radius: 8px;
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

.task-view__context {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 8px;
  flex-wrap: wrap;
  color: var(--app-page-subtitle-color, rgba(15, 23, 42, 0.58));
  font-size: 13px;
  line-height: 1.45;
}

.app-link {
  color: var(--n-primary-color, #18a058);
  text-decoration: none;
}

.app-link:hover {
  text-decoration: underline;
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
  min-width: 0;
}

.task-view__title {
  margin: 0;
  font-size: var(--app-page-title-size);
  line-height: 1.2;
}

.task-card {
  border-radius: var(--app-card-radius);
}

.task-workbench {
  display: grid;
  grid-template-columns: minmax(0, 2fr) minmax(300px, 1fr);
  gap: 16px;
  align-items: start;
}

.task-workbench__main,
.task-workbench__aside {
  display: grid;
  gap: 16px;
  min-width: 0;
  max-width: 100%;
}

.task-workbench__main > *,
.task-workbench__aside > * {
  min-width: 0;
  max-width: 100%;
}

.task-workbench__aside {
  position: sticky;
  top: 16px;
}

.task-execution-overview {
  --execution-accent: #64748b;

  position: relative;
  overflow: hidden;
}

.task-execution-overview::before {
  position: absolute;
  inset: 0 auto 0 0;
  width: 3px;
  background: var(--execution-accent);
  content: '';
}

.task-execution-overview--queued {
  --execution-accent: #0284c7;
}

.task-execution-overview--running {
  --execution-accent: #d97706;
}

.task-execution-overview--cancelled {
  --execution-accent: #94a3b8;
}

.execution-overview__content {
  padding: 2px 2px 2px 4px;
}

.execution-overview__status-line {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  color: var(--execution-accent);
  font-size: 12px;
  font-weight: 600;
}

.execution-overview__pulse {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: currentColor;
}

.task-execution-overview--running .execution-overview__pulse {
  animation: execution-pulse 1.8s ease-in-out infinite;
}

.execution-overview__content h3 {
  margin: 10px 0 6px;
  color: var(--n-text-color-1);
  font-size: 20px;
  line-height: 1.35;
}

.execution-overview__content p {
  margin: 0;
  color: var(--n-text-color-2);
  font-size: 13px;
  line-height: 1.6;
}

.execution-overview__meta {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  margin-top: 12px;
  color: var(--n-text-color-3, #8a8f98);
  font-size: 12px;
}

@keyframes execution-pulse {
  0%, 100% { opacity: 0.42; transform: scale(0.88); }
  50% { opacity: 1; transform: scale(1); }
}

.task-prompt-wrap {
  background: rgba(15, 23, 42, 0.035);
  border-radius: 6px;
  overflow: hidden;
  height: min(260px, 38vh);
}

.task-prompt-wrap--full {
  height: min(560px, 68vh);
}

.task-prompt-wrap :deep(.n-scrollbar) {
  height: 100%;
}

.task-prompt-view-switch {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  padding: 2px;
  border: 1px solid rgba(148, 163, 184, 0.18);
  border-radius: 7px;
  background: rgba(148, 163, 184, 0.1);
}

.task-prompt-view-switch__button {
  min-height: 24px;
  padding: 3px 9px;
  border: 0;
  border-radius: 5px;
  background: transparent;
  color: rgba(15, 23, 42, 0.58);
  font: inherit;
  font-size: 12px;
  font-weight: 500;
  line-height: 18px;
  white-space: nowrap;
  cursor: pointer;
  transition: background-color 0.16s ease, color 0.16s ease, box-shadow 0.16s ease;
}

.task-prompt-view-switch__button:hover {
  color: rgba(15, 23, 42, 0.84);
}

.task-prompt-view-switch__button--active {
  background: rgba(255, 255, 255, 0.92);
  color: rgba(15, 23, 42, 0.88);
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.1);
}

.task-prompt-view-switch__button:focus-visible {
  outline: 2px solid rgba(32, 128, 240, 0.32);
  outline-offset: 1px;
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
  align-items: center;
  gap: 12px;
}

.task-card__title {
  font-size: 16px;
  font-weight: 600;
  line-height: 1.35;
}

.task-card__eyebrow {
  margin-bottom: 3px;
  color: var(--n-text-color-3, #8a8f98);
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0;
  text-transform: uppercase;
}

.task-card__subtitle {
  margin-top: 4px;
  font-size: 13px;
  color: rgba(15, 23, 42, 0.58);
}

.task-prompt-card__controls {
  display: flex;
  align-items: center;
  gap: 8px;
}

.task-prompt-height-toggle {
  flex: 0 0 auto;
  --n-height: 28px !important;
  --n-width: 28px !important;
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
  --n-border-radius: 8px !important;
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
  min-width: 104px;
  box-shadow: 0 7px 18px rgba(24, 160, 88, 0.15);
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
  --n-width: 34px !important;
  --n-padding: 0 !important;
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
  padding: 10px 12px;
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

.task-override-modal__description {
  margin: 0;
  color: var(--n-text-color-2);
  font-size: 14px;
  line-height: 1.6;
}

.task-override-modal__actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
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

@media (max-width: 1024px) {
  .task-workbench {
    grid-template-columns: 1fr;
  }

  .task-workbench__aside {
    position: static;
  }
}

@media (max-width: 768px) {
  .task-view__actions {
    width: 100%;
    justify-content: flex-start;
    flex-basis: auto;
  }

  .task-card__header {
    align-items: flex-start;
  }

  .task-actions__toolbar {
    align-items: stretch;
    justify-content: flex-start;
  }

  .task-actions__command,
  .task-actions__linked-task {
    flex: 0 1 auto;
    justify-content: center;
  }

  .task-prompt-card__controls {
    align-items: flex-start;
  }

  .task-prompt-wrap {
    height: min(240px, 36vh);
  }

  .task-prompt-wrap--full {
    height: min(440px, 62vh);
  }

  .task-schedule-drawer__form .task-actions__date-picker {
    width: 100%;
  }

  .task-schedule-drawer__actions :deep(.n-button) {
    flex: 1 1 140px;
  }
}

@media (prefers-reduced-motion: reduce) {
  .task-execution-overview--running .execution-overview__pulse {
    animation: none;
  }

}
</style>
