<template>
  <div v-if="issue" class="issue-view" data-testid="issue-view-page">
    <n-space vertical :size="16">
      <!-- Header -->
      <PageHeader
        data-testid="issue-view-header"
        root-class="issue-view__hero"
        actions-class="issue-view__actions"
      >
        <template #title>
          <h2 class="issue-view__title">#{{ issue.id }} {{ issue.title }}</h2>
          <n-tag :type="issueStatusColors[issue.status]" round>
            {{ t(`issue.status.${issue.status}`) }}
          </n-tag>
        </template>
        <template #subtitle>
          <div class="issue-view__context">
            <a v-if="projectUrl" :href="projectUrl" target="_blank" rel="noopener noreferrer" class="app-link">
              {{ projectName }}
            </a>
            <span v-else>{{ projectName }}</span>
            <span aria-hidden="true">·</span>
            <span>{{ issue.initiator_username || '—' }}</span>
            <span aria-hidden="true">·</span>
            <span>{{ t('issue.field.updatedAt') }} {{ formatCompactDateTime(issue.updated_at) }}</span>
          </div>
        </template>
        <template #actions>
          <div class="issue-actions issue-actions--header" data-testid="issue-actions">
            <div class="issue-actions__toolbar">
              <n-tooltip
                v-if="isOwner && issue.status !== 'closed' && issue.tasks?.length"
                trigger="hover"
                placement="top"
                :content-style="issueDetailTooltipContentStyle"
                :theme-overrides="issueDetailTooltipThemeOverrides"
              >
                <template #trigger>
                  <n-button
                    class="issue-actions__command issue-actions__command--primary"
                    type="primary"
                    strong
                    data-testid="issue-toggle-create-task"
                    @click="showCreateDrawer = true"
                  >
                    <template #icon><n-icon :component="AddOutline" /></template>
                    {{ t('issue.appendTask') }}
                  </n-button>
                </template>
                {{ t('issue.appendTaskHint') }}
              </n-tooltip>
              <n-button
                v-else-if="isOwner && issue.status !== 'closed'"
                class="issue-actions__command issue-actions__command--primary"
                type="primary"
                strong
                data-testid="issue-toggle-create-task"
                @click="showCreateDrawer = true"
              >
                <template #icon><n-icon :component="AddOutline" /></template>
                {{ t('issue.createTask') }}
              </n-button>
              <template v-if="isOwner">
                <n-button
                  class="issue-actions__command issue-actions__command--danger"
                  type="error"
                  secondary
                  strong
                  :disabled="issue.status === 'closed' || closingIssue"
                  :loading="closingIssue"
                  data-testid="issue-close-button"
                  @click="showCloseModal = true"
                >
                  <template #icon><n-icon :component="CloseCircleOutline" /></template>
                  {{ t('issue.close') }}
                </n-button>
                <n-tooltip
                  v-if="issue.status === 'closed' && issue.branch_name && issue.branch_deleted"
                  :title="t('issue.branchAlreadyDeleted')"
                  :content-style="issueDetailTooltipContentStyle"
                  :theme-overrides="issueDetailTooltipThemeOverrides"
                >
                  <template #trigger>
                    <n-button
                      class="issue-actions__command issue-actions__command--danger"
                      data-testid="issue-delete-branch-button"
                      type="error"
                      secondary
                      strong
                      :disabled="deletingBranch || issue.branch_deleted"
                      :loading="deletingBranch"
                      @click="handleDeleteBranch"
                    >
                      <template #icon><n-icon :component="TrashOutline" /></template>
                      {{ t('issue.deleteBranch') }}
                    </n-button>
                  </template>
                  {{ t('issue.branchAlreadyDeleted') }}
                </n-tooltip>
                <n-popconfirm
                  v-else-if="issue.status === 'closed' && issue.branch_name"
                  @positive-click="handleDeleteBranch"
                >
                  <template #trigger>
                    <n-button
                      class="issue-actions__command issue-actions__command--danger"
                      data-testid="issue-delete-branch-button"
                      type="error"
                      secondary
                      strong
                      :disabled="deletingBranch"
                      :loading="deletingBranch"
                    >
                      <template #icon><n-icon :component="TrashOutline" /></template>
                      {{ t('issue.deleteBranch') }}
                    </n-button>
                  </template>
                  {{ t('issue.deleteBranchConfirm', { branch: issue.branch_name }) }}
                </n-popconfirm>
                <n-button
                  class="issue-actions__command issue-actions__command--neutral"
                  data-testid="issue-edit-button"
                  type="default"
                  secondary
                  strong
                  :disabled="issue.status === 'closed'"
                  @click="openEditModal"
                >
                  <template #icon><n-icon :component="CreateOutline" /></template>
                  {{ t('issue.edit') }}
                </n-button>
              </template>
              <n-button
                class="issue-actions__command issue-actions__command--neutral issue-actions__command--refresh"
                secondary
                strong
                @click="refreshIssue"
                :loading="loading"
              >
                <template #icon><n-icon :component="RefreshOutline" /></template>
                {{ t('common.refresh') }}
              </n-button>
            </div>
          </div>
        </template>
      </PageHeader>

      <div class="issue-workbench">
        <main class="issue-workbench__main">
          <IssueCurrentExecution
            :task="highlightedTask"
            :is-active="Boolean(activeTask)"
            @open-task="openTask"
          />

          <n-card
            v-if="issue.description"
            class="issue-card issue-description-card"
            :bordered="false"
            data-testid="issue-description-card"
          >
            <template #header>
              <div class="issue-card__header">
                <div>
                  <div class="issue-card__eyebrow">{{ t('issue.requirementContext') }}</div>
                  <div class="issue-card__title">{{ t('issue.field.description') }}</div>
                </div>
                <n-tooltip trigger="hover" content-style="font-size: 12px">
                  <template #trigger>
                    <n-button
                      size="small"
                      secondary
                      circle
                      :aria-label="t('taskView.copySource')"
                      @click="copyIssueDescription"
                    >
                      <template #icon>
                        <n-icon :component="CopyOutline" />
                      </template>
                    </n-button>
                  </template>
                  {{ t('taskView.copySource') }}
                </n-tooltip>
              </div>
            </template>
            <div class="issue-view__description markdown-content" v-html="renderedDescription"></div>
          </n-card>

          <IssueTaskPanel
            :tasks="issue.tasks || []"
            :retried-task-map="retriedTaskMap"
            :can-manage-task="canManageIssueTask"
            :can-reschedule-task="canRescheduleIssueTask"
            @open-task="openTask"
            @retry-task="openRetryDrawer"
            @reschedule-task="openRescheduleDrawer"
          />

          <IssueCIAutomationPanel
            :enabled="issue.ci_auto_repair_enabled"
            :failures="ciFailures"
            :loading="ciFailuresLoading"
            :total="ciFailureTotal"
            :repair-task-count="ciRepairTaskCount"
            :root-cause-job-count="ciRootCauseJobCount"
            :webhook-events-by-run="webhookEventsByRun"
            @open-task="openTask"
          />
        </main>

        <div class="issue-workbench__aside">
          <IssueOverviewSidebar
            :issue="issue"
            :project-name="projectName"
            :project-url="projectUrl"
          />
        </div>
      </div>
    </n-space>

    <!-- Close Modal -->
    <n-modal
      v-model:show="showCloseModal"
      preset="card"
      :title="t('issue.close')"
      class="config-editor-modal issue-close-confirm-modal"
      style="width: 520px; max-width: 90vw;"
      data-testid="issue-close-modal"
    >
      <div class="close-issue-modal">
        <p class="close-issue-modal__message">{{ t('issue.confirmClose') }}</p>
        <p v-if="issue.branch_name && !issue.branch_deleted" class="close-issue-modal__branch">
          {{ t('issue.closeBranchChoiceHint', { branch: issue.branch_name }) }}
        </p>
      </div>
      <template #action>
        <n-space justify="end">
          <n-button @click="showCloseModal = false">{{ t('common.cancel') }}</n-button>
          <n-button
            type="primary"
            :disabled="closingIssue"
            :loading="closingIssue"
            data-testid="issue-close-keep-branch-button"
            @click="handleClose(false)"
          >
            {{ t('issue.closeKeepBranch') }}
          </n-button>
          <n-button
            v-if="issue.branch_name && !issue.branch_deleted"
            type="error"
            :disabled="closingIssue"
            :loading="closingIssue"
            data-testid="issue-close-delete-branch-button"
            @click="handleClose(true)"
          >
            {{ t('issue.closeDeleteBranch') }}
          </n-button>
        </n-space>
      </template>
    </n-modal>

    <!-- Edit Modal -->
    <n-modal v-model:show="showEditModal" preset="card" :title="t('issue.edit')" style="width: 600px; max-width: 90vw;">
      <n-form label-placement="top">
        <n-form-item :label="t('issue.field.title')">
          <n-input v-model:value="editForm.title" />
        </n-form-item>
        <n-form-item :label="t('issue.field.description')">
          <n-input
            v-model:value="editForm.description"
            type="textarea"
            :rows="6"
          />
        </n-form-item>
        <n-form-item :label="t('issue.ciAutoRepair')">
          <n-space align="center" :size="8">
            <n-switch v-model:value="editForm.ci_auto_repair_enabled" />
            <span class="metadata-muted">
              {{ editForm.ci_auto_repair_enabled ? t('issue.ciAutoRepairEnabled') : t('issue.ciAutoRepairDisabled') }}
            </span>
          </n-space>
        </n-form-item>
        <n-form-item :label="t('createTask.workerProfile')">
          <n-input :value="issue?.worker_profile_name ?? t('common.unavailable')" disabled />
        </n-form-item>
        <n-form-item :label="t('createTask.defaultProvider')">
          <n-select
            v-model:value="editForm.default_provider_id"
            :options="providerOptions"
            clearable
            :placeholder="t('config.providers.systemDefault')"
          />
        </n-form-item>
      </n-form>
      <template #action>
        <n-space justify="end">
          <n-button @click="showEditModal = false">{{ t('common.cancel') }}</n-button>
          <n-button type="primary" :loading="editLoading" @click="handleSaveEdit">
            {{ t('common.save') }}
          </n-button>
        </n-space>
      </template>
    </n-modal>

    <TaskFormDrawer
      v-model:show="showCreateDrawer"
      mode="create"
      :issue-id="issueId"
      :issue-description="issue?.description ?? undefined"
      :has-current-session="Boolean(issue?.claude_session_id || issue?.current_harness)"
      :issue-current-harness="issue?.current_harness ?? null"
      :issue-default-harness="issue?.default_harness_key ?? null"
      :worker-profile-id="issue?.worker_profile_id ?? null"
      :default-provider-id="issue?.default_provider_id ?? null"
      data-testid="issue-create-task-drawer"
      @created="fetchIssue"
    />

    <!-- Retry Task Drawer -->
    <n-drawer
      v-model:show="showRetryDrawer"
      :width="isMobile ? '100%' : 680"
      placement="right"
      data-testid="issue-retry-task-drawer"
    >
      <n-drawer-content :title="t('taskView.retryWithSchedule')" :native-scrollbar="false" closable>
        <div class="retry-drawer">
          <div v-if="retryTargetTask" class="retry-drawer__summary">
            <div class="retry-drawer__summary-title-row">
              <div class="retry-drawer__summary-title">Task #{{ retryTargetTask.id }}</div>
              <n-tooltip trigger="hover" content-style="font-size: 12px">
                <template #trigger>
                  <n-button
                    size="small"
                    secondary
                    circle
                    :aria-label="t('taskView.copySource')"
                    @click="copyRetryPrompt"
                  >
                    <template #icon>
                      <n-icon :component="CopyOutline" />
                    </template>
                  </n-button>
                </template>
                {{ t('taskView.copySource') }}
              </n-tooltip>
            </div>
            <n-scrollbar
              class="retry-drawer__summary-prompt"
              trigger="hover"
              content-style="padding-right: 8px;"
            >
              <div class="retry-drawer__summary-prompt-content markdown-content" v-html="renderedRetryPrompt"></div>
            </n-scrollbar>
          </div>

          <n-form label-placement="top">
            <n-form-item :label="t('createTask.schedule')">
              <div class="schedule-section">
                <n-radio-group v-model:value="retryScheduleType">
                  <n-radio value="now">{{ t('createTask.executeNow') }}</n-radio>
                  <n-radio value="scheduled">{{ t('createTask.scheduleAt') }}</n-radio>
                </n-radio-group>
                <div class="schedule-row" :class="{ 'schedule-row--hidden': retryScheduleType !== 'scheduled' }">
                  <n-date-picker
                    v-model:value="retryTaskSchedule"
                    type="datetime"
                    clearable
                    style="width: 220px; flex-shrink: 0"
                    :is-date-disabled="isScheduleDateDisabled"
                  />
                </div>
              </div>
            </n-form-item>
            <n-form-item :label="t('taskView.lineageStrategy')">
              <n-radio-group v-model:value="retryLineageStrategy">
                <n-radio value="inherit">{{ t('taskView.lineageStrategyInherit') }}</n-radio>
                <n-radio value="fresh_retry">{{ t('taskView.lineageStrategyFreshRetry') }}</n-radio>
              </n-radio-group>
            </n-form-item>
          </n-form>

          <div v-if="retryScheduleType === 'scheduled'" class="retry-drawer__schedule-preview">
            <n-spin v-if="scheduledTasksLoading" :description="t('createTask.schedulePreviewLoading')" />
            <template v-else>
              <p class="retry-drawer__hint">
                {{ t('createTask.schedulePreviewHint') }}
              </p>
              <HeatmapChart
                :tasks="scheduledTasksForPreview"
                :selected-ms="retryTaskSchedule"
                :max-per-slot="slotMaxTasks"
                :enforce-capacity="slotEnforce"
                @cell-click="handleRetryHeatmapCellClick"
              />
            </template>
          </div>
        </div>

        <template #footer>
          <div class="retry-drawer__footer">
            <n-button @click="showRetryDrawer = false">
              {{ t('common.cancel') }}
            </n-button>
            <n-button
              type="primary"
              :loading="retryTaskLoading"
              data-testid="issue-submit-retry-button"
              @click="handleSubmitRetry"
            >
              {{ retryScheduleType === 'scheduled' ? t('taskView.scheduleRetry') : t('common.retry') }}
            </n-button>
          </div>
        </template>
      </n-drawer-content>
    </n-drawer>

    <!-- Reschedule Task Drawer -->
    <RescheduleDrawer
      v-model:show="showRescheduleDrawer"
      :task="rescheduleTargetTask ?? undefined"
      data-testid="issue-reschedule-task-drawer"
      @rescheduled="onTaskRescheduled"
    />

  </div>

  <!-- Loading state before issue is loaded -->
  <n-spin v-else :show="loading" style="min-height: 200px" />
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, reactive, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  NButton, NSpace, NCard, NTag, NSpin,
  NIcon, NInput, NDrawer, NDrawerContent,
  NRadio, NRadioGroup, NForm, NFormItem, NDatePicker, NModal, NPopconfirm, NScrollbar, NTooltip,
  NSelect, NSwitch, useMessage
} from 'naive-ui'
import { useI18n } from 'vue-i18n'
import {
  AddOutline,
  CloseCircleOutline,
  CopyOutline,
  CreateOutline,
  RefreshOutline,
  TrashOutline,
} from '@vicons/ionicons5'
import HeatmapChart from '../components/HeatmapChart.vue'
import IssueCIAutomationPanel from '../components/issue-detail/IssueCIAutomationPanel.vue'
import IssueCurrentExecution from '../components/issue-detail/IssueCurrentExecution.vue'
import IssueOverviewSidebar from '../components/issue-detail/IssueOverviewSidebar.vue'
import IssueTaskPanel from '../components/issue-detail/IssueTaskPanel.vue'
import TaskFormDrawer from '../components/TaskFormDrawer.vue'
import RescheduleDrawer from '../components/RescheduleDrawer.vue'
import {
  getIssue, updateIssue, closeIssue, retryTask, deleteIssueBranch,
  getProjects, getIssueCIFailures, getIssueWebhookEvents,
  getProviders,
  type AIProvider, type Issue, type Task, type Project, type CIFailureRun, type WebhookEvent,
} from '../api'
import PageHeader from '../components/PageHeader.vue'
import { useBreakpoints } from '../composables/useBreakpoints'
import { formatDateTimeUtc8Compact } from '../utils/datetime'
import { extractSlotErrorMessage } from '../utils/slotError'
import { authState, isAdmin } from '../auth'
import { renderMarkdown } from '../components/task-process/taskProcessUtils'
import { issueDetailTooltipContentStyle, issueDetailTooltipThemeOverrides } from '../components/issue-detail/tooltip'
import { useTaskScheduleContext } from '../features/tasks/useTaskScheduleContext'

