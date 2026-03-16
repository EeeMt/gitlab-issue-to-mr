<template>
  <div class="analytics-page">
    <n-spin :show="initialLoading" :description="t('analytics.loading')">
      <n-space vertical :size="20">
        <div class="analytics-page__hero">
          <div>
            <h2 class="analytics-page__title">{{ t('analytics.title') }}</h2>
            <p class="analytics-page__subtitle">
              {{ t('analytics.subtitle') }}
            </p>
          </div>
          <n-space align="center" wrap>
            <n-select
              v-model:value="windowDays"
              :options="windowOptions"
              style="width: 140px"
            />
            <n-button @click="refresh" :loading="loading">{{ t('common.refresh') }}</n-button>
          </n-space>
        </div>

        <n-alert type="info" :show-icon="false">
          {{ t('analytics.projectInfo') }}
        </n-alert>

        <n-grid v-if="hasLoadedOnce" :cols="isMobile ? 2 : 3" :x-gap="16" :y-gap="16">
          <n-gi v-for="item in summaryItems" :key="item.label" class="analytics-grid-cell">
            <n-card size="small" class="analytics-summary-card" :bordered="false">
              <div class="analytics-summary-card__label">{{ item.label }}</div>
              <div class="analytics-summary-card__value">{{ item.value }}</div>
              <div v-if="item.note" class="analytics-summary-card__note">{{ item.note }}</div>
            </n-card>
          </n-gi>
        </n-grid>

        <n-space vertical :size="16">
          <n-card class="analytics-card" :bordered="false">
            <template #header>
              <div class="analytics-card__header">
                <div>
                    <div class="analytics-card__title">{{ t('analytics.taskVolumeTrend') }}</div>
                    <div class="analytics-card__subtitle">{{ t('analytics.taskVolumeTrendSubtitle') }}</div>
                </div>
              </div>
            </template>

            <div v-if="taskTrendBars.length" class="trend-chart-scroll">
              <div class="trend-chart" :style="{ minWidth: trendChartMinWidth }">
                <div v-for="bar in taskTrendBars" :key="bar.key" class="trend-chart__item">
                  <div class="trend-chart__count">{{ bar.displayValue }}</div>
                  <div class="trend-chart__bar-wrap">
                    <div class="trend-chart__bar" :style="{ height: `${bar.heightPercent}%` }" />
                  </div>
                  <div class="trend-chart__label">{{ bar.label }}</div>
                </div>
              </div>
            </div>
          </n-card>

          <n-card class="analytics-card" :bordered="false">
            <template #header>
              <div class="analytics-card__header">
                <div>
                    <div class="analytics-card__title">{{ t('analytics.changedLinesTrend') }}</div>
                    <div class="analytics-card__subtitle">{{ t('analytics.changedLinesTrendSubtitle') }}</div>
                </div>
              </div>
            </template>

            <div v-if="changeTrendBars.length" class="trend-chart-scroll">
              <div class="trend-chart" :style="{ minWidth: trendChartMinWidth }">
                <div v-for="bar in changeTrendBars" :key="bar.key" class="trend-chart__item">
                  <div class="trend-chart__count">{{ bar.displayValue }}</div>
                  <div class="trend-chart__bar-wrap">
                    <div class="trend-chart__bar trend-chart__bar--secondary" :style="{ height: `${bar.heightPercent}%` }" />
                  </div>
                  <div class="trend-chart__label">{{ bar.label }}</div>
                </div>
              </div>
            </div>
          </n-card>

          <n-card class="analytics-card" :bordered="false">
            <template #header>
              <div class="analytics-card__header">
                <div>
                    <div class="analytics-card__title">{{ t('analytics.executionDurationTrend') }}</div>
                    <div class="analytics-card__subtitle">{{ t('analytics.executionDurationTrendSubtitle') }}</div>
                </div>
              </div>
            </template>

            <div v-if="durationTrendBars.length" class="trend-chart-scroll">
              <div class="trend-chart" :style="{ minWidth: trendChartMinWidth }">
                <div v-for="bar in durationTrendBars" :key="bar.key" class="trend-chart__item">
                  <div class="trend-chart__count">{{ bar.displayValue }}</div>
                  <div class="trend-chart__bar-wrap">
                    <div class="trend-chart__bar trend-chart__bar--accent" :style="{ height: `${bar.heightPercent}%` }" />
                  </div>
                  <div class="trend-chart__label">{{ bar.label }}</div>
                </div>
              </div>
            </div>
          </n-card>

          <n-card class="analytics-card" :bordered="false">
            <template #header>
              <div class="analytics-card__header">
                <div>
                    <div class="analytics-card__title">{{ t('analytics.tokenTrend') }}</div>
                    <div class="analytics-card__subtitle">{{ t('analytics.tokenTrendSubtitle') }}</div>
                </div>
              </div>
            </template>

            <div v-if="tokenTrendBars.length" class="trend-chart-scroll">
              <div class="trend-chart" :style="{ minWidth: trendChartMinWidth }">
                <div v-for="bar in tokenTrendBars" :key="bar.key" class="trend-chart__item">
                  <div class="trend-chart__count">{{ bar.displayValue }}</div>
                  <div class="trend-chart__bar-wrap">
                    <div class="trend-chart__bar trend-chart__bar--token" :style="{ height: `${bar.heightPercent}%` }" />
                  </div>
                  <div class="trend-chart__label">{{ bar.label }}</div>
                </div>
              </div>
            </div>
          </n-card>
        </n-space>

        <n-grid :cols="isMobile ? 1 : 2" :x-gap="16" :y-gap="16">
          <n-gi class="analytics-grid-cell">
            <n-card class="analytics-card analytics-card--stretch" :bordered="false">
              <template #header>
                <div class="analytics-card__header">
                  <div>
                      <div class="analytics-card__title">{{ t('analytics.byProject') }}</div>
                      <div class="analytics-card__subtitle">{{ t('analytics.byProjectSubtitle') }}</div>
                  </div>
                </div>
              </template>

              <n-data-table
                :columns="projectColumns"
                :data="analytics?.projects || []"
                :bordered="false"
                :pagination="{ pageSize: 8 }"
                :scroll-x="isMobile ? undefined : 1130"
              />
            </n-card>
          </n-gi>

          <n-gi class="analytics-grid-cell">
            <n-card class="analytics-card analytics-card--stretch" :bordered="false">
              <template #header>
                <div class="analytics-card__header">
                  <div>
                      <div class="analytics-card__title">{{ t('analytics.byInitiator') }}</div>
                      <div class="analytics-card__subtitle">{{ t('analytics.byInitiatorSubtitle') }}</div>
                  </div>
                </div>
              </template>

              <n-data-table
                :columns="initiatorColumns"
                :data="analytics?.initiators || []"
                :bordered="false"
                :pagination="{ pageSize: 8 }"
                :scroll-x="isMobile ? undefined : 1050"
              />
            </n-card>
          </n-gi>
        </n-grid>

        <n-grid :cols="isMobile ? 1 : 2" :x-gap="16" :y-gap="16">
          <n-gi class="analytics-grid-cell">
            <n-card class="analytics-card analytics-card--stretch" :bordered="false">
              <template #header>
                <div class="analytics-card__header">
                  <div>
                      <div class="analytics-card__title">{{ t('analytics.queueWaitByPriority') }}</div>
                      <div class="analytics-card__subtitle">{{ t('analytics.queueWaitByPrioritySubtitle') }}</div>
                  </div>
                </div>
              </template>

              <n-data-table
                :columns="priorityColumns"
                :data="analytics?.priority_waits || []"
                :bordered="false"
                :pagination="false"
              />
            </n-card>
          </n-gi>

          <n-gi class="analytics-grid-cell">
            <n-card class="analytics-card analytics-card--stretch" :bordered="false">
              <template #header>
                <div class="analytics-card__header">
                  <div>
                      <div class="analytics-card__title">{{ t('analytics.failureBreakdown') }}</div>
                      <div class="analytics-card__subtitle">{{ t('analytics.failureBreakdownSubtitle') }}</div>
                  </div>
                </div>
              </template>

              <n-data-table
                :columns="errorColumns"
                :data="analytics?.error_breakdown || []"
                :bordered="false"
                :pagination="{ pageSize: 8 }"
                :scroll-x="isMobile ? undefined : 760"
              />
            </n-card>
          </n-gi>
        </n-grid>
      </n-space>
    </n-spin>
  </div>
