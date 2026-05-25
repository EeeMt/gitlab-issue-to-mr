<template>
  <div v-if="issue" class="issue-view" data-testid="issue-view-page">
    <n-space vertical :size="16">
      <!-- Header -->
      <PageHeader
        data-testid="issue-view-header"
        root-class="issue-view__hero"
        actions-class="issue-view__actions"
        :subtitle="t('issue.detailSubtitle')"
      >
        <template #title>
          <h2 class="issue-view__title">#{{ issue.id }} {{ issue.title }}</h2>
          <n-tag :type="issueStatusColors[issue.status]" round>
            {{ t(`issue.status.${issue.status}`) }}
          </n-tag>
        </template>
        <template #actions>
          <div class="issue-actions issue-actions--header" data-testid="issue-actions">
            <div class="issue-actions__toolbar">
              <template v-if="isOwner">
                <n-popconfirm @positive-click="handleClose">
                  <template #trigger>
                    <n-button
                      class="issue-actions__command issue-actions__command--danger"
                      type="error"
                      secondary
                      strong
                      :disabled="issue.status === 'closed' || closingIssue"
                      :loading="closingIssue"
                      data-testid="issue-close-button"
                    >
                      <template #icon><n-icon :component="CloseCircleOutline" /></template>
                      {{ t('issue.close') }}
                    </n-button>
                  </template>
                  {{ t('issue.confirmClose') }}
                </n-popconfirm>
                <n-tooltip v-if="issue.status === 'closed' && issue.branch_name && issue.branch_deleted" :title="t('issue.branchAlreadyDeleted')">
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

      <!-- Metadata + Description side by side -->
      <n-grid :cols="issue.description ? (isMobile ? 1 : 2) : 1" :x-gap="16" :y-gap="16">
        <n-gi>
          <!-- Metadata -->
          <n-card class="issue-card" :bordered="false" data-testid="issue-metadata-card">
            <template #header>
              <div class="issue-card__header">
                <div class="issue-card__title">{{ t('issue.metadata') }}</div>
              </div>
            </template>
            <div class="metadata-body">
              <!-- Status -->
              <div class="metadata-row">
                <span class="metadata-label">
                  <n-icon size="14" class="metadata-label-icon"><InformationCircleOutline /></n-icon>
                  {{ t('common.status') }}
                </span>
                <span class="metadata-value">
                  <n-tag :type="issueStatusColors[issue.status]" size="small" round>
                    {{ t(`issue.status.${issue.status}`) }}
                  </n-tag>
                </span>
              </div>

              <!-- Closed Via -->
              <div v-if="issue.status === 'closed' && issue.closed_via" class="metadata-row">
                <span class="metadata-label">
                  <n-icon size="14" class="metadata-label-icon"><InformationCircleOutline /></n-icon>
                  {{ t('issue.closedViaLabel') }}
                </span>
                <span class="metadata-value">
                  <n-tag size="small" round :type="issue.closed_via === 'webhook_mr_merged' ? 'info' : 'default'">
                    {{ issue.closed_via === 'webhook_mr_merged' ? t('issue.closedViaWebhookMrMerged') : t('issue.closedViaManual') }}
                  </n-tag>
                </span>
              </div>

              <!-- Project -->
              <div class="metadata-row">
                <span class="metadata-label">
                  <n-icon size="14" class="metadata-label-icon"><FolderOpenOutline /></n-icon>
                  {{ t('issue.field.project') }}
                </span>
                <span class="metadata-value">
                  <a v-if="projectUrl" :href="projectUrl" target="_blank" rel="noopener noreferrer" class="app-link">
                    {{ projectName }}
                  </a>
                  <span v-else>{{ projectName }}</span>
                </span>
              </div>

              <!-- Creator -->
              <div class="metadata-row">
                <span class="metadata-label">
                  <n-icon size="14" class="metadata-label-icon"><PersonOutline /></n-icon>
                  {{ t('issue.field.creator') }}
                </span>
                <span class="metadata-value">
                  {{ issue.initiator_username || '-' }}
                </span>
              </div>

              <!-- Branch flow -->
              <div class="metadata-row">
                <span class="metadata-label">
                  <n-icon size="14" class="metadata-label-icon"><GitBranchOutline /></n-icon>
                  {{ t('taskView.branchFlow') }}
                </span>
                <span class="metadata-value">
                  <span class="branch-flow">
                    <template v-if="issue.base_branch">
                      <n-tooltip trigger="hover" placement="top">
                        <template #trigger>
                          <a v-if="issueBranchUrl(issue.base_branch)" :href="issueBranchUrl(issue.base_branch)!" target="_blank" rel="noopener noreferrer" class="branch-item branch-item--base app-link">{{ issue.base_branch }}</a>
                          <span v-else class="branch-item branch-item--base">{{ issue.base_branch }}</span>
                        </template>
                        {{ t('issue.field.baseBranch') }}
                      </n-tooltip>
                    </template>
                    <span v-if="issue.base_branch && issue.branch_name" class="branch-arrow">➜</span>
                    <template v-if="issue.branch_name">
                      <n-tooltip trigger="hover" placement="top">
                        <template #trigger>
                          <a v-if="issueBranchUrl(issue.branch_name)" :href="issueBranchUrl(issue.branch_name)!" target="_blank" rel="noopener noreferrer" class="branch-item branch-item--work app-link">{{ issue.branch_name }}</a>
                          <span v-else class="branch-item branch-item--work">{{ issue.branch_name }}</span>
                        </template>
                        {{ t('createTask.branchFlowWorkBranch') }}
                      </n-tooltip>
                    </template>
                    <span v-if="issue.branch_name && issue.target_branch" class="branch-arrow">➜</span>
                    <template v-if="issue.target_branch">
                      <n-tooltip trigger="hover" placement="top">
                        <template #trigger>
                          <a v-if="issueBranchUrl(issue.target_branch)" :href="issueBranchUrl(issue.target_branch)!" target="_blank" rel="noopener noreferrer" class="branch-item branch-item--target app-link">{{ issue.target_branch }}</a>
                          <span v-else class="branch-item branch-item--target">{{ issue.target_branch }}</span>
                        </template>
                        {{ t('issue.field.targetBranch') }}
                      </n-tooltip>
                    </template>
                    <span v-if="!issue.branch_name && !issue.base_branch && !issue.target_branch">-</span>
                  </span>
                </span>
              </div>

              <!-- Merge Request -->
              <div class="metadata-row">
                <span class="metadata-label">
                  <n-icon size="14" class="metadata-label-icon"><GitPullRequest /></n-icon>
                  {{ t('issue.field.mergeRequest') }}
                </span>
                <span class="metadata-value">
                  <a
                    v-if="issue.merge_request_url"
                    :href="issue.merge_request_url"
                    target="_blank"
                    rel="noopener noreferrer"
                    class="app-link"
                  >
                    !{{ issue.merge_request_iid }}
                  </a>
                  <span v-else class="metadata-muted">{{ t('issue.noMergeRequest') }}</span>
                </span>
              </div>

              <!-- Branch policy -->
              <div v-if="issue.branch_name || issue.branch_deleted" class="metadata-row" data-testid="issue-branch-policy-row">
                <span class="metadata-label">
                  <n-icon size="14" class="metadata-label-icon"><GitBranchOutline /></n-icon>
                  {{ t('issue.deleteBranchOnClose') }}
                </span>
                <span class="metadata-value">
                  <n-tag size="small" round data-testid="delete-branch-badge" v-if="issue.delete_branch_on_close">
                    {{ t('issue.deleteBranchBadge') }}
                  </n-tag>
                  <n-tag size="small" round data-testid="keep-branch-badge" v-else>
                    {{ t('issue.keepBranchBadge') }}
                  </n-tag>

                  <n-tag size="small" round data-testid="branch-deleted-badge" v-if="issue.branch_deleted">
                    {{ t('issue.branchDeletedBadge') }}
                  </n-tag>
                </span>
              </div>

              <!-- Session ID -->
              <div class="metadata-row">
                <span class="metadata-label">
                  <n-icon size="14" class="metadata-label-icon"><CodeOutline /></n-icon>
                  {{ t('issue.field.sessionId') }}
                </span>
                <span class="metadata-value">
                  <code v-if="issue.claude_session_id" class="issue-view__code">{{ issue.claude_session_id }}</code>
                  <span v-else class="metadata-muted">-</span>
                </span>
              </div>

              <!-- Changes -->
              <div v-if="issue.totals && (issue.totals.total_changes > 0 || issue.totals.input_tokens > 0)" class="metadata-row">
                <span class="metadata-label">
                  <n-icon size="14" class="metadata-label-icon"><CodeOutline /></n-icon>
                  {{ t('common.changes') }}
                </span>
                <span class="metadata-value">
                  <span v-if="issue.totals.total_changes > 0">
                    {{ issue.totals.total_changes }}
                    <span class="metadata-secondary">
                      (<span class="stat-add">+{{ issue.totals.additions }}</span> / <span class="stat-del">-{{ issue.totals.deletions }}</span>)
                    </span>
                  </span>
                  <span v-else class="metadata-muted">—</span>
                </span>
              </div>

              <!-- Tokens -->
              <div v-if="issue.totals && (issue.totals.input_tokens > 0 || issue.totals.output_tokens > 0)" class="metadata-row">
                <span class="metadata-label">
                  <n-icon size="14" class="metadata-label-icon"><CodeOutline /></n-icon>
                  {{ t('analytics.tokens') }}
                </span>
                <span class="metadata-value">
                  {{ formatNumber(issue.totals.input_tokens + issue.totals.output_tokens) }}
                  <span class="metadata-secondary">
                    ({{ t('analytics.tokenInputLine', { value: formatNumber(issue.totals.input_tokens) }) }} /
                    {{ t('analytics.tokenOutputLine', { value: formatNumber(issue.totals.output_tokens) }) }})
                  </span>
                </span>
              </div>

              <!-- Total task duration -->
              <div v-if="issue.totals" class="metadata-row">
                <span class="metadata-label">
                  <n-icon size="14" class="metadata-label-icon"><TimeOutline /></n-icon>
                  {{ t('issue.totalTaskDuration') }}
                </span>
                <span class="metadata-value">
                  {{ formatDurationSec(issue.totals.duration_seconds) }}
                </span>
              </div>

              <!-- Timeline -->
              <div class="metadata-row">
                <span class="metadata-label">
                  <n-icon size="14" class="metadata-label-icon"><TimeOutline /></n-icon>
                  {{ t('common.timeline') }}
                </span>
                <div class="time-axis">
                  <div class="time-point">
                    <span class="time-point__label">{{ t('common.created') }}</span>
                    <span class="time-point__value">{{ formatCompactDateTime(issue.created_at) }}</span>
                  </div>
                  <div class="time-axis__sep">→</div>
                  <div class="time-point">
                    <span class="time-point__label">{{ t('issue.field.updatedAt') }}</span>
                    <span class="time-point__value">{{ formatCompactDateTime(issue.updated_at) }}</span>
                  </div>
                </div>
              </div>
            </div>
          </n-card>
        </n-gi>
        <n-gi v-if="issue.description">
          <!-- Description -->
          <n-card
            class="issue-card"
            :bordered="false"
            data-testid="issue-description-card"
          >
            <template #header>
              <div class="issue-card__header">
                <div class="issue-card__title">{{ t('issue.field.description') }}</div>
              </div>
            </template>
            <div class="issue-view__description-wrap">
              <n-scrollbar trigger="hover" style="position: absolute; top: 0; right: 0; bottom: 0; left: 0;">
                <div class="issue-view__description markdown-content" v-html="renderedDescription"></div>
              </n-scrollbar>
            </div>
          </n-card>
        </n-gi>
      </n-grid>

      <!-- Task List + Create Task -->
      <n-card class="issue-card" :bordered="false" data-testid="issue-tasks-card">
        <template #header>
          <div class="issue-card__header">
            <div class="issue-card__title">
              {{ t('issue.taskCount', { count: issue.tasks?.length ?? 0 }) }}
            </div>
            <n-tooltip
              v-if="isOwner && issue.status !== 'closed' && issue.tasks?.length"
              trigger="hover"
              placement="top"
              :style="{ maxWidth: '260px', fontSize: '12px' }"
            >
              <template #trigger>
                <n-button
                  size="small"
                  type="primary"
                  @click="showCreateDrawer = true"
                  data-testid="issue-toggle-create-task"
                >
                  {{ t('issue.appendTask') }}
                </n-button>
              </template>
              {{ t('issue.appendTaskHint') }}
            </n-tooltip>
            <n-button
              v-else-if="isOwner && issue.status !== 'closed'"
              size="small"
              type="primary"
              @click="showCreateDrawer = true"
              data-testid="issue-toggle-create-task"
            >
              {{ t('issue.createTask') }}
            </n-button>
          </div>
        </template>
        <n-data-table
          :columns="taskColumns"
          :data="issue.tasks || []"
          :row-key="(row: Task) => row.id"
          :row-props="taskRowProps"
          :bordered="false"
        />
      </n-card>
    </n-space>

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
      <n-drawer-content :title="t('taskView.retryWithSchedule')" closable>
        <div class="retry-drawer">
          <div v-if="retryTargetTask" class="retry-drawer__summary">
            <div class="retry-drawer__summary-title">Task #{{ retryTargetTask.id }}</div>
            <div class="retry-drawer__summary-prompt markdown-content" v-html="renderedRetryPrompt"></div>
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
import { ref, computed, h, onMounted, onUnmounted, reactive, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  NButton, NSpace, NCard, NTag, NGrid, NGi, NSpin,
  NIcon, NDataTable, NInput, NDrawer, NDrawerContent,
  NRadio, NRadioGroup, NForm, NFormItem, NDatePicker, NModal, NPopconfirm, NTooltip, NScrollbar,
  useMessage,
  type DataTableColumns
} from 'naive-ui'
import { useI18n } from 'vue-i18n'
import {
  CloseCircleOutline,
  FolderOpenOutline,
  GitBranchOutline,
  GitPullRequest,
  CodeOutline,
  CreateOutline,
  TimeOutline,
  InformationCircleOutline,
  PersonOutline,
  RefreshOutline,
  TrashOutline,
} from '@vicons/ionicons5'
import HeatmapChart from '../components/HeatmapChart.vue'
import TaskFormDrawer from '../components/TaskFormDrawer.vue'
import RescheduleDrawer from '../components/RescheduleDrawer.vue'
import {
  getIssue, updateIssue, closeIssue, retryTask, deleteIssueBranch,
  getScheduledTasks, getConfig, getProjects,
  type Issue, type Task, type Project
} from '../api'
import PageHeader from '../components/PageHeader.vue'
import { useBreakpoints } from '../composables/useBreakpoints'
import { formatDateTimeUtc8Compact, parseUtcDate } from '../utils/datetime'
import { formatDurationMs, formatDurationSec } from '../utils/format'
import { extractSlotErrorMessage } from '../utils/slotError'
import { authState, isAdmin } from '../auth'
import { renderMarkdown } from '../components/task-process/taskProcessUtils'

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
let pollTimer: number | null = null
const projects = ref<Project[]>([])

