<template>
  <div class="dashboard" data-testid="dashboard-page">
    <n-spin :show="initialLoading" :description="t('common.loadingTasks')">
      <n-space vertical :size="16">
        <div class="dashboard__top-bar">
          <n-space align="center" :size="8">
            <span v-if="lastUpdatedText" class="dashboard__last-updated">{{ lastUpdatedText }}</span>
            <n-button size="small" quaternary :loading="loading" @click="manualRefresh">
              <template #icon><n-icon :component="RefreshOutline" /></template>
            </n-button>
            <n-divider vertical style="height: 14px; margin: 0" />
            <span class="dashboard__refresh-label">{{ t('dashboard.autoRefresh') }}</span>
            <n-switch v-model:value="autoRefreshEnabled" size="small" />
            <n-select
              class="dashboard__interval-select"
              v-model:value="refreshIntervalMs"
              :disabled="!autoRefreshEnabled"
              size="small"
              :options="intervalOptions"
              style="width: 72px"
            />
          </n-space>
        </div>
        <n-grid
          v-if="hasLoadedOnce"
          data-testid="dashboard-summary"
          :cols="isMobile ? 2 : 4"
          :x-gap="12"
          :y-gap="12"
        >
          <n-gi>
            <n-card size="small" class="dashboard-metric-card" data-testid="dashboard-summary-card">
              <n-icon size="18" :component="DocumentTextOutline" class="metric-corner-icon" />
              <div class="metric-title">
                <span>{{ t('dashboard.issueStatus') }}</span>
                <n-tooltip trigger="hover" :style="tooltipStyle"><template #trigger><n-icon size="14" class="metric-info-icon" :component="InformationCircleOutline" /></template>{{ t('dashboard.issueStatusTip') }}</n-tooltip>
              </div>
              <div class="metric-body">
                <StatusPieChart :data="issueChartData" />
              </div>
            </n-card>
          </n-gi>
          <n-gi>
            <n-card size="small" class="dashboard-metric-card" data-testid="dashboard-summary-card">
              <n-icon size="18" :component="PlayCircleOutline" class="metric-corner-icon" />
              <div class="metric-title">
                <span>{{ t('dashboard.taskStatus') }}</span>
                <n-tooltip trigger="hover" :style="tooltipStyle"><template #trigger><n-icon size="14" class="metric-info-icon" :component="InformationCircleOutline" /></template>{{ t('dashboard.taskStatusTip') }}</n-tooltip>
              </div>
              <div class="metric-body">
                <StatusPieChart :data="taskChartData" />
              </div>
            </n-card>
          </n-gi>
          <n-gi>
            <n-card size="small" class="dashboard-metric-card" data-testid="dashboard-summary-card">
              <n-icon size="18" :component="CodeSlashOutline" class="metric-corner-icon" />
              <div class="metric-title">
                <span>{{ t('dashboard.linesChanged') }}</span>
                <n-tooltip trigger="hover" :style="tooltipStyle"><template #trigger><n-icon size="14" class="metric-info-icon" :component="InformationCircleOutline" /></template>{{ t('dashboard.linesChangedTip') }}</n-tooltip>
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
              <n-icon size="18" :component="FlashOutline" class="metric-corner-icon" />
              <div class="metric-title">
                <span>{{ t('dashboard.tokensUsed') }}</span>
                <n-tooltip trigger="hover" :style="tooltipStyle"><template #trigger><n-icon size="14" class="metric-info-icon" :component="InformationCircleOutline" /></template>{{ t('dashboard.tokensUsedTip') }}</n-tooltip>
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

        <n-grid
          v-if="hasLoadedOnce"
          :cols="isMobile ? 1 : 2"
          :x-gap="12"
          :y-gap="12"
        >
          <n-gi>
            <n-card size="small" class="dashboard-metric-card dashboard-metric-card--wide" data-testid="dashboard-activity-heatmap">
              <n-icon size="18" :component="CalendarOutline" class="metric-corner-icon" />
              <div class="metric-title">
                <span>{{ t('dashboard.activity') }}</span>
                <n-tooltip trigger="hover" :style="tooltipStyle"><template #trigger><n-icon size="14" class="metric-info-icon" :component="InformationCircleOutline" /></template>{{ t('dashboard.activityTip') }}</n-tooltip>
              </div>
              <div class="metric-body">
                <ActivityHeatmap :data="heatmapData" />
              </div>
            </n-card>
          </n-gi>
          <n-gi>
            <n-card size="small" class="dashboard-metric-card dashboard-metric-card--wide dashboard-metric-card--trend" data-testid="dashboard-trend-chart">
              <n-icon size="18" :component="TrendingUpOutline" class="metric-corner-icon" />
              <div class="metric-title">
                <span>{{ t('dashboard.trend') }}</span>
                <n-tooltip trigger="hover" :style="tooltipStyle"><template #trigger><n-icon size="14" class="metric-info-icon" :component="InformationCircleOutline" /></template>{{ t('dashboard.trendTip') }}</n-tooltip>
              </div>
              <div class="metric-body">
                <TrendChart :data="trendData" />
              </div>
            </n-card>
          </n-gi>
        </n-grid>

        <MyWorkBoard
          :issue-columns="issueBoardColumns"
          :task-columns="taskBoardColumns"
          :issue-total="boardIssueTotal"
          :task-total="boardTaskTotal"
          :visible-limit="boardVisibleLimit"
          :is-mobile="isMobile"
          @select="router.push($event)"
        />
      </n-space>
    </n-spin>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted, computed, watch } from 'vue'
