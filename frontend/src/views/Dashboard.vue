<template>
  <div class="dashboard" data-testid="dashboard-page">
    <n-spin :show="initialLoading" :description="t('common.loadingTasks')">
      <n-space vertical :size="16">
        <PageHeader
          data-testid="dashboard-header"
          root-class="dashboard__hero"
          title-class="dashboard__title"
          subtitle-class="dashboard__subtitle"
          actions-class="dashboard__filters"
          :title="t('dashboard.title')"
          :subtitle="t('dashboard.subtitle')"
        >
          <template #actions>
            <n-select
              v-model:value="statusFilter"
              :options="statusOptions"
              :placeholder="t('dashboard.status')"
              clearable
              class="dashboard__filter dashboard__filter--status"
            />
            <n-select
              v-model:value="projectFilter"
              :options="projectOptions"
              :placeholder="t('dashboard.project')"
              clearable
              filterable
              class="dashboard__filter dashboard__filter--project"
            />
            <n-select
              v-model:value="initiatorFilter"
              :options="initiatorOptions"
              :placeholder="t('dashboard.initiator')"
              clearable
              filterable
              class="dashboard__filter dashboard__filter--initiator"
            />
            <n-button @click="refreshTasks" :loading="loading" size="small" class="dashboard__refresh">
              {{ t('common.refresh') }}
            </n-button>
          </template>
        </PageHeader>

        <n-grid
          v-if="hasLoadedOnce"
          data-testid="dashboard-summary"
          :cols="isMobile ? 2 : 4"
          :x-gap="16"
          :y-gap="16"
        >
          <n-gi v-for="item in summaryItems" :key="item.label">
            <SummaryCard
              :label="item.label"
              :value="item.value"
              data-testid="dashboard-summary-card"
              card-class="dashboard-summary-card"
              label-class="dashboard-summary-card__label"
              value-class="dashboard-summary-card__value"
            />
          </n-gi>
        </n-grid>

        <n-card class="dashboard-table-card" :bordered="false" data-testid="dashboard-table-card">
          <n-data-table
            data-testid="dashboard-table"
            :columns="columns"
            :data="tasks"
            :loading="tableLoading"
            :row-key="(row: Task) => row.id"
            :row-props="getRowProps"
            :pagination="pagination"
            :bordered="false"
            :scroll-x="isMobile ? undefined : undefined"
          />
        </n-card>
      </n-space>
    </n-spin>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onBeforeUnmount, h, watch, computed } from 'vue'
import { NButton, NSpace, NSelect, NCard, NDataTable, NTag, NGrid, NGi, NSpin, useMessage, DataTableColumns } from 'naive-ui'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { getProjects, getTasksPaginated, getStats, type Project, type Task } from '../api'
import PageHeader from '../components/PageHeader.vue'
import SummaryCard from '../components/SummaryCard.vue'
import { useBreakpoints } from '../composables/useBreakpoints'
import { formatDateTimeUtc8Compact } from '../utils/datetime'

const router = useRouter()
const message = useMessage()
const { t } = useI18n()
const { isMobile } = useBreakpoints()

const tasks = ref<Task[]>([])
const projects = ref<Project[]>([])
const loading = ref(false)
const hasLoadedOnce = ref(false)
const statusFilter = ref<string | null>(null)
const projectFilter = ref<number | null>(null)
const initiatorFilter = ref<string | null>(null)
let pollTimer: number | null = null

const currentPage = ref(1)
const pageSize = ref(20)
const totalTasks = ref(0)

const statsTotal = ref(0)
const statsRunning = ref(0)
const statsCompleted = ref(0)
const statsPending = ref(0)

const pagination = computed(() => ({
  page: currentPage.value,
  pageSize: pageSize.value,
  itemCount: totalTasks.value,
  showSizePicker: true,
  pageSizes: [20, 50, 100],
  onChange: (page: number) => {
    currentPage.value = page
    fetchTasks()
  },
  onUpdatePageSize: (size: number) => {
    pageSize.value = size
    currentPage.value = 1
    fetchTasks()
  },
}))

const statusOptions = computed(() => [
  { label: t('status.pending'), value: 'pending' },
  { label: t('status.queued'), value: 'queued' },
  { label: t('status.running'), value: 'running' },
  { label: t('status.completed'), value: 'completed' },
  { label: t('status.failed'), value: 'failed' },
  { label: t('status.cancelled'), value: 'cancelled' }
])
const projectOptions = computed(() =>
  projects.value.map((project) => ({
    label: project.path_with_namespace,
    value: project.id
  }))
)
const initiatorOptions = computed(() => {
  const values = Array.from(
    new Set(tasks.value.map((task) => task.initiator_username?.trim()).filter(Boolean) as string[])
  ).sort((left, right) => left.localeCompare(right))

  return values.map((username) => ({
    label: username,
    value: username
  }))
})