const route = useRoute()
const router = useRouter()
const message = useMessage()
const { t } = useI18n()
const { isMobile } = useBreakpoints()

const issueId = computed(() => Number(route.params.id))

const isOwner = computed(() => {
  if (!issue.value) return false
  if (!authState.oidcEnabled) return true
  if (!authState.user) return false
  if (isAdmin.value) return true
  return issue.value.initiator_user_id === authState.user.id
})

function canManageIssueTask(task: Pick<Task, 'initiator_user_id' | 'initiator_gitlab_user_id'>): boolean {
  if (!authState.oidcEnabled) return true
  if (!authState.user) return false
  if (isAdmin.value) return true

  return (
    (
      task.initiator_user_id !== null
      && task.initiator_user_id !== undefined
      && task.initiator_user_id === authState.user.id
    )
    || (
      task.initiator_gitlab_user_id !== null
      && task.initiator_gitlab_user_id !== undefined
      && task.initiator_gitlab_user_id === authState.user.gitlab_user_id
    )
  )
}

// --- State ---
const issue = ref<Issue | null>(null)
const loading = ref(false)
const deletingBranch = ref(false)
const closingIssue = ref(false)
const showCloseModal = ref(false)
let pollTimer: number | null = null
const projects = ref<Project[]>([])
const providers = ref<AIProvider[]>([])
const ciFailures = ref<CIFailureRun[]>([])
const issueWebhookEvents = ref<WebhookEvent[]>([])
const ciFailuresLoading = ref(false)
const ciFailureTotal = ref(0)