import { NSpace, NCard, NGrid, NGi, NSpin, NIcon, NTooltip, NButton, NSwitch, NSelect, NDivider, useMessage } from 'naive-ui'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { getIssues, getTasksPaginated, getStats, getAnalytics, getActivityHeatmap, type Issue, type Task, type ActivityHeatmapEntry, type AnalyticsTrendPoint } from '../api'
import {
  CalendarOutline,
  CodeSlashOutline,
  DocumentTextOutline,
  FlashOutline,
  InformationCircleOutline,
  PlayCircleOutline,
  RefreshOutline,
  TrendingUpOutline,
} from '@vicons/ionicons5'

import StatusPieChart from '../components/StatusPieChart.vue'
import ActivityHeatmap from '../components/ActivityHeatmap.vue'
import TrendChart from '../components/TrendChart.vue'
import MyWorkBoard, { type BoardCardItem, type BoardColumn } from '../components/dashboard/MyWorkBoard.vue'
import { useBreakpoints } from '../composables/useBreakpoints'
import { formatDateTimeUtc8Compact } from '../utils/datetime'
import { formatPriority } from '../utils/format'
import { authState } from '../auth'

const issueStatuses = ['open', 'in_progress', 'in_review', 'closed'] as const

const boardVisibleLimit = 20

const router = useRouter()
const message = useMessage()
const { t } = useI18n()
const { isMobile } = useBreakpoints()
const tooltipStyle = { fontSize: '11px', borderRadius: '6px', padding: '6px 12px', maxWidth: '280px' }

// Auto-refresh state
const autoRefreshEnabled = ref(true)
const refreshIntervalMs = ref(15_000)
const secondsSinceUpdate = ref<number | null>(null)

const intervalOptions = [
  { label: '5s', value: 5_000 },
  { label: '15s', value: 15_000 },
  { label: '30s', value: 30_000 },
  { label: '1m', value: 60_000 },
]

let refreshTimer: ReturnType<typeof setInterval> | null = null
let clockTimer: ReturnType<typeof setInterval> | null = null

