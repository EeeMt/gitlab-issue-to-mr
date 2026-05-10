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
        <template #actions>
          <n-button @click="refreshIssue" :loading="loading">
            {{ t('common.refresh') }}
          </n-button>
          <template v-if="isOwner">
            <n-button data-testid="issue-edit-button" :disabled="issue.status === 'closed'" @click="openEditModal">
              {{ t('issue.edit') }}
            </n-button>
            <n-popconfirm @positive-click="handleClose">
              <template #trigger>
                <n-button
                  type="error"
                  secondary
                  :disabled="issue.status === 'closed'"
                  data-testid="issue-close-button"
                >
                  {{ t('issue.close') }}
                </n-button>
              </template>
              {{ t('issue.confirmClose') }}
            </n-popconfirm>
          </template>
        </template>
      </PageHeader>

      <!-- Metadata + Description side by side -->
      <n-grid :cols="issue.description ? (isMobile ? 1 : 2) : 1" :x-gap="16" :y-gap="16">
        <n-gi>
          <!-- Metadata -->
          <n-card class="issue-card" :bordered="false" data-testid="issue-metadata-card">
            <template #header>
              <div class="issue-card__header">
                <div class="issue-card__title">{{ t('issue.detail') }}</div>
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
                  <router-link :to="{ path: '/issues', query: { project_id: issue.project_id } }" class="app-link">
                    {{ projectName }}
                  </router-link>
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
                    <span v-if="issue.base_branch" class="branch-item branch-item--base">{{ issue.base_branch }}</span>
                    <span v-if="issue.base_branch && issue.branch_name" class="branch-arrow">➜</span>
                    <span v-if="issue.branch_name" class="branch-item branch-item--work">{{ issue.branch_name }}</span>
                    <span v-if="issue.branch_name && issue.target_branch" class="branch-arrow">➜</span>
                    <span v-if="issue.target_branch" class="branch-item branch-item--target">{{ issue.target_branch }}</span>
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
              <div class="issue-view__description">{{ issue.description }}</div>
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
            <n-button
              v-if="isOwner && issue.status !== 'closed'"
              size="small"
              type="primary"
              @click="showCreateDrawer = true"
              data-testid="issue-toggle-create-task"
            >
              {{ issue.tasks?.length ? t('issue.appendTask') : t('issue.createTask') }}
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

    <!-- Template Picker Drawer -->
    <n-drawer v-model:show="showTemplateDrawer" :width="isMobile ? '100%' : 480" placement="right">
      <div class="template-drawer-layout">
        <div class="template-drawer-layout__header">
          <span class="template-drawer-layout__title">{{ t('createTask.selectTemplate') }}</span>
          <n-button quaternary circle @click="showTemplateDrawer = false">
            <template #icon><n-icon size="18"><CloseOutline /></n-icon></template>
          </n-button>
        </div>
        <Transition name="banner-slide">
          <div v-if="pendingTemplate" class="template-overwrite-banner">
            <span class="template-overwrite-banner__text">{{ t('createTask.templateOverwriteConfirm') }}</span>
            <div class="template-overwrite-banner__actions">
              <n-button size="small" @click="cancelTemplateOverwrite">{{ t('common.cancel') }}</n-button>
              <n-button size="small" type="primary" @click="confirmTemplateOverwrite">{{ t('common.confirm') }}</n-button>
            </div>
          </div>
        </Transition>
        <div class="template-drawer-layout__body">
          <div v-if="promptTemplates.length === 0" class="prompt-template-dropdown__empty">
            {{ t('createTask.noPromptTemplates') }}
          </div>
          <div
            v-for="tmpl in promptTemplates"
            :key="tmpl.id"
            class="prompt-template-dropdown__item"
            :class="{ 'prompt-template-dropdown__item--pending': pendingTemplate?.id === tmpl.id }"
            @click="handleTemplateItemClick(tmpl)"
          >
            <div class="prompt-template-dropdown__item-name">{{ tmpl.name }}</div>
            <div class="prompt-template-dropdown__item-preview">{{ tmpl.content.substring(0, 80) }}...</div>
          </div>
        </div>
      </div>
    </n-drawer>

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

    <!-- Create Task Drawer -->
    <n-drawer
      v-model:show="showCreateDrawer"
      :width="isMobile ? '100%' : 640"
      placement="right"
      data-testid="issue-create-task-drawer"
    >
      <n-drawer-content :title="t('issue.createTask')" closable>
        <n-form label-placement="top" class="issue-view__create-form">
          <!-- Prompt -->
          <n-form-item>
            <template #label>
              <div class="prompt-label-row">
                <span>{{ t('issue.field.description') }}</span>
                <n-button
                  size="tiny"
                  :disabled="promptTemplatesLoading || promptTemplates.length === 0"
                  :loading="promptTemplatesLoading"
                  type="primary"
                  ghost
                  @click="showTemplateDrawer = true"
                >
                  <template #icon>
                    <n-icon :component="DocumentTextOutline" size="12" />
                  </template>
                  {{ t('createTask.useTemplate') }}
                </n-button>
              </div>
            </template>
            <VariableEditor
              v-model="newTaskPrompt"
              :variable-tips="promptVariableTips"
              :placeholder="issue?.description || t('issue.promptPlaceholder')"
            />
            <template #feedback>
              <div v-if="unreplacedVariables.length > 0" class="prompt-variable-warning">
                <n-icon :component="WarningOutline" size="14" />
                <span>{{ t('createTask.unreplacedVariablesHint') }}: {{ unreplacedVariables.join(', ') }}</span>
              </div>
            </template>
          </n-form-item>

          <!-- Priority cards -->
          <n-form-item :label="t('common.priority')">
            <n-radio-group v-model:value="newTaskPriority" class="priority-selector">
              <div
                v-for="opt in priorityOptions"
                :key="opt.value"
                class="priority-card"
                :class="[
                  `priority-card--p${opt.value}`,
                  { 'priority-card--active': newTaskPriority === opt.value }
                ]"
                @click="newTaskPriority = opt.value"
              >
                <n-radio :value="opt.value" />
                <div>
                  <div class="priority-card__label">{{ opt.label }}</div>
                  <div class="priority-card__desc">{{ opt.desc }}</div>
                </div>
              </div>
            </n-radio-group>
          </n-form-item>

          <!-- Schedule -->
          <n-form-item :label="t('createTask.schedule')">
            <div class="schedule-section">
              <n-radio-group v-model:value="scheduleType">
                <n-radio value="now">{{ t('createTask.executeNow') }}</n-radio>
                <n-radio value="scheduled">{{ t('createTask.scheduleAt') }}</n-radio>
              </n-radio-group>
              <div class="schedule-row" :class="{ 'schedule-row--hidden': scheduleType !== 'scheduled' }">
                <n-date-picker
                  v-model:value="newTaskSchedule"
                  type="datetime"
                  clearable
                  style="width: 200px; flex-shrink: 0"
                  :is-date-disabled="isScheduleDateDisabled"
                />
                <n-button
                  size="small"
                  secondary
                  :loading="scheduledTasksLoading"
                  @click="openScheduleDrawer"
                >
                  <template #icon><n-icon :component="CalendarOutline" /></template>
                  {{ t('createTask.viewScheduleHeatmap') }}
                </n-button>
              </div>
            </div>
          </n-form-item>

          <!-- AI Provider -->
          <n-form-item :label="t('config.providers.providerLabel')">
            <n-select
              v-model:value="selectedProviderId"
              :options="providerOptions"
              clearable
              :placeholder="t('config.providers.systemDefault')"
            />
          </n-form-item>

          <!-- Require Changes (only when issue has target_branch / MR mode) -->
          <n-form-item
            v-if="issue?.target_branch"
            :label="t('issue.requireChanges')"
          >
            <n-switch v-model:value="requireChanges" />
            <template #feedback>
              {{ t('issue.requireChangesHint') }}
            </template>
          </n-form-item>
        </n-form>

        <!-- Slot capacity alert -->
        <n-alert
          v-if="slotCapacity?.is_full"
          :type="slotCapacity.enforce ? 'error' : 'warning'"
          style="margin-bottom: 16px;"
        >
          {{ slotCapacity.enforce
            ? t('createTask.slotFullError', {
                start: formatDateTimeUtc8Compact(slotCapacity.hour_start),
                end: formatTimeUtc8(slotCapacity.hour_end),
                count: slotCapacity.count,
                max: slotCapacity.max
              })
            : t('createTask.slotFullWarning', {
                start: formatDateTimeUtc8Compact(slotCapacity.hour_start),
                end: formatTimeUtc8(slotCapacity.hour_end),
                count: slotCapacity.count,
                max: slotCapacity.max
              })
          }}
        </n-alert>

        <n-alert
          v-if="createTaskUsageLimitDetail"
          type="warning"
          style="margin-bottom: 16px;"
        >
          <div data-testid="issue-create-task-usage-alert" class="issue-view__usage-limit-alert">
            <div class="issue-view__usage-limit-title">{{ t('createTask.usageLimitExceededTitle') }}</div>
            <div
              v-for="item in createTaskUsageLimitDetail.exceeded_items"
              :key="`${item.field}-${item.reset_at}`"
              class="issue-view__usage-limit-row"
            >
              <span>{{ t(`createTask.usageWindow.${item.window}`) }}</span>
              <span>{{ t(`createTask.usageMetric.${item.metric}`) }}</span>
              <span>{{ t('createTask.usageLimitUsed') }} {{ item.used }}/{{ item.limit }}</span>
              <span>{{ t('createTask.usageLimitReset') }} {{ formatUsageResetAt(item.reset_at) }}</span>
            </div>
          </div>
        </n-alert>

        <template #footer>
          <div style="display: flex; justify-content: flex-end;">
            <n-button
              type="primary"
              :loading="createTaskLoading"
              data-testid="issue-create-task-button"
              @click="handleCreateTask"
            >
              {{ t('issue.createTask') }}
            </n-button>
          </div>
        </template>
      </n-drawer-content>
    </n-drawer>

    <!-- Schedule Heatmap Drawer -->
    <n-drawer v-model:show="showScheduleDrawer" :width="isMobile ? '100%' : 580" placement="right">
      <n-drawer-content :title="t('createTask.schedulePreviewTitle')" closable>
        <n-spin v-if="scheduledTasksLoading" :description="t('createTask.schedulePreviewLoading')" />
        <template v-else>
          <p style="margin-bottom: 12px; color: var(--n-text-color-3); font-size: 13px;">
            {{ t('createTask.schedulePreviewHint') }}
          </p>
          <HeatmapChart
            :tasks="scheduledTasksForPreview"
            :selected-ms="heatmapSelectedMs"
            :max-per-slot="slotMaxTasks"
            :enforce-capacity="slotEnforce"
            @cell-click="handleScheduleHeatmapCellClick"
          />
        </template>
      </n-drawer-content>
    </n-drawer>
  </div>

  <!-- Loading state before issue is loaded -->
  <n-spin v-else :show="loading" style="min-height: 200px" />
