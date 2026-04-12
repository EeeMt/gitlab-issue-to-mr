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
          <n-button data-testid="issue-edit-button" @click="openEditModal">
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
      </PageHeader>

      <!-- Metadata -->
      <n-card class="issue-card" :bordered="false" data-testid="issue-metadata-card">
        <template #header>
          <div class="issue-card__header">
            <div class="issue-card__title">{{ t('issue.detail') }}</div>
          </div>
        </template>
        <n-descriptions :column="isMobile ? 1 : 2" label-placement="left" bordered>
          <n-descriptions-item :label="t('common.status')">
            <n-tag :type="issueStatusColors[issue.status]" size="small" round>
              {{ t(`issue.status.${issue.status}`) }}
            </n-tag>
          </n-descriptions-item>
          <n-descriptions-item :label="t('issue.field.project')">
            {{ issue.project_id }}
          </n-descriptions-item>
          <n-descriptions-item :label="t('issue.field.branch')">
            {{ issue.branch_name || '-' }}
          </n-descriptions-item>
          <n-descriptions-item :label="t('issue.field.baseBranch')">
            {{ issue.base_branch || '-' }}
          </n-descriptions-item>
          <n-descriptions-item :label="t('issue.field.targetBranch')">
            {{ issue.target_branch || '-' }}
          </n-descriptions-item>
          <n-descriptions-item :label="t('issue.field.mergeRequest')">
            <a
              v-if="issue.merge_request_url"
              :href="issue.merge_request_url"
              target="_blank"
              rel="noopener noreferrer"
              class="app-link"
            >
              !{{ issue.merge_request_iid }}
            </a>
            <span v-else>-</span>
          </n-descriptions-item>
          <n-descriptions-item :label="t('issue.field.sessionId')">
            <code v-if="issue.claude_session_id" class="issue-view__code">
              {{ issue.claude_session_id }}
            </code>
            <span v-else>-</span>
          </n-descriptions-item>
          <n-descriptions-item :label="t('issue.field.createdAt')">
            {{ formatCompactDateTime(issue.created_at) }}
          </n-descriptions-item>
          <n-descriptions-item :label="t('issue.field.updatedAt')">
            {{ formatCompactDateTime(issue.updated_at) }}
          </n-descriptions-item>
        </n-descriptions>
      </n-card>

      <!-- Description -->
      <n-card
        v-if="issue.description"
        class="issue-card"
        :bordered="false"
        data-testid="issue-description-card"
      >
        <template #header>
          <div class="issue-card__header">
            <div class="issue-card__title">{{ t('issue.field.description') }}</div>
          </div>
        </template>
        <div class="issue-view__description">{{ issue.description }}</div>
      </n-card>

      <!-- Task List -->
      <n-card class="issue-card" :bordered="false" data-testid="issue-tasks-card">
        <template #header>
          <div class="issue-card__header">
            <div class="issue-card__title">
              {{ t('issue.taskCount', { count: issue.tasks?.length ?? 0 }) }}
            </div>
          </div>
        </template>
        <n-data-table
          :columns="taskColumns"
          :data="issue.tasks || []"
          :row-key="(row: Task) => row.id"
          :bordered="false"
        />
      </n-card>

      <!-- Create Task Form -->
      <n-card class="issue-card" :bordered="false" data-testid="issue-create-task-card">
        <template #header>
          <div class="issue-card__header">
            <div class="issue-card__title">{{ t('issue.createTask') }}</div>
          </div>
        </template>
        <n-form label-placement="top" class="issue-view__create-form">
          <n-form-item :label="t('issue.field.description')">
            <n-input
              v-model:value="newTaskPrompt"
              type="textarea"
              :placeholder="issue.description || t('issue.promptPlaceholder')"
              :rows="4"
              data-testid="issue-task-prompt"
            />
          </n-form-item>
          <n-grid :cols="isMobile ? 1 : 3" :x-gap="16" :y-gap="12">
            <n-gi>
              <n-form-item :label="t('common.priority')">
                <n-select
                  v-model:value="newTaskPriority"
                  :options="priorityOptions"
                />
              </n-form-item>
            </n-gi>
            <n-gi>
              <n-form-item :label="t('issue.scheduleDelayed')">
                <n-date-picker
                  v-model:value="newTaskSchedule"
                  type="datetime"
                  clearable
                  style="width: 100%"
                  :is-date-disabled="isScheduleDateDisabled"
                />
              </n-form-item>
            </n-gi>
            <n-gi>
              <n-form-item label="&nbsp;">
                <n-button
                  type="primary"
                  :loading="createTaskLoading"
                  data-testid="issue-create-task-button"
                  @click="handleCreateTask"
                >
                  {{ t('issue.createTask') }}
                </n-button>
              </n-form-item>
            </n-gi>
          </n-grid>
        </n-form>
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
  </div>

  <!-- Loading state before issue is loaded -->
  <n-spin v-else :show="loading" style="min-height: 200px" />