</template>

<script setup lang="ts">
import { computed, h, onMounted, ref, watch } from 'vue'
import {
  NAlert,
  NButton,
  NCard,
  NDataTable,
  NGi,
  NGrid,
  NSelect,
  NSpace,
  NSpin,
  useMessage,
  type DataTableColumns
} from 'naive-ui'
import { useWindowSize } from '@vueuse/core'
import { useI18n } from 'vue-i18n'
import {
  getAnalytics,
  type AnalyticsErrorRow,
  type AnalyticsInitiatorRow,
  type AnalyticsPriorityWaitRow,
  type AnalyticsProjectRow,
  type AnalyticsResponse
} from '../api'
import { formatDateTimeLocal, formatMonthDayLocal } from '../utils/datetime'

type TrendBar = {
  key: string
  label: string
  value: number
  displayValue: string
  heightPercent: number
}

const message = useMessage()
const { t } = useI18n()
const { width } = useWindowSize()
const isMobile = computed(() => width.value < 768)

const analytics = ref<AnalyticsResponse | null>(null)
const loading = ref(false)
const hasLoadedOnce = ref(false)
const windowDays = ref<number>(30)

const windowOptions = computed(() => [
  { label: t('analytics.last7Days'), value: 7 },
  { label: t('analytics.last30Days'), value: 30 },
  { label: t('analytics.last90Days'), value: 90 }
])