const webhookEventsByRun = computed(() => {
  const eventById = new Map(issueWebhookEvents.value.map(e => [e.id, e]))
  const map: Record<number, WebhookEvent> = {}
  for (const run of ciFailures.value) {
    if (run.webhook_event_id) {
      const event = eventById.get(run.webhook_event_id)
      if (event) map[run.id] = event
    }
  }
  return map
})

const ciRepairTaskCount = computed(() => {
  const tasks = issue.value?.tasks
  if (tasks?.length) {
    return tasks.filter(task => task.trigger_source === 'ci_auto_repair').length
  }
  return ciFailures.value.filter(run => run.repair_task_id).length
})
const ciRootCauseJobCount = computed(() =>
  ciFailures.value.reduce((total, run) => (
    total + (run.jobs?.filter(job => job.is_root_cause).length ?? 0)
  ), 0)
)

const renderedDescription = computed(() => renderMarkdown(issue.value?.description ?? ''))
const renderedRetryPrompt = computed(() => renderMarkdown(retryTargetTask.value?.user_prompt ?? ''))

function copyIssueDescription() {
  navigator.clipboard.writeText(issue.value?.description ?? '')
  message.success(t('taskView.copied'))
}

function copyRetryPrompt() {
  navigator.clipboard.writeText(retryTargetTask.value?.user_prompt ?? '')
  message.success(t('taskView.copied'))
}

