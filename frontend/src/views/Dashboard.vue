<template>
  <div class="dashboard">
    <n-spin :show="initialLoading" description="Loading tasks...">
      <n-space vertical :size="16">
        <div class="dashboard__hero">
          <div>
            <h2 class="dashboard__title">Task Dashboard</h2>
            <p class="dashboard__subtitle">
              Track queued work, running jobs, and completed merge request tasks from a single view.
            </p>
          </div>
          <n-space align="center" wrap>
            <n-select
              v-model:value="statusFilter"
              :options="statusOptions"
              placeholder="Filter"
              clearable
              style="width: 140px"
            />
            <n-button @click="refreshTasks" :loading="loading" size="small">
              Refresh
            </n-button>
          </n-space>
        </div>

        <n-grid v-if="hasLoadedOnce" :cols="isMobile ? 2 : 4" :x-gap="16" :y-gap="16">
          <n-gi v-for="item in summaryItems" :key="item.label">
            <n-card size="small" class="dashboard-summary-card" :bordered="false">
              <div class="dashboard-summary-card__label">{{ item.label }}</div>
              <div class="dashboard-summary-card__value">{{ item.value }}</div>
            </n-card>
          </n-gi>
        </n-grid>

        <n-card class="dashboard-table-card" :bordered="false">
          <n-data-table
            :columns="columns"
            :data="tasks"
            :loading="loading"
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
import { useWindowSize } from '@vueuse/core'
import { getTasks, type Task } from '../api'
import { formatDateTimeUtc8 } from '../utils/datetime'

const router = useRouter()
const message = useMessage()
const { width } = useWindowSize()

const isMobile = computed(() => width.value < 768)

const tasks = ref<Task[]>([])
const loading = ref(false)
const hasLoadedOnce = ref(false)
const statusFilter = ref<string | null>(null)
let pollTimer: number | null = null

const pagination = {
  pageSize: 20,
  responsive: true
}

const statusOptions = [
  { label: 'Pending', value: 'pending' },
  { label: 'Queued', value: 'queued' },
  { label: 'Running', value: 'running' },
  { label: 'Completed', value: 'completed' },
  { label: 'Failed', value: 'failed' },
  { label: 'Cancelled', value: 'cancelled' }
]

const statusColors: Record<string, 'default' | 'info' | 'warning' | 'success' | 'error'> = {
  pending: 'default',
  queued: 'info',
  running: 'warning',
  completed: 'success',
  failed: 'error',
  cancelled: 'default'
}

