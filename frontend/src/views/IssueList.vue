<template>
  <div class="issue-list" data-testid="issue-list-page">
    <n-spin :show="initialLoading" :description="t('common.loadingTasks')">
      <n-space vertical :size="16">
        <PageHeader
          data-testid="issue-list-header"
          root-class="issue-list__hero"
          actions-class="issue-list__actions"
          :title="t('issue.list')"
          :subtitle="t('issue.subtitle')"
        >
          <template #actions>
            <n-select
              v-model:value="statusFilter"
              :options="statusOptions"
              :placeholder="t('common.status')"
              clearable
              class="issue-list__filter issue-list__filter--status"
              data-testid="issue-list-status-filter"
            />
            <n-select
              v-model:value="projectFilter"
              :options="projectOptions"
              :placeholder="t('issue.field.project')"
              clearable
              filterable
              class="issue-list__filter issue-list__filter--project"
            />
            <n-button
              type="primary"
              data-testid="issue-list-create-button"
              @click="router.push('/issues/create')"
            >
              {{ t('issue.create') }}
            </n-button>
          </template>
        </PageHeader>

        <n-card class="issue-list__table-card" :bordered="false" data-testid="issue-list-table-card">
          <n-data-table
            data-testid="issue-list-table"
            :columns="columns"
            :data="issues"
            :loading="tableLoading"
            :row-key="(row: Issue) => row.id"
            :pagination="pagination"
            remote
            :bordered="false"
          />
        </n-card>
      </n-space>
    </n-spin>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, h, watch, computed } from 'vue'
import { NButton, NSpace, NSelect, NCard, NDataTable, NTag, NSpin, useMessage, type DataTableColumns } from 'naive-ui'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { getIssues, getProjects, type Issue, type IssueStatus, type Project } from '../api'
import PageHeader from '../components/PageHeader.vue'
import { formatDateTimeUtc8Compact } from '../utils/datetime'

const router = useRouter()
const message = useMessage()
const { t } = useI18n()

const issues = ref<Issue[]>([])
const projects = ref<Project[]>([])
const loading = ref(false)
const hasLoadedOnce = ref(false)
const statusFilter = ref<string | null>(null)
const projectFilter = ref<number | null>(null)

const currentPage = ref(1)
const pageSize = ref(20)
const totalIssues = ref(0)

const pagination = computed(() => ({
  page: currentPage.value,
  pageSize: pageSize.value,
  itemCount: totalIssues.value,
  showSizePicker: true,
  pageSizes: [20, 50, 100],
  'onUpdate:page': (page: number) => {
    currentPage.value = page
    fetchIssues()
  },
  'onUpdate:pageSize': (size: number) => {
    pageSize.value = size
    currentPage.value = 1
    fetchIssues()
  },
}))

const statusOptions = computed(() => [
  { label: t('issue.status.open'), value: 'open' },
  { label: t('issue.status.in_progress'), value: 'in_progress' },
  { label: t('issue.status.completed'), value: 'completed' },
  { label: t('issue.status.closed'), value: 'closed' },
])

const projectOptions = computed(() =>
  projects.value.map((project) => ({
    label: project.path_with_namespace,
    value: project.id,
  }))
)

const statusColors: Record<IssueStatus, 'default' | 'info' | 'warning' | 'success'> = {
  open: 'info',
  in_progress: 'warning',
  completed: 'success',
  closed: 'default',
}

function getProjectName(projectId: number): string {
  const project = projects.value.find((p) => p.id === projectId)
  return project ? project.path_with_namespace : `Project #${projectId}`
}

function formatCompactDateTime(value?: string | null): string {
  if (!value) return '-'
  return formatDateTimeUtc8Compact(value)
}

const columns = computed<DataTableColumns<Issue>>(() => [
  {
    title: 'ID',
    key: 'id',
    width: 60,
  },
  {
    title: t('issue.field.title'),
    key: 'title',
    ellipsis: { tooltip: true },
    render: (row) =>
      h(
        NButton,
        {
          text: true,
          type: 'primary',
          onClick: () => router.push(`/issues/${row.id}`),
        },
        () => row.title
      ),
  },
  {
    title: t('issue.field.project'),
    key: 'project_id',
    width: 180,
    ellipsis: { tooltip: true },
    render: (row) => getProjectName(row.project_id),
  },
  {
    title: t('common.status'),
    key: 'status',
    width: 110,
    render: (row) =>
      h(
        NTag,
        { type: statusColors[row.status], size: 'small' },
        () => t(`issue.status.${row.status}`)
      ),
  },
  {
    title: t('issue.taskCount', { count: '' }).trim(),
    key: 'task_count',
    width: 100,
    render: (row) => t('issue.taskCount', { count: row.task_count ?? 0 }),
  },
  {
    title: t('issue.field.createdAt'),
    key: 'created_at',
    width: 140,
    render: (row) => formatCompactDateTime(row.created_at),
  },
])

const initialLoading = computed(() => loading.value && !hasLoadedOnce.value)
const tableLoading = computed(() => loading.value && hasLoadedOnce.value)

async function fetchIssues() {
  if (loading.value) return
  loading.value = true
  try {
    const params: {
      page: number
      page_size: number
      status?: string
      project_id?: number
    } = {
      page: currentPage.value,
      page_size: pageSize.value,
    }
    if (statusFilter.value) {
      params.status = statusFilter.value
    }
    if (projectFilter.value !== null) {
      params.project_id = projectFilter.value
    }
    const result = await getIssues(params)
    issues.value = result.items
    totalIssues.value = result.total
  } catch {
    message.error('Failed to fetch issues')
  } finally {
    hasLoadedOnce.value = true
    loading.value = false
  }
}

async function fetchProjects() {
  try {
    projects.value = await getProjects()
  } catch {
    // Keep the issue list usable even if the optional filter options fail to load.
  }
}

watch([statusFilter, projectFilter], () => {
  currentPage.value = 1
  fetchIssues()
})

onMounted(() => {
  fetchProjects()
  fetchIssues()
})
</script>

<style scoped>
.issue-list {
  max-width: var(--app-page-max-width);
}

.issue-list__actions {
  display: inline-flex;
  align-items: center;
  justify-content: flex-end;
  gap: 8px;
  flex-wrap: wrap;
}

.issue-list__filter--status {
  width: 140px;
}

.issue-list__filter--project {
  width: min(280px, 70vw);
}

.issue-list__table-card {
  border-radius: var(--app-card-radius);
}

@media (max-width: 768px) {
  .issue-list__actions {
    width: 100%;
    justify-content: flex-start;
  }

  .issue-list__actions :deep(.n-base-selection),
  .issue-list__actions :deep(.n-button) {
    width: 100%;
  }

  .issue-list__filter--project {
    width: min(280px, 100vw);
  }
}
</style>