const renderedDescription = computed(() => renderMarkdown(issue.value?.description ?? ''))
const renderedRetryPrompt = computed(() => renderMarkdown(retryTargetTask.value?.user_prompt ?? ''))

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

function issueBranchUrl(branchName: string | null | undefined): string | null {
  if (!branchName || !projectUrl.value) return null
  return `${projectUrl.value}/-/tree/${branchName.split('/').map(encodeURIComponent).join('/')}`
}

// Create task form
const showCreateDrawer = ref(false)
const showRetryDrawer = ref(false)
const retryTargetTask = ref<Task | null>(null)
const retryScheduleType = ref<'now' | 'scheduled'>('now')
const retryTaskSchedule = ref<number | null>(null)
const retryTaskLoading = ref(false)
const showRescheduleDrawer = ref(false)
const rescheduleTargetTask = ref<Task | null>(null)

// Schedule heatmap
const scheduledTasksForPreview = ref<Task[]>([])
const scheduledTasksLoading = ref(false)
const slotMaxTasks = ref(0)
const slotEnforce = ref(false)

// Edit modal
const showEditModal = ref(false)
const editLoading = ref(false)
const editForm = reactive({
  title: '',
  description: ''
})

// --- Constants ---
const issueStatusColors: Record<string, 'default' | 'info' | 'warning' | 'success' | 'error'> = {
  open: 'default',
  in_progress: 'warning',
  in_review: 'info',
  closed: 'success'
}

