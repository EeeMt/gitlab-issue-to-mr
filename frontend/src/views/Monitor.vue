<template>
  <div class="monitor-page">
    <n-space vertical :size="16">
      <div class="monitor-page__hero">
        <div>
          <h2 class="monitor-page__title">System Monitor</h2>
          <p class="monitor-page__subtitle">
            Watch global task health and currently running worker containers.
          </p>
        </div>
        <n-button @click="refresh" :loading="loading">Refresh</n-button>
      </div>

      <n-grid :cols="isMobile ? 2 : 4" :x-gap="16" :y-gap="16">
        <n-gi v-for="item in summaryItems" :key="item.label">
          <n-card size="small" class="monitor-summary-card" :bordered="false">
            <div class="monitor-summary-card__label">{{ item.label }}</div>
            <div class="monitor-summary-card__value">{{ item.value }}</div>
          </n-card>
        </n-gi>
      </n-grid>

      <n-card class="monitor-table-card" :bordered="false">
        <template #header>
          <div class="monitor-card__header">
            <div>
              <div class="monitor-card__title">Running Containers</div>
              <div class="monitor-card__subtitle">Live worker containers currently visible to the backend</div>
            </div>
          </div>
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
import { NCard, NButton, NDataTable, NTag, NGrid, NGi, useMessage, DataTableColumns } from 'naive-ui'
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

const summaryItems = computed(() => [
  { label: 'Total Tasks', value: String(stats.value.total) },
  { label: 'Running', value: String(stats.value.running) },
  { label: 'Pending / Queued', value: String(stats.value.pending + stats.value.queued) },
  { label: 'Completed', value: String(stats.value.completed) },
  { label: 'Failed', value: String(stats.value.failed) },
  { label: 'Cancelled', value: String(stats.value.cancelled) }
])

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

<style scoped>
.monitor-page {
  max-width: 1240px;
}

.monitor-page__hero {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 16px;
  flex-wrap: wrap;
}

.monitor-page__title {
  margin: 0;
  font-size: 28px;
  line-height: 1.2;
}

.monitor-page__subtitle {
  margin: 8px 0 0;
  color: rgba(15, 23, 42, 0.68);
  max-width: 760px;
}

.monitor-summary-card {
  border-radius: 12px;
  background: linear-gradient(180deg, rgba(32, 128, 240, 0.06), rgba(32, 128, 240, 0.02));
}

.monitor-summary-card__label {
  margin-bottom: 8px;
  font-size: 12px;
  color: rgba(15, 23, 42, 0.6);
}

.monitor-summary-card__value {
  font-size: 20px;
  font-weight: 600;
  color: var(--n-text-color-1);
}

.monitor-table-card {
  border-radius: 18px;
}

.monitor-card__header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.monitor-card__title {
  font-size: 18px;
  font-weight: 600;
}

.monitor-card__subtitle {
  margin-top: 4px;
  font-size: 13px;
  color: rgba(15, 23, 42, 0.58);
}

@media (max-width: 768px) {
  .monitor-page__hero,
  .monitor-card__header {
    flex-direction: column;
    align-items: flex-start;
  }

  .monitor-page__title {
    font-size: 24px;
  }
}
</style>
