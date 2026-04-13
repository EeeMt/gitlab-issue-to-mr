<template>
  <div class="dashboard" data-testid="dashboard-page">
    <n-spin :show="initialLoading" :description="t('common.loadingTasks')">
      <n-space vertical :size="16">
        <div class="dashboard__top-bar" data-testid="dashboard-header">
          <n-button
            type="primary"
            data-testid="dashboard-new-issue-button"
            @click="router.push('/issues/create')"
          >
            {{ t('dashboard.createIssue') }}
          </n-button>
        </div>

        <n-grid
          v-if="hasLoadedOnce"
          data-testid="dashboard-summary"
          :cols="isMobile ? 2 : 5"
          :x-gap="12"
          :y-gap="12"
        >
          <n-gi>
            <StatCard
              :label="t('dashboard.issueCount')"
              :value="statsIssueTotal"
              :icon="FolderOpenOutline"
              color="#2080f0"
              data-testid="dashboard-summary-card"
            />
          </n-gi>
          <n-gi>
            <StatCard
              :label="t('dashboard.openIssues')"
              :value="statsOpenIssues"
              :icon="AlertCircleOutline"
              color="#f0a020"
              data-testid="dashboard-summary-card"
            />
          </n-gi>
          <n-gi>
            <StatCard
              :label="t('dashboard.tasks')"
              :value="statsTotal"
              :icon="CodeOutline"
              color="#2080f0"
              data-testid="dashboard-summary-card"
            />
          </n-gi>
          <n-gi>
            <StatCard
              :label="t('dashboard.running')"
              :value="statsRunning"
              :icon="PlayOutline"
              color="#18a058"
              data-testid="dashboard-summary-card"
            />
          </n-gi>
          <n-gi>
            <StatCard
              :label="t('dashboard.successRate')"
              :value="successRate"
              :icon="CheckmarkCircleOutline"
              suffix="%"
              color="#18a058"
              data-testid="dashboard-summary-card"
            />
          </n-gi>
        </n-grid>

        <n-card
          :title="t('dashboard.recentIssues')"
          :bordered="false"
          class="dashboard-table-card"
          data-testid="dashboard-recent-issues"
        >
          <n-data-table
            :columns="issueColumns"
            :data="recentIssues"
            :loading="loading"
            :row-key="(row: Issue) => row.id"
            :row-props="issueRowProps"
            :bordered="false"
          />
        </n-card>

        <n-card
          :title="t('dashboard.running')"
          :bordered="false"
          class="dashboard-table-card"
          data-testid="dashboard-running-tasks"
        >
          <n-data-table
            :columns="taskColumns"
            :data="runningAndQueuedTasks"
            :loading="loading"
            :row-key="(row: Task) => row.id"
            :row-props="taskRowProps"
            :bordered="false"
          />
        </n-card>

        <n-card
          :title="t('dashboard.activity')"
          :bordered="false"
          class="dashboard-table-card"
          data-testid="dashboard-activity-heatmap"
        >
          <ActivityHeatmap :data="heatmapData" />
        </n-card>

      </n-space>
    </n-spin>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, h, computed } from 'vue'
import { NButton, NSpace, NCard, NDataTable, NTag, NGrid, NGi, NSpin, useMessage, type DataTableColumns } from 'naive-ui'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { getIssues, getTasksPaginated, getStats, getActivityHeatmap, type Issue, type Task, type ActivityHeatmapEntry } from '../api'
import {
  FolderOpenOutline,
  AlertCircleOutline,
  CodeOutline,
  PlayOutline,
  CheckmarkCircleOutline
} from '@vicons/ionicons5'

import StatCard from '../components/StatCard.vue'
import ActivityHeatmap from '../components/ActivityHeatmap.vue'
import { useBreakpoints } from '../composables/useBreakpoints'
import { usePolling } from '../composables/usePolling'
import { formatDateTimeUtc8Compact } from '../utils/datetime'
import { formatPriority } from '../utils/format'

const router = useRouter()
const message = useMessage()
const { t } = useI18n()
const { isMobile } = useBreakpoints()

function issueRowProps(row: Issue) {
  return { style: 'cursor: pointer', onClick: () => router.push(`/issues/${row.id}`) }
}

function taskRowProps(row: Task) {
  return { style: 'cursor: pointer', onClick: () => router.push(`/tasks/${row.id}`) }
}