const sortedTasks = computed(() => [...(issue.value?.tasks ?? [])].sort((a, b) => {
  const seqA = a.issue_sequence
  const seqB = b.issue_sequence
  if (typeof seqA === 'number' && typeof seqB === 'number' && seqA !== seqB) {
    return seqB - seqA
  }
  const timeDiff = new Date(b.created_at).getTime() - new Date(a.created_at).getTime()
  return timeDiff || b.id - a.id
}))
const activeTask = computed(() => {
  const tasks = sortedTasks.value
  if (!tasks.length) return null
  // §8.1: prefer the RUNNING task, otherwise the active task with the smallest
  // queue_position. Never fall back to the newest-created PENDING task.
  const running = tasks.find(task => task.status === 'running')
  if (running) return running
  const positioned = tasks.filter(task =>
    ['pending', 'queued'].includes(task.status)
    && typeof task.queue_position === 'number'
    && task.queue_position >= 1,
  )
  if (positioned.length) {
    return positioned.reduce((min, task) =>
      (task.queue_position! < min.queue_position! ? task : min), positioned[0])
  }
  // Legacy rows without queue context: fall back to the oldest active task.
  const legacy = tasks.filter(task => ['pending', 'queued'].includes(task.status))
  if (legacy.length) {
    return legacy.reduce((oldest, task) =>
      (new Date(task.created_at).getTime() < new Date(oldest.created_at).getTime() ? task : oldest), legacy[0])
  }
  return null
})
const highlightedTask = computed(() => activeTask.value ?? sortedTasks.value[0] ?? null)

