<template>
  <div>
    <n-space vertical :size="16">
      <n-space align="center" justify="space-between">
        <h2>Task Dashboard</h2>
        <n-space>
          <n-select
            v-model:value="statusFilter"
            :options="statusOptions"
            placeholder="Filter by status"
            clearable
            style="width: 180px"
          />
          <n-button @click="refreshTasks" :loading="loading">
            Refresh
          </n-button>
        </n-space>
      </n-space>

      <n-card>
        <n-data-table
          :columns="columns"
          :data="tasks"
          :loading="loading"
          :row-key="(row: Task) => row.id"
          :pagination="pagination"
          :bordered="false"
        />
      </n-card>
    </n-space>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, h, watch } from 'vue'
import { NButton, NSpace, NSelect, NCard, NDataTable, NTag, useMessage, DataTableColumns } from 'naive-ui'
import { useRouter } from 'vue-router'
import { getTasks, type Task } from '../api'

const router = useRouter()
const message = useMessage()

const tasks = ref<Task[]>([])
const loading = ref(false)
const statusFilter = ref<string | null>(null)

const pagination = {
  pageSize: 20
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

const columns: DataTableColumns<Task> = [
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

async function fetchTasks() {
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
  // Auto-refresh every 10 seconds
  setInterval(fetchTasks, 10000)
})
</script>
