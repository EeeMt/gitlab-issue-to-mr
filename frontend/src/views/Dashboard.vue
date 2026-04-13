<template>
  <div class="dashboard" data-testid="dashboard-page">
    <n-spin :show="initialLoading" :description="t('common.loadingTasks')">
      <n-space vertical :size="16">
        <n-grid
          v-if="hasLoadedOnce"
          data-testid="dashboard-summary"
          :cols="isMobile ? 2 : 4"
          :x-gap="12"
          :y-gap="12"
        >
          <n-gi>
            <n-card size="small" class="dashboard-metric-card" data-testid="dashboard-summary-card">
              <div class="metric-title">
                <span>{{ t('dashboard.issueStatus') }}</span>
                <n-tooltip trigger="hover"><template #trigger><n-icon size="14" class="metric-info-icon" :component="InformationCircleOutline" /></template>{{ t('dashboard.last90days') }}</n-tooltip>
              </div>
              <div class="metric-body">
                <StatusPieChart :data="issueChartData" />
              </div>
            </n-card>
          </n-gi>
          <n-gi>
            <n-card size="small" class="dashboard-metric-card" data-testid="dashboard-summary-card">
              <div class="metric-title">
                <span>{{ t('dashboard.taskStatus') }}</span>
                <n-tooltip trigger="hover"><template #trigger><n-icon size="14" class="metric-info-icon" :component="InformationCircleOutline" /></template>{{ t('dashboard.last90days') }}</n-tooltip>
              </div>
              <div class="metric-body">
                <StatusPieChart :data="taskChartData" />
              </div>
            </n-card>
          </n-gi>
          <n-gi>
            <n-card size="small" class="dashboard-metric-card" data-testid="dashboard-summary-card">
              <div class="metric-title">
                <span>{{ t('dashboard.linesChanged') }}</span>
                <n-tooltip trigger="hover"><template #trigger><n-icon size="14" class="metric-info-icon" :component="InformationCircleOutline" /></template>{{ t('dashboard.last90days') }}</n-tooltip>
              </div>
              <div class="metric-body">
                <div class="dashboard-stat__value">{{ formatNumber(analyticsTotalChanges) }}</div>
                <div class="dashboard-stat__detail">
                  <span class="dashboard-stat__add">+{{ formatNumber(analyticsTotalAdditions) }}</span>
                  <span class="dashboard-stat__del">-{{ formatNumber(analyticsTotalDeletions) }}</span>
                </div>
              </div>
            </n-card>
          </n-gi>
          <n-gi>
            <n-card size="small" class="dashboard-metric-card" data-testid="dashboard-summary-card">
              <div class="metric-title">
                <span>{{ t('dashboard.tokensUsed') }}</span>
                <n-tooltip trigger="hover"><template #trigger><n-icon size="14" class="metric-info-icon" :component="InformationCircleOutline" /></template>{{ t('dashboard.last90days') }}</n-tooltip>
              </div>
              <div class="metric-body">
                <div class="dashboard-stat__value">{{ formatNumber(analyticsTotalTokens) }}</div>
                <div class="dashboard-stat__detail">
                  <n-icon size="12" :component="FlashOutline" style="margin-right:2px" />
                  <span>{{ formatNumber(analyticsInputTokens) }} in / {{ formatNumber(analyticsOutputTokens) }} out</span>
                </div>
              </div>
            </n-card>
          </n-gi>
        </n-grid>

        <n-card
          :title="t('dashboard.recentIssues')"
          :bordered="false"
          class="dashboard-table-card"
          data-testid="dashboard-recent-issues"
        >
          <template #header-extra>
            <n-button
              type="primary"
              size="small"
              data-testid="dashboard-new-issue-button"
              @click="router.push('/issues/create')"
            >
              {{ t('dashboard.createIssue') }}
            </n-button>
          </template>
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
import { NButton, NSpace, NCard, NDataTable, NTag, NGrid, NGi, NSpin, NIcon, NTooltip, useMessage, type DataTableColumns } from 'naive-ui'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { getIssues, getTasksPaginated, getStats, getAnalytics, getActivityHeatmap, type Issue, type Task, type ActivityHeatmapEntry } from '../api'
import {
  FlashOutline,
  InformationCircleOutline,
} from '@vicons/ionicons5'

import StatusPieChart from '../components/StatusPieChart.vue'
import ActivityHeatmap from '../components/ActivityHeatmap.vue'
import { useBreakpoints } from '../composables/useBreakpoints'
import { usePolling } from '../composables/usePolling'
import { formatDateTimeUtc8Compact } from '../utils/datetime'
import { formatPriority } from '../utils/format'
import { authState } from '../auth'

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

const statsIssueByStatus = ref<Record<string, number>>({})
const statsPending = ref(0)
const statsQueued = ref(0)
const statsRunning = ref(0)
const statsCompleted = ref(0)
const statsFailed = ref(0)
const statsCancelled = ref(0)
const analyticsTotalAdditions = ref(0)
const analyticsTotalDeletions = ref(0)
const analyticsTotalChanges = ref(0)
const analyticsInputTokens = ref(0)
const analyticsOutputTokens = ref(0)
const analyticsTotalTokens = ref(0)
const heatmapData = ref<ActivityHeatmapEntry[]>([])