</template>

<script setup lang="ts">
import { ref, computed, h, onMounted, onUnmounted, reactive, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  NButton, NSpace, NCard, NTag, NGrid, NGi, NSpin,
  NIcon, NDataTable, NInput, NDrawer, NDrawerContent, NSelect,
  NRadio, NRadioGroup, NForm, NFormItem, NDatePicker, NModal, NPopconfirm, NAlert, NSwitch,
  useMessage,
  type DataTableColumns
} from 'naive-ui'
import { useI18n } from 'vue-i18n'
import {
  FolderOpenOutline,
  GitBranchOutline,
  GitPullRequest,
  CodeOutline,
  TimeOutline,
  InformationCircleOutline,
  DocumentTextOutline,
  WarningOutline,
  CalendarOutline,
  PersonOutline,
  CloseOutline
} from '@vicons/ionicons5'
import VariableEditor from '../components/VariableEditor.vue'
import HeatmapChart from '../components/HeatmapChart.vue'
import {
  getIssue, updateIssue, closeIssue, createTask, retryTask, getPromptTemplates,
  getScheduledTasks, getSlotCapacity, getConfig, getProjects, getProviders,
  type Issue, type Task, type PromptTemplate, type SlotCapacityInfo, type Project, type AIProvider
} from '../api'
import PageHeader from '../components/PageHeader.vue'
import { useBreakpoints } from '../composables/useBreakpoints'
import { formatDateTimeUtc8Compact, formatTimeUtc8 } from '../utils/datetime'
import { extractSlotErrorMessage } from '../utils/slotError'
import { formatUsageResetAt, isUsageLimitExceededDetail, type UsageLimitExceededDetail } from '../utils/usageLimits'
import { authState, isAdmin } from '../auth'

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