function getProjectLabel(task: Task): string {
  return task.project_path_with_namespace || task.project_name || `Project #${task.project_id}`
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

  return formatDateTimeUtc8(value).slice(0, 16)
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

const mobileColumns: DataTableColumns<Task> = [
  {
    title: 'ID',
    key: 'id',
    width: 45
  },
  {
    title: 'Task',
    key: 'task_info',
    render: (row) => h('div', { style: 'line-height: 1.4' }, [
      h('div', { style: 'font-size: 12px; color: #888; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 140px' }, getProjectSecondaryLabel(row)),
      h('div', { style: 'font-size: 12px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 120px' }, row.branch_name ? renderExternalLink(row.branch_name, row.branch_url) : '-')
    ])
  },
  {
    title: 'Status',
    key: 'status',
    width: 85,
    render: (row) => h(NTag, { type: statusColors[row.status], size: 'small' }, () => row.status)
  }
]

const desktopColumns: DataTableColumns<Task> = [
  {
    title: 'ID',
    key: 'id',
    width: 60
  },
  {
    title: 'Project',
    key: 'project',
    width: 180,
    ellipsis: { tooltip: true },
    render: (row) => h('div', { style: 'line-height: 1.4' }, [
      h('div', renderExternalLink(getProjectLabel(row), row.project_url)),
      h('div', { style: 'font-size: 12px; color: #888; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;' }, `#${row.project_id}`)
    ])
  },
  {
    title: 'Issue',
    key: 'issue_iid',
    width: 60,
    render: (row) => row.issue_iid ? renderExternalLink(`!${row.issue_iid}`, row.issue_url) : '-'
  },
  {
    title: 'Status',
    key: 'status',
    width: 90,
    render: (row) => h(NTag, { type: statusColors[row.status], size: 'small' }, () => row.status)
  },
  {
    title: 'Priority',
    key: 'priority',
    width: 68,
    render: (row) => formatPriority(row.priority)
  },
  {
    title: 'Branch',
    key: 'branch_name',
    width: 140,
    ellipsis: { tooltip: true },
    render: (row) => row.branch_name ? renderExternalLink(row.branch_name, row.branch_url) : '-'
  },
  {
    title: 'MR',
    key: 'merge_request_url',
    width: 76,
    render: (row) => {
      if (!row.merge_request_url) return '-'
      const label = row.merge_request_iid ? `!${row.merge_request_iid}` : 'Open'
      return h('a', { href: row.merge_request_url, target: '_blank', rel: 'noopener noreferrer', class: 'app-link' }, label)
    }
  },
  {
    title: 'Changes',
    key: 'changes',
    width: 92,
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
    title: 'Created',
    key: 'created_at',
    width: 132,
    render: (row) => formatCompactDateTime(row.created_at)
  },
  {
    title: 'Scheduled',
    key: 'scheduled_at',
    width: 132,
    render: (row) => formatCompactDateTime(row.scheduled_at)
  }
]

const columns = computed(() => isMobile.value ? mobileColumns : desktopColumns)
const initialLoading = computed(() => loading.value && !hasLoadedOnce.value)

const summaryItems = computed(() => {
  const summary = tasks.value.reduce(
    (acc, task) => {
      acc.total += 1
      if (task.status === 'running') acc.running += 1
      if (task.status === 'completed') acc.completed += 1
      if (task.status === 'pending' || task.status === 'queued') acc.pending += 1
      if (task.status === 'failed') acc.failed += 1
      return acc
    },
    { total: 0, running: 0, completed: 0, pending: 0, failed: 0 }
  )

  return [
    { label: 'Visible Tasks', value: String(summary.total) },
    { label: 'Running', value: String(summary.running) },
    { label: 'Pending / Queued', value: String(summary.pending) },
    { label: 'Completed', value: String(summary.completed) }
  ]
})

async function fetchTasks() {
  if (loading.value) return
  loading.value = true
  try {
    const params: { status?: string } = {}
    if (statusFilter.value) {
      params.status = statusFilter.value
    }
    tasks.value = await getTasks(params)
  } catch (error) {
    message.error('Failed to fetch tasks')
  } finally {
    hasLoadedOnce.value = true
    loading.value = false
  }
}

function refreshTasks() {
  fetchTasks()
}

watch(statusFilter, () => {
  fetchTasks()
})

onMounted(() => {
  fetchTasks()
  // Auto-refresh every 15 seconds and skip when tab is not visible
  pollTimer = window.setInterval(() => {
    if (document.visibilityState !== 'visible') return
    fetchTasks()
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
  max-width: 1240px;
}

.dashboard__hero {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  flex-wrap: wrap;
  gap: 16px;
}

.dashboard__title {
  margin: 0;
  font-size: 28px;
  line-height: 1.2;
}

.dashboard__subtitle {
  margin: 8px 0 0;
  color: rgba(15, 23, 42, 0.68);
  max-width: 760px;
}

.dashboard-summary-card {
  border-radius: 12px;
  background: linear-gradient(180deg, rgba(32, 128, 240, 0.06), rgba(32, 128, 240, 0.02));
}

.dashboard-summary-card__label {
  margin-bottom: 8px;
  font-size: 12px;
  color: rgba(15, 23, 42, 0.6);
}

.dashboard-summary-card__value {
  font-size: 20px;
  font-weight: 600;
  color: var(--n-text-color-1);
}

.dashboard-table-card {
  border-radius: 18px;
}

@media (max-width: 768px) {
  .dashboard__hero {
    flex-direction: column;
    align-items: flex-start;
  }

  .dashboard__title {
    font-size: 24px;
  }
}
</style>