const taskStatusColors: Record<string, 'default' | 'info' | 'warning' | 'success' | 'error'> = {
  pending: 'default',
  queued: 'info',
  running: 'warning',
  completed: 'success',
  failed: 'error',
  cancelled: 'default'
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

// --- Task Table Row Props ---
function taskRowProps(row: Task) {
  return {
    style: 'cursor: pointer',
    onClick: () => router.push({ name: 'TaskView', params: { id: row.id } })
  }
}

// --- Task Table Columns ---
const taskColumns = computed<DataTableColumns<Task>>(() => {
  const renderTaskStatus = (row: Task) =>
    h(NTag, { type: taskStatusColors[row.status], size: 'small' }, () => t(`status.${row.status}`))

  return [
    {
      title: 'ID',
      key: 'id',
      width: 60
    },
    {
      title: t('common.status'),
      key: 'status',
      width: 130,
      render: renderTaskStatus
    },
    {
      title: t('issue.field.description'),
      key: 'user_prompt',
      ellipsis: {
        tooltip: {
          style: { maxWidth: '420px', wordBreak: 'break-word', whiteSpace: 'pre-wrap' }
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        } as any
      },
      render: (row) => {
        const prompt = row.user_prompt || ''
        const display = prompt.length > 80 ? prompt.slice(0, 80) + '…' : prompt
        const children = row.is_retry
          ? [
              h(NTag, { class: 'task-prompt-link__retry-badge', size: 'tiny', round: true }, () => t('common.retry')),
              display
            ]
          : display
        return h(
          'a',
          {
            class: 'task-prompt-link',
            onClick: (e: MouseEvent) => {
              e.stopPropagation()
              router.push({ name: 'TaskView', params: { id: row.id } })
            }
          },
          children
        )
      }
    },
    {
      title: t('dashboard.duration'),
      key: 'duration',
      width: 90,
      render: (row) => formatTaskDuration(row)
    },
    {
      title: t('dashboard.scheduled'),
      key: 'scheduled_at',
      width: 140,
      render: (row) => formatCompactDateTime(row.scheduled_at)
    },
    {
      title: t('common.created'),
      key: 'created_at',
      width: 140,
      render: (row) => formatCompactDateTime(row.created_at)
    },
    {
      title: '',
      key: 'actions',
      width: 120,
      render: (row) => {
        const retryTask = retriedTaskMap.value.get(row.id)
        if (retryTask) {
          return h('span', { style: 'font-size: 12px; color: var(--n-text-color-3)' }, [
            t('issue.retriedAs'),
            ' ',
            h(
              NButton,
              {
                text: true,
                type: 'primary',
                size: 'small',
                onClick: (e: MouseEvent) => {
                  e.stopPropagation()
                  router.push({ name: 'TaskView', params: { id: retryTask.id } })
                }
              },
              () => `Task #${retryTask.id}`
            )
          ])
        }
        if (!canManageIssueTask(row)) return ''
        if (canRescheduleIssueTask(row)) {
          return h(
            NButton,
            {
              size: 'small',
              secondary: true,
              strong: true,
              round: true,
              type: 'info',
              onClick: (e: MouseEvent) => {
                e.stopPropagation()
                void openRescheduleDrawer(row)
              }
            },
            () => t('taskView.rescheduleTask')
          )
        }
        if (!['failed', 'cancelled'].includes(row.status)) return ''
        return h(
          NButton,
          {
            size: 'small',
            secondary: true,
            strong: true,
            round: true,
            type: 'default',
            onClick: (e: MouseEvent) => {
              e.stopPropagation()
              void openRetryDrawer(row)
            }
          },
          () => t('issue.retryTask')
        )
      }
    }
  ]
})

// --- Helpers ---
function formatCompactDateTime(value?: string | null): string {
  if (!value) return '-'
  return formatDateTimeUtc8Compact(value)
}

function formatTaskDuration(task: Pick<Task, 'started_at' | 'completed_at'>): string {
  if (!task.started_at) return '—'
  const started = parseUtcDate(task.started_at).getTime()
  const ended = task.completed_at ? parseUtcDate(task.completed_at).getTime() : Date.now()
  if (!Number.isFinite(started) || !Number.isFinite(ended) || ended < started) return '—'
  return formatDurationMs(ended - started)
}

function canRescheduleIssueTask(task: Pick<Task, 'status' | 'scheduled_at'>): boolean {
  if (task.status === 'queued') return true
  return task.status === 'pending' && !!task.scheduled_at
}

function formatNumber(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '—'
  return Math.round(value).toLocaleString()
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
    retryTaskSchedule.value = null
  }
})