</template>

<script setup lang="ts">
import { ref, computed, h, onMounted, reactive } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  NButton, NSpace, NCard, NTag, NGrid, NGi, NSpin,
  NDescriptions, NDescriptionsItem, NDataTable, NInput,
  NSelect, NForm, NFormItem, NDatePicker, NModal, NPopconfirm,
  useMessage,
  type DataTableColumns
} from 'naive-ui'
import { useI18n } from 'vue-i18n'
import {
  getIssue, updateIssue, closeIssue, createTask, retryTask,
  type Issue, type Task
} from '../api'
import PageHeader from '../components/PageHeader.vue'
import { useBreakpoints } from '../composables/useBreakpoints'
import { formatDateTimeUtc8Compact } from '../utils/datetime'

const route = useRoute()
const router = useRouter()
const message = useMessage()
const { t } = useI18n()
const { isMobile } = useBreakpoints()

const issueId = computed(() => Number(route.params.id))

// --- State ---
const issue = ref<Issue | null>(null)
const loading = ref(false)

// Create task form
const newTaskPrompt = ref('')
const newTaskPriority = ref(1)
const newTaskSchedule = ref<number | null>(null)
const createTaskLoading = ref(false)

// Edit modal
const showEditModal = ref(false)
const editLoading = ref(false)
const editForm = reactive({
  title: '',
  description: ''
})

// --- Constants ---
const issueStatusColors: Record<string, 'default' | 'info' | 'warning' | 'success' | 'error'> = {
  open: 'info',
  in_progress: 'warning',
  completed: 'success',
  closed: 'default'
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
  { label: 'P0', value: 0 },
  { label: 'P1', value: 1 },
  { label: 'P2', value: 2 }
]

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
      ellipsis: { tooltip: true },
      render: (row) => {
        const truncated = row.user_prompt.length > 80
          ? row.user_prompt.substring(0, 80) + '…'
          : row.user_prompt
        return h(
          'a',
          {
            style: 'cursor: pointer; color: var(--n-text-color);',
            onClick: (e: MouseEvent) => {
              e.stopPropagation()
              router.push({ name: 'TaskView', params: { id: row.id } })
            }
          },
          truncated
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
      width: 80,
      render: (row) => {
        if (!['failed', 'cancelled'].includes(row.status)) return ''
        return h(
          NButton,
          {
            size: 'small',
            secondary: true,
            type: 'warning',
            onClick: () => handleRetryTask(row.id)
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

function isScheduleDateDisabled(timestamp: number): boolean {
  const candidate = new Date(timestamp)
  const today = new Date()
  candidate.setHours(0, 0, 0, 0)
  today.setHours(0, 0, 0, 0)
  return candidate.getTime() < today.getTime()
}

// --- API Actions ---
async function fetchIssue() {
  loading.value = true
  try {
    issue.value = await getIssue(issueId.value)
  } catch {
    message.error('Failed to load issue')
  } finally {
    loading.value = false
  }
}

async function handleClose() {
  try {
    issue.value = await closeIssue(issueId.value)
    message.success('Issue closed')
  } catch {
    message.error('Failed to close issue')
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
    message.success('Issue updated')
  } catch {
    message.error('Failed to update issue')
  } finally {
    editLoading.value = false
  }
}

async function handleCreateTask() {
  createTaskLoading.value = true
  try {
    const request: Parameters<typeof createTask>[0] = {
      issue_id: issueId.value,
      priority: newTaskPriority.value
    }
    if (newTaskPrompt.value.trim()) {
      request.user_prompt = newTaskPrompt.value.trim()
    }
    if (newTaskSchedule.value) {
      request.scheduled_datetime = new Date(newTaskSchedule.value).toISOString()
    }
    await createTask(request)
    message.success('Task created')
    newTaskPrompt.value = ''
    newTaskSchedule.value = null
    await fetchIssue()
  } catch {
    message.error('Failed to create task')
  } finally {
    createTaskLoading.value = false
  }
}

async function handleRetryTask(taskId: number) {
  try {
    await retryTask(taskId)
    message.success('Task retried')
    await fetchIssue()
  } catch {
    message.error('Failed to retry task')
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

.issue-view__description {
  white-space: pre-wrap;
  line-height: 1.6;
  color: rgba(15, 23, 42, 0.82);
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
  max-width: 800px;
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
