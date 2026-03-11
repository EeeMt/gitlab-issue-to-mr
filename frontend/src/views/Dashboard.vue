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
          :scroll-x="800"
        />
      </n-card>
    </n-space>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, h, watch, computed } from 'vue'
import { NButton, NSpace, NSelect, NCard, NDataTable, NTag, useMessage, DataTableColumns } from 'naive-ui'
import { useRouter } from 'vue-router'
import { useWindowSize } from '@vueuse/core'
import { getTasks, getTaskStats, type Task, type TaskStats } from '../api'

const router = useRouter()
const message = useMessage()
const { width } = useWindowSize()

const isMobile = computed(() => width.value < 768)

const tasks = ref<Task[]>([])
const taskStats = ref<Record<number, TaskStats>>({})
const loading = ref(false)
const statusFilter = ref<string | null>(null)

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
    width: 50
  },
  {
    title: 'Issue',
    key: 'issue_iid',
    width: 60,
    render: (row) => `!${row.issue_iid}`
  },
  {
    title: 'Status',
    key: 'status',
    width: 80,
    render: (row) => h(NTag, { type: statusColors[row.status], size: 'small' }, () => row.status)
  },
  {
    title: 'Actions',
    key: 'actions',
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
    key: 'stats',
    width: 100,
    render: (row) => {
      const stats = taskStats.value[row.id]
      if (!stats || stats.total === 0) return '-'
      return h('span', { style: 'display: flex; align-items: center; gap: 4px;' }, [
        h('span', { style: 'color: #18a053' }, '+' + stats.additions),
        h('span', { style: 'color: #db3b21; margin-left: 8px' }, '-' + stats.deletions)
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
  loading.value = true
  try {
    const params: { status?: string } = {}
    if (statusFilter.value) {
      params.status = statusFilter.value
    }
    tasks.value = await getTasks(params)

    // Fetch stats for completed tasks
    const statsMap: Record<number, TaskStats> = {}
    for (const task of tasks.value) {
      if (task.merge_request_iid && task.status === 'completed') {
        try {
          statsMap[task.id] = await getTaskStats(task.id)
        } catch {
          statsMap[task.id] = { additions: 0, deletions: 0, total: 0 }
        }
      }
    }
    taskStats.value = statsMap
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
  // Auto-refresh every 10 seconds
  setInterval(fetchTasks, 10000)
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