const initialLoading = computed(() => loading.value && !hasLoadedOnce.value)
const trendChartMinWidth = computed(() => {
  const points = analytics.value?.trends.length || 0
  const barWidth = isMobile.value ? 24 : 32
  const gap = isMobile.value ? 8 : 10
  return `${Math.max(points * barWidth + Math.max(points - 1, 0) * gap, isMobile.value ? 0 : 760)}px`
})

function formatShortDate(value: string) {
  return formatMonthDayLocal(value)
}

function formatDateTime(value: string | null) {
  if (!value) {
    return '—'
  }
  return formatDateTimeLocal(value)
}

function formatDuration(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return '—'
  }

  const seconds = Math.max(Math.round(value), 0)
  if (seconds < 60) {
    return `${seconds}s`
  }

  if (seconds < 3600) {
    const minutes = Math.floor(seconds / 60)
    const remainder = seconds % 60
    return remainder === 0 ? `${minutes}m` : `${minutes}m ${remainder}s`
  }

  const hours = Math.floor(seconds / 3600)
  const minutes = Math.floor((seconds % 3600) / 60)
  return minutes === 0 ? `${hours}h` : `${hours}h ${minutes}m`
}

function formatNumber(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return '—'
  }
  return Math.round(value).toLocaleString()
}

function formatCompactNumber(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return '—'
  }
  return new Intl.NumberFormat(undefined, {
    notation: 'compact',
    maximumFractionDigits: value >= 1000 ? 1 : 0
  }).format(value)
}

function formatPercentage(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return '—'
  }
    return `${(value * 100).toFixed(1)}%`
}

function formatTokenBreakdown(inputTokens: number, outputTokens: number) {
  return t('analytics.tokenBreakdown', {
    input: formatNumber(inputTokens),
    output: formatNumber(outputTokens)
  })
}

function buildTrendBars(values: { key: string; label: string; value: number; displayValue?: string }[]) {
  const max = Math.max(...values.map((item) => item.value), 1)
  return values.map<TrendBar>((item) => ({
    ...item,
    displayValue: item.displayValue ?? String(item.value),
    heightPercent: item.value === 0 ? 10 : Math.max((item.value / max) * 100, 14)
  }))
}