const projectName = computed(() => {
  if (!issue.value) return '-'
  const project = projects.value.find(p => p.id === issue.value!.project_id)
  return project ? project.path_with_namespace : `Project #${issue.value.project_id}`
})

const projectUrl = computed(() => {
  if (!issue.value) return null
  const project = projects.value.find(p => p.id === issue.value!.project_id)
  return project?.web_url ?? null
})

const providerOptions = computed(() =>
  providers.value
    .filter(provider => !provider.is_disabled || provider.id === issue.value?.default_provider_id)
    .map(provider => ({
      label: `${provider.name} (${provider.model})${provider.is_default ? ' ★' : ''}`,
      value: provider.id,
      disabled: provider.is_disabled,
    }))
)

// Create task form
const showCreateDrawer = ref(false)
const showRetryDrawer = ref(false)
const retryTargetTask = ref<Task | null>(null)
const retryScheduleType = ref<'now' | 'scheduled'>('now')
const retryLineageStrategy = ref<'inherit' | 'fresh_retry'>('inherit')
const retryTaskSchedule = ref<number | null>(null)
const retryTaskLoading = ref(false)
const showRescheduleDrawer = ref(false)
const rescheduleTargetTask = ref<Task | null>(null)

// Schedule heatmap
const {
  scheduledTasks: scheduledTasksForPreview,
  scheduledTasksLoading,
  slotMaxTasks,
  slotEnforce,
  loadScheduleContext,
} = useTaskScheduleContext()

// Edit modal
const showEditModal = ref(false)
const editLoading = ref(false)
const editForm = reactive({
  title: '',
  description: '',
  ci_auto_repair_enabled: false,
  default_provider_id: null as number | null,
})

// --- Constants ---
const issueStatusColors: Record<string, 'default' | 'info' | 'warning' | 'success' | 'error'> = {
  open: 'default',
  in_progress: 'warning',
  in_review: 'info',
  closed: 'success'
}

// --- Retry lookup ---
const retriedTaskMap = computed(() => {
  const map = new Map<number, Task>()
  if (!issue.value?.tasks) return map
  for (const task of issue.value.tasks) {
    if (task.is_retry && task.retry_source_task_id) {
      map.set(task.retry_source_task_id, task)
    }
  }
  return map
})

// --- Helpers ---
function formatCompactDateTime(value?: string | null): string {
  if (!value) return '-'
  return formatDateTimeUtc8Compact(value)
}

function openTask(taskId: number) {
  router.push({ name: 'TaskView', params: { id: taskId } })
}

function canRescheduleIssueTask(task: Pick<Task, 'status' | 'scheduled_at'>): boolean {
  if (task.status === 'queued') return true
  return task.status === 'pending' && !!task.scheduled_at
}

function isScheduleDateDisabled(timestamp: number): boolean {
  const candidate = new Date(timestamp)
  const today = new Date()
  candidate.setHours(0, 0, 0, 0)
  today.setHours(0, 0, 0, 0)
  return candidate.getTime() < today.getTime()
}

watch(showRetryDrawer, (val) => {
  if (!val) {
    retryTargetTask.value = null
    retryScheduleType.value = 'now'
    retryLineageStrategy.value = 'inherit'
    retryTaskSchedule.value = null
  }
})

watch(showRescheduleDrawer, (val) => {
  if (!val) {
    rescheduleTargetTask.value = null
  }
})

watch(issueId, () => {
  automationLoaded = false
})

onUnmounted(() => {
  document.removeEventListener('visibilitychange', handleVisibilityChange)
  if (pollTimer !== null) {
    clearInterval(pollTimer)
    pollTimer = null
  }
})

function handleRetryHeatmapCellClick(startMs: number) {
  retryTaskSchedule.value = startMs
}

