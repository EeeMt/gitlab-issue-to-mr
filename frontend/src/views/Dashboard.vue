<template>
  <div class="dashboard">
    <n-space vertical :size="16">
      <div class="header-row">
        <h2>Task Dashboard</h2>
        <n-space align="center">
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

      <n-card>
        <n-data-table
          :columns="columns"
          :data="tasks"
          :loading="loading"
          :row-key="(row: Task) => row.id"
          :pagination="pagination"
          :bordered="false"
          :scroll-x="isMobile ? undefined : 900"
        />
      </n-card>
    </n-space>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onBeforeUnmount, h, watch, computed } from 'vue'
import { NButton, NSpace, NSelect, NCard, NDataTable, NTag, useMessage, DataTableColumns } from 'naive-ui'
import { useRouter } from 'vue-router'
import { useWindowSize } from '@vueuse/core'
import { getTasks, type Task } from '../api'

const router = useRouter()
const message = useMessage()
const { width } = useWindowSize()

const isMobile = computed(() => width.value < 768)

const tasks = ref<Task[]>([])
const loading = ref(false)
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
      h('div', { style: 'font-size: 12px; color: #888' }, `P${row.project_id} · !${row.issue_iid}`),
      h('div', { style: 'font-size: 12px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 120px' }, row.branch_name || '-')
    ])
  },
  {
    title: 'Status',
    key: 'status',
    width: 85,
    render: (row) => h(NTag, { type: statusColors[row.status], size: 'small' }, () => row.status)
  },
  {
    title: '',
    key: 'actions',
    width: 52,
    render: (row) => h(NButton, { size: 'tiny', onClick: () => router.push({ name: 'TaskView', params: { id: row.id } }) }, () => 'View')
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
    key: 'project_id',
    width: 80
  },
  {
    title: 'Issue',
    key: 'issue_iid',
    width: 70,
    render: (row) => `!${row.issue_iid}`
  },
  {
    title: 'Status',
    key: 'status',
    width: 100,
    render: (row) => h(NTag, { type: statusColors[row.status], size: 'small' }, () => row.status)
  },
  {
    title: 'Priority',
    key: 'priority',
    width: 80
  },
  {
    title: 'Branch',
    key: 'branch_name',
    width: 180,
    ellipsis: { tooltip: true }
  },
  {
    title: 'MR',
    key: 'merge_request_url',
    width: 200,
    ellipsis: { tooltip: true },
    render: (row) => row.merge_request_url ? h('a', { href: row.merge_request_url, target: '_blank' }, row.merge_request_url.split('/').pop()) : '-'
  },
  {
    title: 'Changes',
    key: 'changes',
    width: 120,
    render: (row) => {
      if (row.additions === undefined && row.deletions === undefined) return '-'
      if (!row.additions && !row.deletions) return '-'
      return h('span', { style: 'display: flex; align-items: center; gap: 4px;' }, [
        h('span', { style: 'color: #18a053' }, '+' + (row.additions || 0)),
        h('span', { style: 'color: #db3b21; margin-left: 8px' }, '-' + (row.deletions || 0))
      ])
    }
  },
  {
    title: 'Created',
    key: 'created_at',
    width: 160,
    render: (row) => new Date(row.created_at).toLocaleString()
  },
  {
    title: 'Actions',
    key: 'actions',
    width: 100,
    render: (row) => h(NButton, { size: 'small', onClick: () => router.push({ name: 'TaskView', params: { id: row.id } }) }, () => 'View')
  }
]

const columns = computed(() => isMobile.value ? mobileColumns : desktopColumns)

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
  max-width: 100%;
}
.header-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 12px;
}
.header-row h2 {
  margin: 0;
  font-size: 18px;
}
@media (max-width: 768px) {
  .header-row {
    flex-direction: column;
    align-items: flex-start;
  }
  .header-row h2 {
    font-size: 16px;
  }
}
</style>