const summaryItems = computed(() => {
  const summary = analytics.value?.summary
  if (!summary) {
    return []
  }

  return [
    { label: t('analytics.tasks'), value: String(summary.total_tasks), note: t('analytics.dayWindow', { days: windowDays.value }) },
    {
      label: t('analytics.successRate'),
      value: formatPercentage(summary.success_rate),
      note:
        summary.finished_tasks > 0
          ? t('analytics.finishedBreakdown', { completed: summary.completed_tasks, failed: summary.failed_tasks, cancelled: summary.cancelled_tasks })
          : t('analytics.noFinishedTasksYet')
    },
    {
      label: t('analytics.avgDuration'),
      value: formatDuration(summary.avg_execution_seconds),
      note:
        summary.max_execution_seconds !== null
          ? t('analytics.maxDuration', { value: formatDuration(summary.max_execution_seconds) })
          : t('analytics.noExecutionData')
    },
    {
      label: t('analytics.avgQueueWait'),
      value: formatDuration(summary.avg_queue_wait_seconds),
      note:
        summary.max_queue_wait_seconds !== null
          ? t('analytics.maxQueueWait', { value: formatDuration(summary.max_queue_wait_seconds) })
          : t('analytics.noQueueData')
    },
    {
      label: t('analytics.changedLines'),
      value: String(summary.total_changes),
      note: t('analytics.changeBreakdown', { additions: summary.total_additions, deletions: summary.total_deletions })
    },
    {
      label: t('analytics.totalTokens'),
      value: formatNumber(summary.total_tokens),
      note:
        summary.token_tracked_tasks > 0
          ? `${formatTokenBreakdown(summary.total_input_tokens, summary.total_output_tokens)} · ${t('analytics.trackedTokenTasks', { count: summary.token_tracked_tasks })}`
          : t('analytics.noTokenData')
    },
    {
      label: t('analytics.avgTokensPerTask'),
      value: formatNumber(summary.avg_total_tokens_per_tracked_task),
      note:
        summary.max_total_tokens_per_tracked_task !== null
          ? t('analytics.maxTokens', { value: formatNumber(summary.max_total_tokens_per_tracked_task) })
          : t('analytics.noTokenData')
    },
    {
      label: t('analytics.trackedInitiators'),
      value: String(summary.tracked_initiator_tasks),
      note: summary.initiator_tracking_started_at
        ? t('analytics.since', { time: formatDateTime(summary.initiator_tracking_started_at) })
        : t('analytics.noTrackedInitiators')
    }
  ]
})

const taskTrendBars = computed(() =>
  buildTrendBars(
    (analytics.value?.trends || []).map((point) => ({
      key: `${point.date}-tasks`,
      label: formatShortDate(point.date),
      value: point.task_count,
      displayValue: String(point.task_count)
    }))
  )
)

const changeTrendBars = computed(() =>
  buildTrendBars(
    (analytics.value?.trends || []).map((point) => ({
      key: `${point.date}-changes`,
      label: formatShortDate(point.date),
      value: point.total_changes,
      displayValue: String(point.total_changes)
    }))
  )
)

const durationTrendBars = computed(() =>
  buildTrendBars(
    (analytics.value?.trends || []).map((point) => ({
      key: `${point.date}-duration`,
      label: formatShortDate(point.date),
      value: point.avg_execution_seconds ?? 0,
      displayValue: formatDuration(point.avg_execution_seconds)
    }))
  )
)

const tokenTrendBars = computed(() =>
  buildTrendBars(
    (analytics.value?.trends || []).map((point) => ({
      key: `${point.date}-tokens`,
      label: formatShortDate(point.date),
      value: point.total_tokens,
      displayValue: formatCompactNumber(point.total_tokens)
    }))
  )
)