// --- State ---
const issue = ref<Issue | null>(null)
const loading = ref(false)
let pollTimer: number | null = null
const projects = ref<Project[]>([])

const projectName = computed(() => {
  if (!issue.value) return '-'
  const project = projects.value.find(p => p.id === issue.value!.project_id)
  return project ? project.path_with_namespace : `Project #${issue.value.project_id}`
})

// Create task form
const showCreateDrawer = ref(false)
const newTaskPrompt = ref('')
const newTaskPriority = ref(1)
const newTaskSchedule = ref<number | null>(null)
const createTaskLoading = ref(false)
const createTaskUsageLimitDetail = ref<UsageLimitExceededDetail | null>(null)
const providers = ref<AIProvider[]>([])
const selectedProviderId = ref<number | null>(null)
const promptTemplates = ref<PromptTemplate[]>([])
const promptTemplatesLoading = ref(false)
const promptVariableTips = ref<Record<string, string> | undefined>(undefined)
const showTemplateDrawer = ref(false)
const pendingTemplate = ref<PromptTemplate | null>(null)

watch(showTemplateDrawer, (val) => {
  if (!val) pendingTemplate.value = null
})
const scheduleType = ref<'now' | 'scheduled'>('now')
const requireChanges = ref(true)

// Schedule heatmap
const scheduledTasksForPreview = ref<Task[]>([])
const scheduledTasksLoading = ref(false)
const showScheduleDrawer = ref(false)
const slotCapacity = ref<SlotCapacityInfo | null>(null)
const slotCapacityLoading = ref(false)
const slotMaxTasks = ref(0)
const slotEnforce = ref(false)
let slotCheckTimeout: ReturnType<typeof setTimeout> | undefined
let slotCheckGeneration = 0

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