async function openRetryDrawer(task: Task) {
  retryTargetTask.value = task
  retryScheduleType.value = 'now'
  retryLineageStrategy.value = 'inherit'
  retryTaskSchedule.value = null
  showRetryDrawer.value = true
  await loadScheduleContext(true)
}

function openRescheduleDrawer(task: Task) {
  rescheduleTargetTask.value = task
  showRescheduleDrawer.value = true
}

function onTaskRescheduled() {
  fetchIssue()
}

// --- API Actions ---
async function fetchIssue() {
  loading.value = true
  try {
    issue.value = await getIssue(issueId.value)
    await fetchIssueAutomation()
  } catch {
    message.error(t('issue.loadFailed'))
  } finally {
    loading.value = false
  }
}

let automationLoaded = false
async function fetchIssueAutomation() {
  const showInitialLoading = !automationLoaded
  if (showInitialLoading) ciFailuresLoading.value = true
  try {
    const [failureResponse, webhookResponse] = await Promise.all([
      getIssueCIFailures(issueId.value, { page_size: 5 }),
      getIssueWebhookEvents(issueId.value, { page_size: 50 }),
    ])
    const failures = failureResponse.items
    ciFailures.value = failures
    ciFailureTotal.value = failureResponse.total
    issueWebhookEvents.value = webhookResponse.items
    automationLoaded = true
  } catch {
    if (!automationLoaded) {
      ciFailures.value = []
      ciFailureTotal.value = 0
      issueWebhookEvents.value = []
    }
  } finally {
    if (showInitialLoading) ciFailuresLoading.value = false
  }
}

async function refreshIssue() {
  await fetchIssue()
  getProjects().then(p => { projects.value = p }).catch((err) => {
    console.warn('Failed to load projects for issue view:', err)
  })
}

async function handleClose(deleteBranch: boolean) {
  if (closingIssue.value) return
  closingIssue.value = true
  try {
    issue.value = await closeIssue(issueId.value, {
      branch_action: deleteBranch ? 'delete' : 'keep',
      delete_branch: deleteBranch,
    })
    showCloseModal.value = false
    message.success(t('issue.closeSuccess'))
  } catch {
    message.error(t('issue.closeFailed'))
  } finally {
    closingIssue.value = false
  }
}

async function handleDeleteBranch() {
  if (!issue.value) return
  deletingBranch.value = true
  try {
    issue.value = await deleteIssueBranch(issueId.value)
    message.success(t('issue.deleteBranchSuccess'))
  } catch {
    message.error(t('issue.deleteBranchFailed'))
  } finally {
    deletingBranch.value = false
  }
}

async function handleSaveEdit() {
  editLoading.value = true
  try {
    issue.value = await updateIssue(issueId.value, {
      title: editForm.title,
      description: editForm.description,
      ci_auto_repair_enabled: editForm.ci_auto_repair_enabled,
      default_provider_id: editForm.default_provider_id,
    })
    showEditModal.value = false
    message.success(t('issue.updateSuccess'))
  } catch {
    message.error(t('issue.updateFailed'))
  } finally {
    editLoading.value = false
  }
}

async function handleRetryTask(
  taskId: number,
  scheduledDatetime?: string,
  lineageStrategy: 'inherit' | 'fresh_retry' = 'inherit',
): Promise<boolean> {
  try {
    await retryTask(taskId, scheduledDatetime, lineageStrategy)
    message.success(
      lineageStrategy === 'fresh_retry'
        ? t('issue.retrySuccessFresh')
        : t('issue.retrySuccess'),
    )
    await fetchIssue()
    return true
  } catch (error: any) {
    message.error(extractSlotErrorMessage(error, t, 'issue.retryFailed'))
    return false
  }
}

async function handleSubmitRetry() {
  if (!retryTargetTask.value) return

  let scheduledDatetime: string | undefined
  if (retryScheduleType.value === 'scheduled') {
    if (!retryTaskSchedule.value) {
      message.warning(t('createTask.pleaseSelectScheduledTime'))
      return
    }
    if (retryTaskSchedule.value <= Date.now()) {
      message.warning(t('createTask.scheduledTimeFuture'))
      return
    }
    scheduledDatetime = new Date(retryTaskSchedule.value).toISOString()
  }

  retryTaskLoading.value = true
  try {
    const success = await handleRetryTask(
      retryTargetTask.value.id,
      scheduledDatetime,
      retryLineageStrategy.value,
    )
    if (success) {
      showRetryDrawer.value = false
    }
  } finally {
    retryTaskLoading.value = false
  }
}


// --- Lifecycle ---
function openEditModal() {
  if (!issue.value) return
  editForm.title = issue.value.title
  editForm.description = issue.value.description || ''
  editForm.ci_auto_repair_enabled = issue.value.ci_auto_repair_enabled
  editForm.default_provider_id = issue.value.default_provider_id
  showEditModal.value = true
}

async function loadExecutionDefaults() {
  const providerResult = await Promise.allSettled([getProviders()])
  const result = providerResult[0]
  if (result.status === 'fulfilled') {
    providers.value = Array.isArray(result.value) ? result.value : []
  }
}

