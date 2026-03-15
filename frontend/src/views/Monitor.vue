<template>
  <div class="monitor-page">
    <n-spin :show="initialLoading" :description="t('monitor.loading')">
      <n-space vertical :size="20">
        <div class="monitor-page__hero">
          <div>
            <h2 class="monitor-page__title">{{ t('monitor.title') }}</h2>
            <p class="monitor-page__subtitle">
              {{ t('monitor.subtitle') }}
            </p>
          </div>
          <n-button @click="refresh" :loading="loading">{{ t('common.refresh') }}</n-button>
        </div>

        <n-grid v-if="hasLoadedOnce" :cols="isMobile ? 2 : 4" :x-gap="16" :y-gap="16">
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
                  <div class="monitor-card__title">{{ t('monitor.runningContainers') }}</div>
                  <div class="monitor-card__subtitle">{{ t('monitor.runningContainersSubtitle') }}</div>
                </div>
              </div>
            </template>
          <n-data-table
            :columns="isMobile ? mobileColumns : columns"
            :data="containers"
            :loading="tableLoading"
            :bordered="false"
            :scroll-x="isMobile ? undefined : 660"
          />
        </n-card>
      </n-space>
    </n-spin>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onBeforeUnmount, h } from 'vue'
import { NCard, NButton, NDataTable, NTag, NGrid, NGi, NSpin, useMessage, DataTableColumns } from 'naive-ui'
import { useWindowSize } from '@vueuse/core'
import { useI18n } from 'vue-i18n'
import { getStats, getContainers, type Container, type Stats } from '../api'

const message = useMessage()
const { t } = useI18n()
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
const hasLoadedOnce = ref(false)
let pollTimer: number | null = null

const summaryItems = computed(() => [
  { label: t('monitor.totalTasks'), value: String(stats.value.total) },
  { label: t('monitor.running'), value: String(stats.value.running) },
  { label: t('monitor.pendingQueued'), value: String(stats.value.pending + stats.value.queued) },
  { label: t('monitor.completed'), value: String(stats.value.completed) },
  { label: t('monitor.failed'), value: String(stats.value.failed) },
  { label: t('monitor.cancelled'), value: String(stats.value.cancelled) }
])
const initialLoading = computed(() => loading.value && !hasLoadedOnce.value)
const tableLoading = computed(() => loading.value && hasLoadedOnce.value)

function containerStatusLabel(status: string) {
  return status === 'running' ? t('status.running') : status
}

const columns = computed<DataTableColumns<Container>>(() => [
  {
    title: t('monitor.containerId'),
    key: 'id',
    width: 140,
    render: (row) => row.id.substring(0, 12)
  },
  {
    title: t('monitor.name'),
    key: 'name',
    width: 180
  },
  {
    title: t('monitor.status'),
    key: 'status',
    width: 100,
    render: (row) =>
      h(NTag, { type: row.status === 'running' ? 'warning' : 'default', size: 'small' }, () => containerStatusLabel(row.status))
  },
  {
    title: t('monitor.taskId'),
    key: 'task_id',
    width: 80
  },
  {
    title: t('common.project'),
    key: 'project_id',
    width: 80
  },
  {
    title: t('common.issue'),
    key: 'issue_iid',
    width: 80,
    render: (row) => (row.issue_iid ? `!${row.issue_iid}` : '-')
  }
])

const mobileColumns = computed<DataTableColumns<Container>>(() => [
  {
    title: t('monitor.name'),
    key: 'name',
    ellipsis: { tooltip: true }
  },
  {
    title: t('monitor.status'),
    key: 'status',
    width: 85,
    render: (row) =>
      h(NTag, { type: row.status === 'running' ? 'warning' : 'default', size: 'small' }, () => containerStatusLabel(row.status))
  },
  {
    title: t('monitor.task'),
    key: 'task_id',
    width: 55
  }
])

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
    message.error(t('monitor.failedToFetchData'))
  } finally {
    hasLoadedOnce.value = true
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

.monitor-table-card :deep(.n-card__content) {
  padding-top: 8px;
  padding-bottom: 8px;
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