const priorityOptions = [
  { label: 'P0', value: 0, desc: t('createTask.priorityP0Desc') },
  { label: 'P1', value: 1, desc: t('createTask.priorityP1Desc') },
  { label: 'P2', value: 2, desc: t('createTask.priorityP2Desc') }
]

const unreplacedVariables = computed(() => {
  const content = newTaskPrompt.value || ''
  const matches = content.match(/\{\{([^}]+)\}\}/g)
  if (!matches) return []
  return matches.map(m => m.replace(/\{\{|\}\}/g, ''))
})

const hasExistingPrompt = computed(() =>
  Boolean(newTaskPrompt.value && newTaskPrompt.value.trim())
)

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
      width: 100,
      render: renderTaskStatus
    },
    {
      title: t('issue.field.description'),
      key: 'user_prompt',
      ellipsis: {
        tooltip: {
          maxWidth: 420,
          style: { maxWidth: '420px', wordBreak: 'break-word', whiteSpace: 'pre-wrap' }
        }
      },
      render: (row) => {
        return h(
          'a',
          {
            style: 'cursor: pointer; color: var(--n-text-color);',
            onClick: (e: MouseEvent) => {
              e.stopPropagation()
              router.push({ name: 'TaskView', params: { id: row.id } })
            }
          },
          row.user_prompt
        )
      }
    },
    {
      title: t('common.retry'),
      key: 'is_retry',
      width: 70,
      render: (row) =>
        row.is_retry
          ? h(NTag, { size: 'tiny', round: true, type: 'warning' }, () => t('common.retry'))
          : ''
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
        if (!['failed', 'cancelled'].includes(row.status)) return ''
        if (!isOwner.value) return ''
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
              handleRetryTask(row.id)
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

// --- Schedule Heatmap ---
const heatmapSelectedMs = computed<number | null>(() => newTaskSchedule.value)

function checkSlotCapacity() {
  slotCapacity.value = null
  if (slotCheckTimeout) clearTimeout(slotCheckTimeout)
  slotCheckGeneration++

  const ms = heatmapSelectedMs.value
  if (!ms) return

  const currentGeneration = slotCheckGeneration
  slotCheckTimeout = setTimeout(async () => {
    slotCapacityLoading.value = true
    try {
      const result = await getSlotCapacity(new Date(ms).toISOString())
      if (currentGeneration !== slotCheckGeneration) return
      slotCapacity.value = result
    } catch {
      if (currentGeneration !== slotCheckGeneration) return
      slotCapacity.value = null
    } finally {
      if (currentGeneration === slotCheckGeneration) {
        slotCapacityLoading.value = false
      }
    }
  }, 300)
}

watch(heatmapSelectedMs, () => checkSlotCapacity())

watch(scheduleType, (val) => {
  if (val === 'now') {
    newTaskSchedule.value = null
  }
})

watch(showCreateDrawer, (val) => {
  if (val && !newTaskPrompt.value && issue.value?.description) {
    newTaskPrompt.value = issue.value.description
  }
  if (!val) {
    createTaskUsageLimitDetail.value = null
  }
})

onUnmounted(() => {
  if (slotCheckTimeout) clearTimeout(slotCheckTimeout)
  slotCheckGeneration++
  if (pollTimer !== null) {
    clearInterval(pollTimer)
    pollTimer = null
  }
})

async function openScheduleDrawer() {
  showScheduleDrawer.value = true
  if (scheduledTasksForPreview.value.length === 0) {
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

function handleScheduleHeatmapCellClick(startMs: number) {
  newTaskSchedule.value = startMs
  showScheduleDrawer.value = false
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
  fetchPromptTemplates()
  getProjects().then(p => { projects.value = p }).catch(() => {})
  getProviders().then(data => { providers.value = data }).catch(() => {})
}

async function handleClose() {
  try {
    issue.value = await closeIssue(issueId.value)
    message.success(t('issue.closeSuccess'))
  } catch {
    message.error(t('issue.closeFailed'))
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

async function handleCreateTask() {
  // Validate scheduled time is in the future
  if (scheduleType.value === 'scheduled') {
    if (!newTaskSchedule.value) {
      message.warning(t('createTask.pleaseSelectScheduledTime'))
      return
    }
    if (newTaskSchedule.value <= Date.now()) {
      message.warning(t('createTask.scheduledTimeFuture'))
      return
    }
  }

  createTaskLoading.value = true
  createTaskUsageLimitDetail.value = null
  try {
    const request: Parameters<typeof createTask>[0] = {
      issue_id: issueId.value,
      priority: newTaskPriority.value
    }
    if (newTaskPrompt.value.trim()) {
      request.user_prompt = newTaskPrompt.value.trim()
    }
    if (scheduleType.value === 'scheduled' && newTaskSchedule.value) {
      request.scheduled_datetime = new Date(newTaskSchedule.value).toISOString()
    }
    request.provider_id = selectedProviderId.value ?? defaultProviderId.value ?? undefined
    request.require_changes = requireChanges.value
    await createTask(request)
    message.success(t('issue.taskCreated'))
    if (showScheduleDrawer.value) {
      scheduledTasksLoading.value = true
      try {
        scheduledTasksForPreview.value = await getScheduledTasks()
      } catch {
        scheduledTasksForPreview.value = []
      } finally {
        scheduledTasksLoading.value = false
      }
    } else {
      scheduledTasksForPreview.value = []
    }
    newTaskPrompt.value = ''
    newTaskSchedule.value = null
    selectedProviderId.value = null
    scheduleType.value = 'now'
    showCreateDrawer.value = false
    await fetchIssue()
  } catch (error: any) {
    const detail = error?.response?.data?.detail
    if (isUsageLimitExceededDetail(detail)) {
      createTaskUsageLimitDetail.value = detail
    } else {
      message.error(extractSlotErrorMessage(error, t, 'createTask.failedToCreateTask'))
    }
  } finally {
    createTaskLoading.value = false
  }
}

async function handleRetryTask(taskId: number) {
  try {
    await retryTask(taskId)
    message.success(t('issue.retrySuccess'))
    await fetchIssue()
  } catch (error: any) {
    const detail = error?.response?.data?.detail
    message.error(typeof detail === 'string' ? detail : t('issue.retryFailed'))
  }
}

async function fetchPromptTemplates() {
  promptTemplatesLoading.value = true
  try {
    promptTemplates.value = await getPromptTemplates()
  } catch {
    // Non-critical
  } finally {
    promptTemplatesLoading.value = false
  }
}

function applyPromptTemplate(tmpl: PromptTemplate) {
  newTaskPrompt.value = tmpl.content
  if (tmpl.variable_tips) {
    promptVariableTips.value = tmpl.variable_tips
  }
}

function handleTemplateItemClick(tmpl: PromptTemplate) {
  if (!hasExistingPrompt.value) {
    applyPromptTemplate(tmpl)
    showTemplateDrawer.value = false
  } else {
    pendingTemplate.value = tmpl
  }
}

function confirmTemplateOverwrite() {
  if (pendingTemplate.value) {
    applyPromptTemplate(pendingTemplate.value)
    pendingTemplate.value = null
    showTemplateDrawer.value = false
  }
}

function cancelTemplateOverwrite() {
  pendingTemplate.value = null
}

// --- Lifecycle ---
function openEditModal() {
  if (!issue.value) return
  editForm.title = issue.value.title
  editForm.description = issue.value.description || ''
  showEditModal.value = true
}

const providerOptions = computed(() =>
  providers.value.map(p => ({
    label: `${p.name} (${p.model})${p.is_default ? ' ★' : ''}`,
    value: p.id,
  }))
)

const defaultProviderId = computed(() =>
  providers.value.find(p => p.is_default)?.id ?? null
)

onMounted(() => {
  fetchIssue()
  fetchPromptTemplates()
  getProjects().then(p => { projects.value = p }).catch(() => {})
  getProviders().then(data => { providers.value = data }).catch(() => {})
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

.issue-card :deep(.n-card__content) {
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
  flex: 1;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

.issue-view__description {
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

.issue-view__code {
  font-family: 'SF Mono', 'Fira Code', 'Fira Mono', Menlo, Consolas, monospace;
  font-size: 13px;
  padding: 2px 8px;
  border-radius: 6px;
  background: rgba(15, 23, 42, 0.06);
  word-break: break-all;
}

.issue-view__create-form {
  max-width: 100%;
}

.issue-view__create-form :deep(.variable-editor__codemirror .cm-editor) {
  min-height: 200px;
}

.prompt-label-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  width: 100%;
  gap: 8px;
}

.prompt-label-row span {
  flex-shrink: 0;
}

.prompt-label-row .n-button {
  flex-shrink: 0;
}

.priority-selector {
  display: flex;
  gap: 8px;
  width: 100%;
}
.priority-card {
  flex: 1;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  border: 1px solid var(--n-border-color);
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.15s;
}
.priority-card:hover {
  border-color: var(--n-primary-color);
}
.priority-card--active.priority-card--p0 {
  border-color: #e88080;
  background: rgba(232, 128, 128, 0.06);
}
.priority-card--active.priority-card--p1 {
  border-color: #f0a020;
  background: rgba(240, 160, 32, 0.06);
}
.priority-card--active.priority-card--p2 {
  border-color: #63e2b7;
  background: rgba(99, 226, 183, 0.06);
}
.priority-card--p0 .priority-card__label { color: #d03050; }
.priority-card--p1 .priority-card__label { color: #f0a020; }
.priority-card--p2 .priority-card__label { color: #18a058; }
.priority-card__label { font-weight: 600; font-size: 13px; }
.priority-card__desc { font-size: 11px; color: var(--n-text-color-3); }

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

.prompt-variable-warning {
  display: flex;
  align-items: center;
  gap: 4px;
  color: #f0a020;
  font-size: 12px;
}

.prompt-template-dropdown__empty {
  padding: 16px;
  text-align: center;
  color: var(--n-text-color-3);
}

.template-drawer-layout {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: var(--n-color, #fff);
}

.template-drawer-layout__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 20px;
  border-bottom: 1px solid rgba(0, 0, 0, 0.09);
  flex-shrink: 0;
}

.template-drawer-layout__title {
  font-size: 18px;
  font-weight: 500;
  color: rgba(15, 23, 42, 0.9);
}

.template-drawer-layout__body {
  flex: 1;
  overflow-y: auto;
  padding: 8px 0;
}

.prompt-template-dropdown__item {
  padding: 12px 16px;
  cursor: pointer;
  border-bottom: 1px solid rgba(128, 128, 128, 0.1);
}

.prompt-template-dropdown__item:hover {
  background: rgba(128, 128, 128, 0.05);
}

.prompt-template-dropdown__item--pending {
  background-color: rgba(32, 128, 240, 0.08);
  border-left: 3px solid #2080f0;
  padding-left: 9px;
}

.prompt-template-dropdown__item-name {
  font-weight: 600;
  margin-bottom: 4px;
}

.prompt-template-dropdown__item-preview {
  font-size: 12px;
  color: var(--n-text-color-3);
}

.template-overwrite-banner {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 14px;
  margin: 0 12px;
  background: rgba(255, 160, 32, 0.1);
  border: 1px solid rgba(255, 160, 32, 0.4);
  border-radius: 10px;
  flex-shrink: 0;
}

.banner-slide-enter-active,
.banner-slide-leave-active {
  transition: opacity 0.22s ease, transform 0.22s ease, max-height 0.22s ease, margin 0.22s ease, padding 0.22s ease;
  overflow: hidden;
  max-height: 80px;
}

.banner-slide-enter-from,
.banner-slide-leave-to {
  opacity: 0;
  transform: translateY(-6px);
  max-height: 0;
  margin-top: 0;
  margin-bottom: 0;
  padding-top: 0;
  padding-bottom: 0;
}

.template-overwrite-banner__text {
  flex: 1;
  font-size: 13px;
  color: rgba(15, 23, 42, 0.82);
}

.template-overwrite-banner__actions {
  display: flex;
  gap: 8px;
  flex-shrink: 0;
}

.metadata-body {
  display: grid;
  gap: 14px;
}

.metadata-row {
  display: flex;
  gap: 12px;
  align-items: baseline;
}

.metadata-label {
  font-size: 13px;
  color: var(--n-text-color-3, #999);
  min-width: 90px;
  flex-shrink: 0;
}

.metadata-label-icon {
  vertical-align: middle;
  margin-right: 3px;
  opacity: 0.65;
}

.metadata-value {
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

  .issue-card__header {
    flex-direction: column;
    align-items: flex-start;
  }
}
</style>