function handleVisibilityChange() {
  if (document.visibilityState !== 'visible' || loading.value) return
  if (issue.value?.status !== 'closed') {
    void fetchIssue()
  }
}

onMounted(() => {
  document.addEventListener('visibilitychange', handleVisibilityChange)
  fetchIssue()
  loadExecutionDefaults()
  getProjects().then(p => { projects.value = p }).catch((err) => {
    console.warn('Failed to load projects for issue view:', err)
  })
  pollTimer = window.setInterval(() => {
    if (document.visibilityState !== 'visible') return
    if (loading.value) return
    if (issue.value?.status !== 'closed') {
      fetchIssue()
    }
  }, 5000)
})
</script>

<style scoped>
.issue-view {
  max-width: var(--app-page-max-width);
}

.issue-view__context {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 8px;
  flex-wrap: wrap;
  color: var(--app-page-subtitle-color, rgba(15, 23, 42, 0.58));
  font-size: 13px;
  line-height: 1.45;
}

.issue-workbench {
  display: grid;
  grid-template-columns: minmax(0, 2fr) minmax(300px, 1fr);
  gap: 16px;
  align-items: start;
}

.issue-workbench__main {
  display: grid;
  gap: 16px;
  min-width: 0;
  max-width: 100%;
}

.issue-workbench__main > * {
  min-width: 0;
  max-width: 100%;
}

.issue-workbench__aside {
  position: sticky;
  top: 16px;
  min-width: 0;
  max-width: 100%;
}

.issue-view__actions {
  display: inline-flex;
  align-items: center;
  justify-content: flex-end;
  gap: 8px;
  flex-wrap: wrap;
  flex: 1 1 360px;
}

.issue-actions {
  display: grid;
  gap: 10px;
}

.issue-actions--header {
  width: 100%;
}

.issue-actions__toolbar {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  flex-wrap: wrap;
  gap: 8px;
  min-height: 34px;
}

.issue-actions__command {
  flex: 0 0 auto;
  --n-height: 34px !important;
  --n-padding: 0 12px !important;
  --n-font-weight: 400 !important;
  --n-border-radius: 10px !important;
  --n-ripple-color: rgba(37, 99, 235, 0.18) !important;
}

.issue-actions__command--primary {
  min-width: 108px;
  box-shadow: 0 7px 18px rgba(24, 160, 88, 0.16);
}