const runningAndQueuedTasks = computed(() => [...runningTasks.value, ...queuedTasks.value])

const initialLoading = computed(() => loading.value && !hasLoadedOnce.value)

function formatNumber(n: number): string {
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + 'M'
  if (n >= 1_000) return (n / 1_000).toFixed(1) + 'K'
  return String(n)
}

const issueChartData = computed(() => {
  const s = statsIssueByStatus.value
  return [
    { name: t('issue.status.open'), value: s.open ?? 0, color: '#2080f0' },
    { name: t('issue.status.in_progress'), value: s.in_progress ?? 0, color: '#f0a020' },
    { name: t('issue.status.completed'), value: s.completed ?? 0, color: '#18a058' },
    { name: t('issue.status.closed'), value: s.closed ?? 0, color: '#909399' },
  ].filter((d) => d.value > 0)
})

const taskChartData = computed(() => {
  return [
    { name: t('status.pending'), value: statsPending.value, color: '#909399' },
    { name: t('status.queued'), value: statsQueued.value, color: '#2080f0' },
    { name: t('status.running'), value: statsRunning.value, color: '#f0a020' },
    { name: t('status.completed'), value: statsCompleted.value, color: '#18a058' },
    { name: t('status.failed'), value: statsFailed.value, color: '#d03050' },
    { name: t('status.cancelled'), value: statsCancelled.value, color: '#909399' },
  ].filter((d) => d.value > 0)
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
    width: 200,
    ellipsis: { tooltip: true },
  },
  {
    title: t('dashboard.status'),
    key: 'status',
    width: 90,
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
    width: 200,
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
    const userId = authState.user?.id
    const username = authState.user?.username
    const [issuesRes, runningRes, queuedRes] = await Promise.all([
      getIssues({ page: 1, page_size: 5, ...(userId ? { initiator_user_id: userId } : {}) }),
      getTasksPaginated({ status: 'running', page: 1, page_size: 10, ...(username ? { initiator_username: username } : {}) }),
      getTasksPaginated({ status: 'queued', page: 1, page_size: 10, ...(username ? { initiator_username: username } : {}) }),
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
    const stats = await getStats({ my: true })
    statsPending.value = stats.pending
    statsQueued.value = stats.queued
    statsRunning.value = stats.running
    statsCompleted.value = stats.completed
    statsFailed.value = stats.failed ?? 0
    statsCancelled.value = stats.cancelled ?? 0
    statsIssueByStatus.value = stats.issues?.by_status ?? {}
  } catch {
    // Stats are supplementary; don't block UI
  }
}

async function fetchHeatmap() {
  try {
    heatmapData.value = await getActivityHeatmap(90, true)
  } catch {
    // Heatmap is supplementary
  }
}

async function fetchAnalytics() {
  try {
    const username = authState.user?.username
    const res = await getAnalytics(90, null, username || null)
    const s = res.summary
    analyticsTotalAdditions.value = s.total_additions
    analyticsTotalDeletions.value = s.total_deletions
    analyticsTotalChanges.value = s.total_changes
    analyticsInputTokens.value = s.total_input_tokens
    analyticsOutputTokens.value = s.total_output_tokens
    analyticsTotalTokens.value = s.total_tokens
  } catch {
    // Analytics are supplementary
  }
}

function refreshAll() {
  fetchData()
  fetchStats()
  fetchHeatmap()
  fetchAnalytics()
}

const { start: startPolling } = usePolling(
  () => refreshAll(),
  { interval: 15_000, immediate: false },
)

onMounted(() => {
  fetchStats()
  fetchHeatmap()
  fetchAnalytics()
  fetchData()
  startPolling()
})
</script>

<style scoped>
.dashboard {
  max-width: var(--app-page-max-width);
}

.dashboard__top-bar {
  display: flex;
  justify-content: flex-end;
  margin-bottom: 4px;
}

.dashboard-table-card {
  border-radius: var(--app-card-radius);
}

.dashboard-metric-card {
  height: 240px;
  border-radius: var(--app-card-radius);
}

.dashboard-metric-card :deep(.n-card-content) {
  display: grid;
  grid-template-rows: auto 1fr;
  height: 100%;
  overflow: hidden;
}

.metric-title {
  font-size: 13px;
  font-weight: 600;
  color: #666;
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.metric-info-icon {
  color: #bbb;
  cursor: pointer;
  transition: color 0.2s;
  &:hover {
    color: #888;
  }
}

.metric-body {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 6px;
  min-height: 0;
  overflow: hidden;
}

.dashboard-stat__value {
  font-size: 32px;
  font-weight: 700;
  color: var(--n-text-color, #333);
  line-height: 1.1;
  text-align: center;
}

.dashboard-stat__detail {
  font-size: 12px;
  color: #999;
  display: flex;
  align-items: center;
  gap: 8px;
}

.dashboard-stat__add {
  color: #18a058;
  font-weight: 600;
}

.dashboard-stat__del {
  color: #d03050;
  font-weight: 600;
}
</style>
