<template>
  <div>
    <n-space vertical :size="16">
      <h2>System Monitor</h2>

      <!-- Merge both stat rows; isMobile → 2-per-row, desktop → 4-per-row -->
      <n-row :gutter="[16, 16]">
        <n-col :span="isMobile ? 12 : 6">
          <n-card>
            <n-statistic label="Total Tasks" :value="stats.total" />
          </n-card>
        </n-col>
        <n-col :span="isMobile ? 12 : 6">
          <n-card>
            <n-statistic label="Running" :value="stats.running">
              <template #prefix>
                <span style="color: #f0a020">●</span>
              </template>
            </n-statistic>
          </n-card>
        </n-col>
        <n-col :span="isMobile ? 12 : 6">
          <n-card>
            <n-statistic label="Pending/Queued" :value="stats.pending + stats.queued" />
          </n-card>
        </n-col>
        <n-col :span="isMobile ? 12 : 6">
          <n-card>
            <n-statistic label="Completed" :value="stats.completed">
              <template #prefix>
                <span style="color: #18a058">●</span>
              </template>
            </n-statistic>
          </n-card>
        </n-col>
        <n-col :span="isMobile ? 12 : 6">
          <n-card>
            <n-statistic label="Failed" :value="stats.failed">
              <template #prefix>
                <span style="color: #d03050">●</span>
              </template>
            </n-statistic>
          </n-card>
        </n-col>
        <n-col :span="isMobile ? 12 : 6">
          <n-card>
            <n-statistic label="Cancelled" :value="stats.cancelled" />
          </n-card>
        </n-col>
      </n-row>

      <n-card title="Running Containers">
        <template #header-extra>
          <n-button @click="refresh" :loading="loading">Refresh</n-button>
        </template>
        <n-data-table
          :columns="isMobile ? mobileColumns : columns"
          :data="containers"
          :loading="loading"
          :bordered="false"
          :scroll-x="isMobile ? undefined : 660"
        />
      </n-card>
    </n-space>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onBeforeUnmount, h } from 'vue'
import { NCard, NStatistic, NRow, NCol, NButton, NDataTable, NTag, useMessage, DataTableColumns } from 'naive-ui'
import { useWindowSize } from '@vueuse/core'
import { getStats, getContainers, type Container, type Stats } from '../api'

const message = useMessage()
const { width } = useWindowSize()
const isMobile = computed(() => width.value < 768)

const stats = ref<Stats>({
  total: 0,
  pending: 0,
  queued: 0,
  running: 0,
  completed: 0,
  failed: 0,
  cancelled: 0
})

const containers = ref<Container[]>([])
const loading = ref(false)
let pollTimer: number | null = null

const columns: DataTableColumns<Container> = [
  {
    title: 'Container ID',
    key: 'id',
    width: 140,
    render: (row) => row.id.substring(0, 12)
  },
  {
    title: 'Name',
    key: 'name',
    width: 180
  },
  {
    title: 'Status',
    key: 'status',
    width: 100,
    render: (row) => h(NTag, { type: row.status === 'running' ? 'warning' : 'default', size: 'small' }, () => row.status)
  },
  {
    title: 'Task ID',
    key: 'task_id',
    width: 80
  },
  {
    title: 'Project',
    key: 'project_id',
    width: 80
  },
  {
    title: 'Issue',
    key: 'issue_iid',
    width: 80,
    render: (row) => row.issue_iid ? `!${row.issue_iid}` : '-'
  }
]

const mobileColumns: DataTableColumns<Container> = [
  {
    title: 'Name',
    key: 'name',
    ellipsis: { tooltip: true }
  },
  {
    title: 'Status',
    key: 'status',
    width: 85,
    render: (row) => h(NTag, { type: row.status === 'running' ? 'warning' : 'default', size: 'small' }, () => row.status)
  },
  {
    title: 'Task',
    key: 'task_id',
    width: 55
  }
]

async function fetchData() {
  if (loading.value) return
  loading.value = true
  try {
    const [statsData, containersData] = await Promise.all([
      getStats(),
      getContainers()
    ])
    stats.value = statsData
    containers.value = containersData
  } catch (error) {
    message.error('Failed to fetch monitor data')
  } finally {
    loading.value = false
  }
}

function refresh() {
  fetchData()
}

onMounted(() => {
  fetchData()
  pollTimer = window.setInterval(() => {
    if (document.visibilityState !== 'visible') return
    fetchData()
  }, 10000)
})

onBeforeUnmount(() => {
  if (pollTimer !== null) {
    clearInterval(pollTimer)
    pollTimer = null
  }
})
</script>