const statusColors: Record<string, 'default' | 'info' | 'warning' | 'success' | 'error'> = {
  pending: 'default',
  queued: 'info',
  running: 'warning',
  completed: 'success',
  failed: 'error',
  cancelled: 'default'
}

function getProjectLabel(task: Task): string {
  return task.project_path_with_namespace || task.project_name || t('dashboard.projectFallback', { id: task.project_id })
}

function renderExternalLink(label: string, href?: string | null) {
  if (!href) {
    return label
  }
  return h('a', { href, target: '_blank', rel: 'noopener noreferrer', class: 'app-link' }, label)
}

function getProjectSecondaryLabel(task: Task): string {
  const issueLabel = task.issue_iid ? `!${task.issue_iid}` : '-'
  return `${getProjectLabel(task)} · ${issueLabel}`
}

function getInitiatorLabel(task: Task): string {
  return task.initiator_username?.trim() || '-'
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

function formatCompactDateTime(value?: string | null): string {
  if (!value) {
    return '-'
  }

  return formatDateTimeUtc8Compact(value)
}

function goToTask(task: Task) {
  router.push({ name: 'TaskView', params: { id: task.id } })
}

function isInteractiveTarget(target: EventTarget | null): boolean {
  if (!(target instanceof Element)) {
    return false
  }

  return Boolean(
    target.closest('a, button, input, textarea, select, summary, [role="button"], .n-button, .n-base-selection')
  )
}

function getRowProps(row: Task) {
  return {
    style: 'cursor: pointer;',
    onClick: (event: MouseEvent) => {
      if (isInteractiveTarget(event.target)) {
        return
      }
      goToTask(row)
    }
  }
}

const columns = computed<DataTableColumns<Task>>(() => {
  const renderStatus = (row: Task) =>
    h(NTag, { type: statusColors[row.status], size: 'small' }, () => t(`status.${row.status}`))

  const mobileColumns: DataTableColumns<Task> = [
    {
      title: t('dashboard.id'),
      key: 'id',
      width: 45
    },
    {
      title: t('dashboard.task'),
      key: 'task_info',
      render: (row) =>
        h('div', { style: 'line-height: 1.4' }, [
          h(
            'div',
            {
              style:
                'font-size: 12px; color: #888; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 140px'
            },
            getProjectSecondaryLabel(row)
          ),
          h(
            'div',
            {
              style:
                'font-size: 12px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 120px'
            },
            row.branch_name ? renderExternalLink(row.branch_name, row.branch_url) : '-'
          )
        ])
    },
    {
      title: t('dashboard.status'),
      key: 'status',
      width: 85,
      render: renderStatus
    }
  ]

  const desktopColumns: DataTableColumns<Task> = [
    {
      title: t('dashboard.id'),
      key: 'id',
      width: 52
    },
    {
      title: t('dashboard.project'),
      key: 'project',
      width: 156,
      ellipsis: { tooltip: true },
      render: (row) =>
        h('div', { style: 'line-height: 1.4' }, [
          h('div', renderExternalLink(getProjectLabel(row), row.project_url)),
          h(
            'div',
            { style: 'font-size: 12px; color: #888; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;' },
            `ID: ${row.project_id}`
          )
        ])
    },
    {
      title: t('dashboard.initiator'),
      key: 'initiator_username',
      width: 112,
      ellipsis: { tooltip: true },
      render: (row) => getInitiatorLabel(row)
    },
    {
      title: t('dashboard.issue'),
      key: 'issue_iid',
      width: 68,
      render: (row) => (row.issue_iid ? renderExternalLink(`!${row.issue_iid}`, row.issue_url) : '-')
    },
    {
      title: t('dashboard.status'),
      key: 'status',
      width: 84,
      render: renderStatus
    },
    {
      title: t('dashboard.priority'),
      key: 'priority',
      width: 84,
      render: (row) => formatPriority(row.priority)
    },
    {
      title: t('dashboard.branch'),
      key: 'branch_name',
      width: 120,
      ellipsis: { tooltip: true },
      render: (row) => (row.branch_name ? renderExternalLink(row.branch_name, row.branch_url) : '-')
    },
    {
      title: t('dashboard.mergeRequest'),
      key: 'merge_request_url',
      width: 72,
      render: (row) => {
        if (!row.merge_request_url) return '-'
        const label = row.merge_request_iid ? `!${row.merge_request_iid}` : t('dashboard.open')
        return h(
          'a',
          { href: row.merge_request_url, target: '_blank', rel: 'noopener noreferrer', class: 'app-link' },
          label
        )
      }
    },
    {
      title: t('dashboard.changes'),
      key: 'changes',
      width: 84,
      render: (row) => {
        if (row.additions === undefined && row.deletions === undefined) return '-'
        if (!row.additions && !row.deletions) return '-'
        return h('span', { style: 'display: flex; align-items: center; gap: 4px; font-size: 12px;' }, [
          h('span', { style: 'color: #18a053' }, '+' + (row.additions || 0)),
          h('span', { style: 'color: #db3b21; margin-left: 4px' }, '-' + (row.deletions || 0))
        ])
      }
    },
    {
      title: t('common.created'),
      key: 'created_at',
      width: 118,
      render: (row) => formatCompactDateTime(row.created_at)
    },
    {
      title: t('dashboard.scheduled'),
      key: 'scheduled_at',
      width: 118,
      render: (row) => formatCompactDateTime(row.scheduled_at)
    }
  ]

  return isMobile.value ? mobileColumns : desktopColumns
})
const initialLoading = computed(() => loading.value && !hasLoadedOnce.value)
const tableLoading = computed(() => loading.value && hasLoadedOnce.value)

const summaryItems = computed(() => [
  { label: t('dashboard.visibleTasks'), value: String(statsTotal.value) },
  { label: t('dashboard.running'), value: String(statsRunning.value) },
  { label: t('dashboard.pendingQueued'), value: String(statsPending.value) },
  { label: t('dashboard.completed'), value: String(statsCompleted.value) },
])

async function fetchTasks() {
  if (loading.value) return
  loading.value = true
  try {
    const params: {
      page: number
      page_size: number
      status?: string
      project_id?: number
      initiator_username?: string
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
    if (initiatorFilter.value) {
      params.initiator_username = initiatorFilter.value
    }
    const result = await getTasksPaginated(params)
    tasks.value = result.items
    totalTasks.value = result.total
  } catch (error) {
    message.error(t('dashboard.failedToFetchTasks'))
  } finally {
    hasLoadedOnce.value = true
    loading.value = false
  }
}

async function fetchStats() {
  try {
    const stats = await getStats()
    statsTotal.value = stats.total
    statsRunning.value = stats.running
    statsCompleted.value = stats.completed
    statsPending.value = stats.pending + stats.queued
  } catch {
    // Stats are supplementary; don't block UI
  }
}

async function fetchProjects() {
  try {
    projects.value = await getProjects()
  } catch (error) {
    // Keep the task list usable even if the optional filter options fail to load.
  }
}

function refreshTasks() {
  fetchTasks()
  fetchStats()
}

watch([statusFilter, projectFilter, initiatorFilter], () => {
  currentPage.value = 1
  fetchTasks()
})

onMounted(() => {
  fetchProjects()
  fetchStats()
  fetchTasks()
  // Auto-refresh every 15 seconds and skip when tab is not visible
  pollTimer = window.setInterval(() => {
    if (document.visibilityState !== 'visible') return
    fetchTasks()
    fetchStats()
  }, 15000)
})

onBeforeUnmount(() => {
  if (pollTimer !== null) {
    clearInterval(pollTimer)
    pollTimer = null
  }
})
</script>

<style scoped>
.dashboard {
  max-width: var(--app-page-max-width);
}

.dashboard__filters {
  display: inline-flex;
  align-items: center;
  justify-content: flex-end;
  gap: 8px;
  flex-wrap: wrap;
}

.dashboard__filter--status {
  width: 140px;
}

.dashboard__filter--project {
  width: min(280px, 70vw);
}

.dashboard__filter--initiator {
  width: 180px;
}

.dashboard-summary-card {
  min-height: 100%;
}

.dashboard-table-card {
  border-radius: var(--app-card-radius);
}

@media (max-width: 768px) {
  .dashboard__filters {
    width: 100%;
    justify-content: flex-start;
  }

  .dashboard__filters :deep(.n-space-item) {
    width: 100%;
  }

  .dashboard__filters :deep(.n-base-selection),
  .dashboard__filters :deep(.n-button) {
    width: 100%;
  }
}
</style>