const projectColumns = computed<DataTableColumns<AnalyticsProjectRow>>(() => [
  {
    title: t('common.project'),
    key: 'project_name',
    minWidth: 180,
    render: (row) =>
      h('div', { class: 'analytics-table__primary' }, [
        h('div', row.project_name),
        row.project_path_with_namespace
          ? h('div', { class: 'analytics-table__secondary' }, row.project_path_with_namespace)
          : null
      ])
  },
  { title: t('analytics.tasks'), key: 'task_count', width: 80 },
  {
    title: t('analytics.success'),
    key: 'success_rate',
    width: 110,
    render: (row) => formatPercentage(row.success_rate)
  },
  {
    title: t('analytics.avgDuration'),
    key: 'avg_execution_seconds',
    width: 120,
    render: (row) => formatDuration(row.avg_execution_seconds)
  },
  {
    title: t('analytics.avgWait'),
    key: 'avg_queue_wait_seconds',
    width: 120,
    render: (row) => formatDuration(row.avg_queue_wait_seconds)
  },
  {
    title: t('common.changes'),
    key: 'total_changes',
    width: 110,
    render: (row) =>
      h('div', { class: 'analytics-table__primary' }, [
        h('div', String(row.total_changes)),
        h('div', { class: 'analytics-table__secondary' }, t('analytics.changeBreakdown', { additions: row.additions, deletions: row.deletions }))
      ])
  },
  {
    title: t('analytics.tokens'),
    key: 'total_tokens',
    width: 150,
    render: (row) =>
      h('div', { class: 'analytics-table__primary' }, [
        h('div', formatNumber(row.total_tokens)),
        h('div', { class: 'analytics-table__secondary' }, formatTokenBreakdown(row.input_tokens, row.output_tokens))
      ])
  },
  {
    title: t('analytics.lastTask'),
    key: 'last_task_at',
    width: 150,
    render: (row) => formatDateTime(row.last_task_at)
  }
])

const initiatorColumns = computed<DataTableColumns<AnalyticsInitiatorRow>>(() => [
  {
    title: t('analytics.initiator'),
    key: 'initiator_username',
    minWidth: 160,
    render: (row) =>
      h('div', { class: 'analytics-table__primary' }, [
        h('div', row.initiator_username),
        row.initiator_gitlab_user_id !== null
          ? h('div', { class: 'analytics-table__secondary' }, t('analytics.gitlabId', { id: row.initiator_gitlab_user_id }))
          : null
      ])
  },
  { title: t('analytics.tasks'), key: 'task_count', width: 80 },
  {
    title: t('analytics.success'),
    key: 'success_rate',
    width: 110,
    render: (row) => formatPercentage(row.success_rate)
  },
  {
    title: t('analytics.avgDuration'),
    key: 'avg_execution_seconds',
    width: 120,
    render: (row) => formatDuration(row.avg_execution_seconds)
  },
  {
    title: t('analytics.avgWait'),
    key: 'avg_queue_wait_seconds',
    width: 120,
    render: (row) => formatDuration(row.avg_queue_wait_seconds)
  },
  {
    title: t('common.changes'),
    key: 'total_changes',
    width: 110,
    render: (row) =>
      h('div', { class: 'analytics-table__primary' }, [
        h('div', String(row.total_changes)),
        h('div', { class: 'analytics-table__secondary' }, t('analytics.changeBreakdown', { additions: row.additions, deletions: row.deletions }))
      ])
  },
  {
    title: t('analytics.tokens'),
    key: 'total_tokens',
    width: 150,
    render: (row) =>
      h('div', { class: 'analytics-table__primary' }, [
        h('div', formatNumber(row.total_tokens)),
        h('div', { class: 'analytics-table__secondary' }, formatTokenBreakdown(row.input_tokens, row.output_tokens))
      ])
  },
  {
    title: t('analytics.lastTask'),
    key: 'last_task_at',
    width: 150,
    render: (row) => formatDateTime(row.last_task_at)
  }
])

const priorityColumns = computed<DataTableColumns<AnalyticsPriorityWaitRow>>(() => [
  { title: t('common.priority'), key: 'priority', width: 90 },
  { title: t('analytics.startedTasks'), key: 'task_count', width: 120 },
  {
    title: t('analytics.avgWait'),
    key: 'avg_queue_wait_seconds',
    width: 130,
    render: (row) => formatDuration(row.avg_queue_wait_seconds)
  },
  {
    title: t('analytics.maxWait'),
    key: 'max_queue_wait_seconds',
    width: 130,
    render: (row) => formatDuration(row.max_queue_wait_seconds)
  }
])

const errorColumns = computed<DataTableColumns<AnalyticsErrorRow>>(() => [
  { title: t('analytics.category'), key: 'category', width: 130 },
  { title: t('analytics.failures'), key: 'count', width: 90 },
  {
    title: t('analytics.share'),
    key: 'share_of_failed',
    width: 100,
    render: (row) => formatPercentage(row.share_of_failed)
  },
  {
    title: t('analytics.example'),
    key: 'sample_message',
    minWidth: 280,
    render: (row) => row.sample_message || '—'
  }
])