const lastUpdatedText = computed(() => {
  const s = secondsSinceUpdate.value
  if (s === null) return ''
  if (s < 3) return t('dashboard.updatedJustNow')
  if (s < 60) return t('dashboard.updatedSecondsAgo', { n: s })
  const m = Math.floor(s / 60)
  return m === 1 ? t('dashboard.updated1MinuteAgo') : t('dashboard.updatedMinutesAgo', { n: m })
})

function startRefreshTimer() {
  if (refreshTimer !== null) {
    clearInterval(refreshTimer)
    refreshTimer = null
  }
  if (!autoRefreshEnabled.value) return
  refreshTimer = setInterval(() => {
    if (document.visibilityState === 'visible') refreshAll()
  }, refreshIntervalMs.value)
}

watch([autoRefreshEnabled, refreshIntervalMs], startRefreshTimer)

function manualRefresh() {
  refreshAll()
  startRefreshTimer()
}

const boardIssues = ref<Issue[]>([])
const boardTasks = ref<Task[]>([])
const boardIssueTotal = ref(0)
const boardTaskTotal = ref(0)
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
const trendData = ref<AnalyticsTrendPoint[]>([])

const initialLoading = computed(() => loading.value && !hasLoadedOnce.value)

function formatNumber(n: number): string {
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + 'M'
  if (n >= 1_000) return (n / 1_000).toFixed(1) + 'K'
  return String(n)
}

function buildIssueCard(issue: Issue): BoardCardItem {
  return {
    id: issue.id,
    title: issue.title,
    subtitle: `#${issue.id}`,
    meta: [
      t('dashboard.projectFallback', { id: issue.project_id }),
      `${issue.task_count ?? 0} ${t('issue.field.tasks')}`,
      issue.created_at ? formatDateTimeUtc8Compact(issue.created_at) : '-',
    ],
    route: `/issues/${issue.id}`,
  }
}

function buildTaskCard(task: Task, badge?: string): BoardCardItem {
  return {
    id: task.id,
    title: task.user_prompt,
    fullTitle: task.user_prompt,
    subtitle: `#${task.id}`,
    badge,
    meta: [
      formatPriority(task.priority),
      formatDateTimeUtc8Compact(task.started_at || task.created_at),
    ],
    route: `/tasks/${task.id}`,
  }
}

const issueChartData = computed(() => {
  const s = statsIssueByStatus.value
  return [
    { name: t('issue.status.open'), value: s.open ?? 0, color: '#64748b' },
    { name: t('issue.status.in_progress'), value: s.in_progress ?? 0, color: '#0ea5e9' },
    { name: t('issue.status.in_review'), value: s.in_review ?? 0, color: '#14b8a6' },
    { name: t('issue.status.closed'), value: s.closed ?? 0, color: '#8b5cf6' },
  ].filter((d) => d.value > 0)
})

const taskChartData = computed(() => {
  return [
    { name: t('status.pending'), value: statsPending.value, color: '#64748b' },
    { name: t('status.queued'), value: statsQueued.value, color: '#0ea5e9' },
    { name: t('status.running'), value: statsRunning.value, color: '#14b8a6' },
    { name: t('status.completed'), value: statsCompleted.value, color: '#8b5cf6' },
    { name: t('status.failed'), value: statsFailed.value, color: '#475569' },
    { name: t('status.cancelled'), value: statsCancelled.value, color: '#94a3b8' },
  ].filter((d) => d.value > 0)
})

const issueBoardColumns = computed<BoardColumn[]>(() =>
  issueStatuses.map((status) => {
    const items = boardIssues.value.filter((issue) => issue.status === status).map(buildIssueCard)
    return {
      status,
      label: t(`issue.status.${status}`),
      count: items.length,
      items,
    }
  }),
)