.issue-actions__command--neutral {
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

.issue-actions__command--danger {
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

.issue-actions__command--refresh {
  margin-left: 2px;
}

.issue-view__title {
  margin: 0;
  font-size: var(--app-page-title-size);
  line-height: 1.2;
}

.issue-card {
  border-radius: var(--app-card-radius);
}

.issue-description-card {
  border: 1px solid rgba(15, 23, 42, 0.065);
}

.metadata-muted {
  color: var(--n-text-color-3);
  font-size: 13px;
}

.issue-card__header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 12px;
}

.issue-card__title {
  font-size: 18px;
  font-weight: 650;
}

.issue-card__eyebrow {
  margin-bottom: 3px;
  color: var(--n-text-color-3);
  font-size: 11px;
  font-weight: 650;
  letter-spacing: 0.07em;
  text-transform: uppercase;
}

.issue-view__description {
  padding: 2px 0;
  line-height: 1.72;
  color: rgba(15, 23, 42, 0.82);
}
.issue-view__description :deep(p) { margin: 0 0 0.6em; }
.issue-view__description :deep(p:last-child) { margin-bottom: 0; }
.issue-view__description :deep(h1),
.issue-view__description :deep(h2),
.issue-view__description :deep(h3),
.issue-view__description :deep(h4) { margin: 0.8em 0 0.4em; font-weight: 600; line-height: 1.3; }
.issue-view__description :deep(h1) { font-size: 1.25em; }
.issue-view__description :deep(h2) { font-size: 1.1em; }
.issue-view__description :deep(h3) { font-size: 1em; }
.issue-view__description :deep(ul),
.issue-view__description :deep(ol) { margin: 0.4em 0; padding-left: 1.5em; }
.issue-view__description :deep(li) { margin: 0.15em 0; }
.issue-view__description :deep(blockquote) {
  margin: 0.5em 0; padding: 0.2em 0.8em;
  border-left: 3px solid rgba(128,128,128,0.35);
  color: rgba(15, 23, 42, 0.5);
}
.issue-view__description :deep(a) { color: var(--n-primary-color, #18a058); text-decoration: none; }
.issue-view__description :deep(a:hover) { text-decoration: underline; }
.issue-view__description :deep(code) {
  font-family: var(--n-font-family-mono, monospace);
  font-size: 0.88em; background: rgba(128,128,128,0.12);
  border-radius: 3px; padding: 0.1em 0.35em;
}
.issue-view__description :deep(pre.md-code-block) {
  margin: 0.5em 0; padding: 10px 12px;
  background: rgba(0,0,0,0.06); border-radius: 5px;
  overflow-wrap: anywhere; font-family: var(--n-font-family-mono, monospace);
  font-size: 0.85em; line-height: 1.55; white-space: pre-wrap;
}
.issue-view__description :deep(pre.md-code-block code) { background: none; padding: 0; border-radius: 0; font-size: inherit; color: inherit; }
.issue-view__description :deep(table) { width: 100%; border-collapse: collapse; margin: 0.6em 0; font-size: 0.9em; table-layout: fixed; }
.issue-view__description :deep(th),
.issue-view__description :deep(td) { border: 1px solid rgba(128,128,128,0.25); padding: 5px 10px; text-align: left; }
.issue-view__description :deep(th) { background: rgba(128,128,128,0.08); font-weight: 600; }
.issue-view__description :deep(tr:nth-child(even) td) { background: rgba(128,128,128,0.04); }
.issue-view__description :deep(hr) { border: none; border-top: 1px solid rgba(128,128,128,0.2); margin: 0.8em 0; }

.issue-view__code {
  font-family: 'SF Mono', 'Fira Code', 'Fira Mono', Menlo, Consolas, monospace;
  font-size: 13px;
  padding: 2px 8px;
  border-radius: 6px;
  background: rgba(15, 23, 42, 0.06);
  word-break: break-all;
}

.schedule-section {
  display: flex;
  flex-direction: column;
  gap: 12px;
  width: 100%;
}

.schedule-row {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  overflow: hidden;
  max-height: 40px;
  opacity: 1;
  transition: max-height 0.2s ease, opacity 0.2s ease, margin 0.2s ease;
}

.schedule-row--hidden {
  max-height: 0;
  opacity: 0;
  margin: 0;
  pointer-events: none;
}

.retry-drawer {
  display: grid;
  gap: 16px;
}

.retry-drawer__summary {
  display: grid;
  gap: 8px;
  padding: 12px 14px;
  border: 1px solid rgba(15, 23, 42, 0.08);
  border-radius: 8px;
  background: rgba(15, 23, 42, 0.035);
}

.retry-drawer__summary-title-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.retry-drawer__summary-title {
  font-size: 13px;
  font-weight: 600;
  color: rgba(15, 23, 42, 0.76);
}

.retry-drawer__summary-prompt {
  max-height: 96px;
}
.retry-drawer__summary-prompt-content {
  word-break: break-word;
  font-size: 13px;
  line-height: 1.55;
  color: rgba(15, 23, 42, 0.72);
}
.retry-drawer__summary-prompt-content :deep(p) { margin: 0 0 0.5em; }
.retry-drawer__summary-prompt-content :deep(p:last-child) { margin-bottom: 0; }
.retry-drawer__summary-prompt-content :deep(ul),
.retry-drawer__summary-prompt-content :deep(ol) { margin: 0.3em 0; padding-left: 1.4em; }
.retry-drawer__summary-prompt-content :deep(li) { margin: 0.1em 0; }
.retry-drawer__summary-prompt-content :deep(code) {
  font-family: var(--n-font-family-mono, monospace);
  font-size: 0.88em; background: rgba(128,128,128,0.12);
  border-radius: 3px; padding: 0.1em 0.3em;
}
.retry-drawer__summary-prompt-content :deep(pre.md-code-block) {
  margin: 0.4em 0; padding: 8px 10px;
  background: rgba(0,0,0,0.06); border-radius: 4px;
  overflow-wrap: anywhere; font-size: 0.82em; white-space: pre-wrap;
}
.retry-drawer__summary-prompt-content :deep(pre.md-code-block code) { background: none; padding: 0; font-size: inherit; }

.retry-drawer__schedule-preview {
  display: grid;
  gap: 10px;
}

.retry-drawer__hint {
  margin: 0;
  color: var(--n-text-color-3);
  font-size: 13px;
}

.retry-drawer__footer {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}


:global(.issue-close-confirm-modal) {
  overflow: hidden;
  border: 1px solid rgba(15, 23, 42, 0.08);
  border-radius: var(--app-card-radius);
  box-shadow: var(--app-card-shadow-soft);
  background: linear-gradient(180deg, rgba(255, 255, 255, 0.96), rgba(248, 250, 252, 0.98));
}

.close-issue-modal {
  display: grid;
  gap: 8px;
}

.close-issue-modal__message,
.close-issue-modal__branch {
  margin: 0;
  line-height: 1.5;
}

.close-issue-modal__branch {
  color: var(--n-text-color-2);
  word-break: break-word;
}


.app-link {
  color: var(--n-primary-color, #18a058);
  text-decoration: none;
}
.app-link:hover {
  text-decoration: underline;
}

@media (max-width: 1100px) {
  .issue-workbench {
    grid-template-columns: minmax(0, 1fr);
  }

  .issue-workbench__aside {
    position: static;
  }
}

@media (max-width: 768px) {
  .issue-view__actions {
    width: 100%;
    justify-content: flex-start;
  }

  .issue-actions__toolbar {
    align-items: stretch;
    justify-content: flex-start;
  }

  .issue-actions__command {
    flex: 1 1 150px;
    justify-content: center;
  }

  .issue-card__header {
    flex-direction: column;
    align-items: flex-start;
  }
}
</style>