async function fetchAnalytics() {
  loading.value = true
  try {
    analytics.value = await getAnalytics(windowDays.value)
  } catch (error: any) {
    message.error(error?.response?.data?.detail || t('analytics.failedToLoad'))
  } finally {
    hasLoadedOnce.value = true
    loading.value = false
  }
}

function refresh() {
  fetchAnalytics()
}

watch(windowDays, () => {
  if (hasLoadedOnce.value) {
    fetchAnalytics()
  }
})

onMounted(() => {
  fetchAnalytics()
})
</script>

<style scoped>
.analytics-page {
  max-width: 1280px;
}

.analytics-page__hero {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 16px;
  flex-wrap: wrap;
}

.analytics-page__title {
  margin: 0;
  font-size: 28px;
  line-height: 1.2;
}

.analytics-page__subtitle {
  margin: 8px 0 0;
  color: rgba(15, 23, 42, 0.68);
  max-width: 760px;
}

.analytics-summary-card,
.analytics-card {
  border-radius: 18px;
}

.analytics-grid-cell {
  display: flex;
}

.analytics-grid-cell > * {
  flex: 1;
}

.analytics-summary-card,
.analytics-card--stretch {
  height: 100%;
}

.analytics-summary-card {
  background: linear-gradient(180deg, rgba(32, 128, 240, 0.06), rgba(32, 128, 240, 0.02));
}

.analytics-summary-card :deep(.n-card__content) {
  display: flex;
  flex-direction: column;
  height: 100%;
}

.analytics-summary-card__label {
  margin-bottom: 8px;
  font-size: 12px;
  color: rgba(15, 23, 42, 0.6);
}

.analytics-summary-card__value {
  font-size: 22px;
  font-weight: 600;
  color: var(--n-text-color-1);
}

.analytics-summary-card__note {
  margin-top: auto;
  padding-top: 6px;
  font-size: 12px;
  color: rgba(15, 23, 42, 0.56);
}

.analytics-card__header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.analytics-card__title {
  font-size: 18px;
  font-weight: 600;
}

.analytics-card__subtitle {
  margin-top: 4px;
  font-size: 13px;
  color: rgba(15, 23, 42, 0.58);
}

.trend-chart {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(24px, 1fr));
  gap: 10px;
  align-items: end;
  min-height: 220px;
}

.trend-chart-scroll {
  overflow-x: auto;
  overflow-y: hidden;
  padding-bottom: 6px;
}

.trend-chart__item {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
}

.trend-chart__count {
  font-size: 12px;
  color: rgba(15, 23, 42, 0.7);
}

.trend-chart__bar-wrap {
  width: 100%;
  height: 150px;
  display: flex;
  align-items: end;
  justify-content: center;
  background: rgba(148, 163, 184, 0.12);
  border-radius: 10px;
  overflow: hidden;
}

.trend-chart__bar {
  width: 100%;
  background: linear-gradient(180deg, rgba(32, 128, 240, 0.92), rgba(32, 128, 240, 0.55));
  border-radius: 10px 10px 0 0;
}

.trend-chart__bar--secondary {
  background: linear-gradient(180deg, rgba(24, 160, 88, 0.92), rgba(24, 160, 88, 0.52));
}

.trend-chart__bar--accent {
  background: linear-gradient(180deg, rgba(245, 158, 11, 0.92), rgba(245, 158, 11, 0.52));
}

.trend-chart__bar--token {
  background: linear-gradient(180deg, rgba(168, 85, 247, 0.92), rgba(168, 85, 247, 0.52));
}

.trend-chart__label {
  font-size: 11px;
  color: rgba(15, 23, 42, 0.62);
  writing-mode: vertical-rl;
  transform: rotate(180deg);
}

.analytics-table__primary {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.analytics-table__secondary {
  font-size: 12px;
  color: rgba(15, 23, 42, 0.58);
}

@media (max-width: 768px) {
  .analytics-page__title {
    font-size: 24px;
  }

  .trend-chart__label {
    writing-mode: horizontal-tb;
    transform: none;
  }
}
</style>