const taskBoardColumns = computed<BoardColumn[]>(() => {
  const tasks = boardTasks.value
  const queuedBadge = t('status.queued')
  const cancelledBadge = t('status.cancelled')
  const pendingItems = [
    ...tasks.filter(task => task.status === 'pending').map(task => buildTaskCard(task)),
    ...tasks.filter(task => task.status === 'queued').map(task => buildTaskCard(task, queuedBadge)),
  ].sort((a, b) => b.id - a.id)
  const runningItems = tasks.filter(task => task.status === 'running').map(task => buildTaskCard(task))
  const completedItems = tasks.filter(task => task.status === 'completed').map(task => buildTaskCard(task))
  const failedItems = [
    ...tasks.filter(task => task.status === 'failed').map(task => buildTaskCard(task)),
    ...tasks.filter(task => task.status === 'cancelled').map(task => buildTaskCard(task, cancelledBadge)),
  ].sort((a, b) => b.id - a.id)
  return [
    { status: 'pending', label: t('status.pending'), count: statsPending.value + statsQueued.value, items: pendingItems },
    { status: 'running', label: t('status.running'), count: statsRunning.value, items: runningItems },
    { status: 'completed', label: t('status.completed'), count: statsCompleted.value, items: completedItems },
    { status: 'failed', label: `${t('status.failed')} / ${t('status.cancelled')}`, count: statsFailed.value + statsCancelled.value, items: failedItems },
  ]
})

async function fetchData() {
  if (loading.value) return
  loading.value = true
  try {
    const userId = authState.user?.id
    const username = authState.user?.username

    const [issuesRes, tasksRes] = await Promise.all([
      getIssues({
        page: 1,
        page_size: boardVisibleLimit,
        ...(userId ? { initiator_user_id: userId } : {}),
      }),
      getTasksPaginated({
        page: 1,
        page_size: boardVisibleLimit,
        ...(username ? { initiator_username: username } : {}),
      }),
    ])

    boardIssues.value = issuesRes.items
    boardTasks.value = tasksRes.items
    boardIssueTotal.value = issuesRes.total
    boardTaskTotal.value = tasksRes.total
  } catch {
    message.error(t('dashboard.failedToFetchTasks'))
  } finally {
    hasLoadedOnce.value = true
    loading.value = false
    secondsSinceUpdate.value = 0
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
    trendData.value = res.trends
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

onMounted(() => {
  fetchStats()
  fetchHeatmap()
  fetchAnalytics()
  fetchData()
  startRefreshTimer()
  clockTimer = setInterval(() => {
    if (secondsSinceUpdate.value !== null) secondsSinceUpdate.value += 1
  }, 1_000)
})

onUnmounted(() => {
  if (refreshTimer !== null) clearInterval(refreshTimer)
  if (clockTimer !== null) clearInterval(clockTimer)
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

.dashboard__last-updated {
  font-size: 12px;
  color: #aaa;
}

.dashboard__refresh-label {
  font-size: 12px;
  color: #888;
}

.dashboard-table-card {
  border-radius: var(--app-card-radius);
}

.dashboard-metric-card {
  height: 240px;
  border-radius: var(--app-card-radius);
  box-shadow: 0 1px 3px rgba(15, 23, 42, 0.04), 0 4px 12px rgba(15, 23, 42, 0.03);
  border-color: rgba(15, 23, 42, 0.06) !important;
  transition: box-shadow 0.25s ease, transform 0.25s ease;
}

.dashboard-metric-card :deep(.n-card__content) {
  position: relative;
}

.dashboard-metric-card:hover {
  box-shadow: 0 2px 6px rgba(15, 23, 42, 0.06), 0 8px 20px rgba(15, 23, 42, 0.05);
  transform: translateY(-1px);
}

.dashboard-metric-card--wide {
  height: 320px;
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
  text-align: center;
  position: relative;
}

.metric-title-icon {
  margin-right: 4px;
  vertical-align: -2px;
  opacity: 0.7;
}

.metric-corner-icon {
  position: absolute;
  top: 10px;
  left: 12px;
  color: #aaa;
  opacity: 0.6;
}

.metric-info-icon {
  position: absolute;
  right: 0;
  top: 50%;
  transform: translateY(-50%);
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