watch(showRescheduleDrawer, (val) => {
  if (!val) {
    rescheduleTargetTask.value = null
  }
})

onUnmounted(() => {
  if (pollTimer !== null) {
    clearInterval(pollTimer)
    pollTimer = null
  }
})

async function loadScheduleContext(force = false) {
  if (force || scheduledTasksForPreview.value.length === 0) {
    scheduledTasksLoading.value = true
    try {
      scheduledTasksForPreview.value = await getScheduledTasks()
    } catch {
      scheduledTasksForPreview.value = []
    } finally {
      scheduledTasksLoading.value = false
    }
  }
  try {
    const config = await getConfig()
    slotMaxTasks.value = config.runtime?.slot_max_tasks ?? 0
    slotEnforce.value = config.runtime?.slot_max_tasks_enforce ?? false
  } catch { /* ignore */ }
}

function handleRetryHeatmapCellClick(startMs: number) {
  retryTaskSchedule.value = startMs
}

async function openRetryDrawer(task: Task) {
  retryTargetTask.value = task
  retryScheduleType.value = 'now'
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
  } catch {
    message.error(t('issue.loadFailed'))
  } finally {
    loading.value = false
  }
}

async function refreshIssue() {
  await fetchIssue()
  getProjects().then(p => { projects.value = p }).catch((err) => {
    console.warn('Failed to load projects for issue view:', err)
  })
}