const recentIssues = ref<Issue[]>([])
const runningTasks = ref<Task[]>([])
const queuedTasks = ref<Task[]>([])
const loading = ref(false)
const hasLoadedOnce = ref(false)

const statsIssueTotal = ref(0)
const statsOpenIssues = ref(0)
const statsTotal = ref(0)
const statsRunning = ref(0)
const statsCompleted = ref(0)
const statsFailed = ref(0)
const heatmapData = ref<ActivityHeatmapEntry[]>([])

const runningAndQueuedTasks = computed(() => [...runningTasks.value, ...queuedTasks.value])

const initialLoading = computed(() => loading.value && !hasLoadedOnce.value)

const successRate = computed(() => {
  const total = statsCompleted.value + statsFailed.value
  if (total === 0) return 0
  return Math.round((statsCompleted.value / total) * 100)
})

const issueStatusColors: Record<string, 'default' | 'info' | 'warning' | 'success' | 'error'> = {
  open: 'info',
  in_progress: 'warning',
  completed: 'success',
  closed: 'default',
}

const issueColumns = computed<DataTableColumns<Issue>>(() => [
  {
    title: t('dashboard.id'),
    key: 'id',
    width: 60,
  },
  {
    title: t('issue.field.title'),
    key: 'title',
    ellipsis: { tooltip: true },
  },
  {
    title: t('dashboard.status'),
    key: 'status',
    width: 100,
    render: (row) =>
      h(
        NTag,
        { type: issueStatusColors[row.status] || 'default', size: 'small' },
        () => t(`issue.status.${row.status}`),
      ),
  },
  {
    title: t('common.createTask'),
    key: 'task_count',
    width: 80,
    render: (row) => String(row.task_count ?? 0),
  },
  {
    title: t('common.created'),
    key: 'created_at',
    width: 140,
    render: (row) => (row.created_at ? formatDateTimeUtc8Compact(row.created_at) : '-'),
  },
])

const taskColumns = computed<DataTableColumns<Task>>(() => [
  {
    title: t('dashboard.id'),
    key: 'id',
    width: 60,
  },
  {
    title: t('dashboard.task'),
    key: 'user_prompt',
    ellipsis: { tooltip: true },
  },
  {
    title: t('dashboard.priority'),
    key: 'priority',
    width: 80,
    render: (row) => formatPriority(row.priority),
  },
  {
    title: t('common.started'),
    key: 'started_at',
    width: 140,
    render: (row) => (row.started_at ? formatDateTimeUtc8Compact(row.started_at) : '-'),
  },
])

async function fetchData() {
  if (loading.value) return
  loading.value = true
  try {
    const [issuesRes, runningRes, queuedRes] = await Promise.all([
      getIssues({ page: 1, page_size: 5 }),
      getTasksPaginated({ status: 'running', page: 1, page_size: 10 }),
      getTasksPaginated({ status: 'queued', page: 1, page_size: 10 }),
    ])
    recentIssues.value = issuesRes.items
    runningTasks.value = runningRes.items
    queuedTasks.value = queuedRes.items
  } catch {
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
    statsFailed.value = stats.failed ?? 0
    statsIssueTotal.value = stats.issues?.total ?? 0
    const byStatus = stats.issues?.by_status ?? {}
    statsOpenIssues.value = (byStatus.open ?? 0) + (byStatus.in_progress ?? 0)
  } catch {
    // Stats are supplementary; don't block UI
  }
}

async function fetchHeatmap() {
  try {
    heatmapData.value = await getActivityHeatmap()
  } catch {
    // Heatmap is supplementary
  }
}

function refreshAll() {
  fetchData()
  fetchStats()
  fetchHeatmap()
}

const { start: startPolling } = usePolling(
  () => refreshAll(),
  { interval: 15_000, immediate: false },
)

onMounted(() => {
  fetchStats()
  fetchHeatmap()
  fetchData()
  startPolling()
})
</script>

<style scoped>
.dashboard {
  max-width: var(--app-page-max-width);
}

.dashboard-summary-card {
  min-height: 100%;
}

.dashboard__top-bar {
  display: flex;
  justify-content: flex-end;
  margin-bottom: 4px;
}

.dashboard-table-card {
  border-radius: var(--app-card-radius);
}
</style>