async function handleClose() {
  closingIssue.value = true
  try {
    issue.value = await closeIssue(issueId.value)
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
      description: editForm.description
    })
    showEditModal.value = false
    message.success(t('issue.updateSuccess'))
  } catch {
    message.error(t('issue.updateFailed'))
  } finally {
    editLoading.value = false
  }
}

async function handleRetryTask(taskId: number, scheduledDatetime?: string): Promise<boolean> {
  try {
    if (scheduledDatetime) {
      await retryTask(taskId, scheduledDatetime)
    } else {
      await retryTask(taskId)
    }
    message.success(t('issue.retrySuccess'))
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
    const success = await handleRetryTask(retryTargetTask.value.id, scheduledDatetime)
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
  showEditModal.value = true
}

onMounted(() => {
  fetchIssue()
  getProjects().then(p => { projects.value = p }).catch((err) => {
    console.warn('Failed to load projects for issue view:', err)
  })
  pollTimer = window.setInterval(() => {
    if (document.visibilityState !== 'visible') return
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
  height: 100%;
  display: flex;
  flex-direction: column;
}

.issue-card :deep(.n-card-content) {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.stat-add {
  color: #18a058;
  font-weight: 500;
}

.stat-del {
  color: #d03050;
  font-weight: 500;
}

.metadata-secondary {
  font-size: 12px;
  color: rgba(15, 23, 42, 0.45);
  margin-left: 4px;
}

.issue-card__header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 12px;
}

.issue-card__title {
  font-size: 18px;
  font-weight: 600;
}

.issue-view__description-wrap {
  background: rgba(15, 23, 42, 0.035);
  border-radius: 8px;
  overflow: hidden;
  flex: 1;
  position: relative;
  min-height: 0;
}

.issue-view__description {
  padding: 12px 14px;
  line-height: 1.6;
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
  overflow-x: auto; font-family: var(--n-font-family-mono, monospace);
  font-size: 0.85em; line-height: 1.55; white-space: pre;
}
.issue-view__description :deep(pre.md-code-block code) { background: none; padding: 0; border-radius: 0; font-size: inherit; color: inherit; }
.issue-view__description :deep(table) { width: 100%; border-collapse: collapse; margin: 0.6em 0; font-size: 0.9em; overflow-x: auto; display: block; }
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

.retry-drawer__summary-title {
  font-size: 13px;
  font-weight: 600;
  color: rgba(15, 23, 42, 0.76);
}

.retry-drawer__summary-prompt {
  max-height: 96px;
  overflow-y: auto;
  word-break: break-word;
  font-size: 13px;
  line-height: 1.55;
  color: rgba(15, 23, 42, 0.72);
}
.retry-drawer__summary-prompt :deep(p) { margin: 0 0 0.5em; }
.retry-drawer__summary-prompt :deep(p:last-child) { margin-bottom: 0; }
.retry-drawer__summary-prompt :deep(ul),
.retry-drawer__summary-prompt :deep(ol) { margin: 0.3em 0; padding-left: 1.4em; }
.retry-drawer__summary-prompt :deep(li) { margin: 0.1em 0; }
.retry-drawer__summary-prompt :deep(code) {
  font-family: var(--n-font-family-mono, monospace);
  font-size: 0.88em; background: rgba(128,128,128,0.12);
  border-radius: 3px; padding: 0.1em 0.3em;
}
.retry-drawer__summary-prompt :deep(pre.md-code-block) {
  margin: 0.4em 0; padding: 8px 10px;
  background: rgba(0,0,0,0.06); border-radius: 4px;
  overflow-x: auto; font-size: 0.82em; white-space: pre;
}
.retry-drawer__summary-prompt :deep(pre.md-code-block code) { background: none; padding: 0; font-size: inherit; }

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

.metadata-body {
  display: grid;
  grid-template-columns: max-content minmax(0, 1fr);
  column-gap: 12px;
  row-gap: 14px;
  align-items: baseline;
}

.metadata-row {
  display: contents;
}

.metadata-label {
  display: inline-flex;
  align-items: center;
  font-size: 13px;
  color: var(--n-text-color-3, #999);
  white-space: nowrap;
}

.metadata-row > :last-child {
  min-width: 0;
}

.issue-view :deep(.task-prompt-link) {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: var(--n-text-color);
  cursor: pointer;
  min-width: 0;
}

.issue-view :deep(.task-prompt-link__retry-badge) {
  --n-color: #eef2ff !important;
  --n-border: 1px solid #c7d2fe !important;
  --n-text-color: #4338ca !important;
  flex: 0 0 auto;
}

.metadata-label-icon {
  vertical-align: middle;
  margin-right: 3px;
  opacity: 0.65;
}

.metadata-value {
  min-width: 0;
  font-size: 14px;
  color: var(--n-text-color-1);
  word-break: break-word;
}

.metadata-muted {
  color: var(--n-text-color-3, #999);
}

.branch-flow {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}

.branch-item {
  padding: 2px 8px;
  border-radius: 4px;
  font-size: 12px;
  font-family: var(--n-font-family-mono, 'JetBrains Mono', monospace);
  background: rgba(128, 128, 128, 0.08);
}

.branch-item--base {
  background: rgba(2, 132, 199, 0.08);
  color: #0284c7;
}

.branch-item--work {
  background: rgba(5, 150, 105, 0.08);
  color: #059669;
}

.branch-item--target {
  background: rgba(124, 58, 237, 0.08);
  color: #7c3aed;
}

.branch-arrow {
  color: var(--n-text-color-3, #999);
  font-size: 12px;
}

.time-axis {
  display: flex;
  align-items: flex-start;
  gap: 6px 8px;
  flex-wrap: wrap;
}

.time-axis__sep {
  color: var(--n-text-color-3, #999);
  margin-top: 2px;
  flex-shrink: 0;
}

.time-point {
  display: flex;
  flex-direction: column;
  gap: 2px;
  flex: 0 0 auto;
  min-width: 0;
}

.time-point__label {
  font-size: 11px;
  color: var(--n-text-color-3, #999);
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

.time-point__value {
  font-size: 13px;
  color: var(--n-text-color-2);
}

.app-link {
  color: var(--n-primary-color, #18a058);
  text-decoration: none;
}
.app-link:hover {
  text-decoration: underline;
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
