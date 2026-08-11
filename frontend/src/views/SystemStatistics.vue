<template>
  <div class="system-statistics-page" data-testid="system-statistics-page">
    <div class="system-statistics-hero">
      <PageHeader
        :title="t('systemStatistics.title')"
        :subtitle="t('systemStatistics.subtitle')"
        root-class="system-statistics-page__hero"
        title-class="system-statistics-page__title"
        subtitle-class="system-statistics-page__subtitle"
      >
        <template #actions>
          <n-button
            size="small"
            quaternary
            data-testid="system-statistics-refresh"
            :loading="refreshing"
            :disabled="refreshing"
            @click="refreshAll"
          >
            <template #icon>
              <n-icon :component="RefreshOutline" :size="16" />
            </template>
            {{ t('systemStatistics.refresh') }}
          </n-button>
        </template>
      </PageHeader>
    </div>

    <n-alert type="info" :show-icon="false" class="system-statistics-coverage" data-testid="coverage-statement">
      <template #header>
        {{ t('systemStatistics.coverageStatement') }}
      </template>
      {{ coverageStatement }}
    </n-alert>

    <n-spin :show="loading && !hasLoadedOnce" :description="t('systemStatistics.loading')">
      <div class="system-statistics-filters">
        <div class="system-statistics-filter">
          <span class="system-statistics-filter__label">{{ t('systemStatistics.dataStateLabel') }}</span>
          <n-select
            v-model:value="dataState"
            :options="dataStateOptions"
            size="small"
            class="system-statistics-filter__control"
            data-testid="data-state-select"
          />
        </div>
        <div class="system-statistics-filter">
          <span class="system-statistics-filter__label">{{ t('systemStatistics.rangeLabel') }}</span>
          <n-select
            v-model:value="range"
            :options="rangeOptions"
            size="small"
            class="system-statistics-filter__control"
            data-testid="trend-range-select"
          />
        </div>
        <div class="system-statistics-filter system-statistics-filter--meta">
          <span class="system-statistics-filter__meta">
            {{ t('systemStatistics.reportingTimezone', { timezone: reportingTimezone }) }}
          </span>
          <span v-if="lastRefreshAt" class="system-statistics-filter__meta" data-testid="last-refresh">
            {{ t('systemStatistics.lastRefresh', { time: lastRefreshAt }) }}
          </span>
        </div>
      </div>

      <!-- Current running state -->
      <n-card class="system-statistics-card" :bordered="false">
        <template #header>
          <div class="system-statistics-card__header">
            <div>
              <div class="system-statistics-card__title">{{ t('systemStatistics.currentState.title') }}</div>
              <div class="system-statistics-card__subtitle">{{ t('systemStatistics.currentState.subtitle') }}</div>
            </div>
          </div>
        </template>
        <n-grid :cols="isMobile ? 2 : 6" :x-gap="12" :y-gap="12">
          <n-gi v-for="item in currentStateItems" :key="item.labelKey">
            <div class="system-statistics-metric">
              <div class="system-statistics-metric__value">{{ item.value }}</div>
              <div class="system-statistics-metric__label">{{ item.label }}</div>
            </div>
          </n-gi>
        </n-grid>
      </n-card>

      <!-- Lifetime cumulative -->
      <n-card class="system-statistics-card" :bordered="false">
        <template #header>
          <div class="system-statistics-card__header">
            <div>
              <div class="system-statistics-card__title">{{ t('systemStatistics.lifetime.title') }}</div>
              <div class="system-statistics-card__subtitle">{{ t('systemStatistics.lifetime.subtitle') }}</div>
            </div>
          </div>
        </template>
        <n-grid :cols="isMobile ? 2 : 5" :x-gap="12" :y-gap="12">
          <n-gi v-for="item in lifetimeItems" :key="item.labelKey">
            <div class="system-statistics-metric">
              <div class="system-statistics-metric__value">{{ item.value }}</div>
              <div class="system-statistics-metric__label">{{ item.label }}</div>
            </div>
          </n-gi>
        </n-grid>
      </n-card>

      <!-- Coverage -->
      <n-card class="system-statistics-card" :bordered="false">
        <template #header>
          <div class="system-statistics-card__header">
            <div>
              <div class="system-statistics-card__title">{{ t('systemStatistics.coverage.title') }}</div>
              <div class="system-statistics-card__subtitle">{{ t('systemStatistics.coverage.subtitle') }}</div>
            </div>
          </div>
        </template>
        <n-grid :cols="isMobile ? 1 : 2" :x-gap="16" :y-gap="12">
          <n-gi>
            <div class="system-statistics-coverage-block">
              <div class="system-statistics-coverage-block__title">{{ t('systemStatistics.coverage.token') }}</div>
              <n-grid :cols="isMobile ? 2 : 4" :x-gap="8" :y-gap="8">
                <n-gi v-for="item in tokenCoverageItems" :key="item.labelKey">
                  <div class="system-statistics-metric system-statistics-metric--small">
                    <div class="system-statistics-metric__value">{{ item.value }}</div>
                    <div class="system-statistics-metric__label">{{ item.label }}</div>
                  </div>
                </n-gi>
              </n-grid>
              <div class="system-statistics-coverage-block__hint">{{ t('systemStatistics.coverage.tokenEligibleHint') }}</div>
            </div>
          </n-gi>
          <n-gi>
            <div class="system-statistics-coverage-block">
              <div class="system-statistics-coverage-block__title">{{ t('systemStatistics.coverage.code') }}</div>
              <n-grid :cols="isMobile ? 2 : 4" :x-gap="8" :y-gap="8">
                <n-gi v-for="item in codeCoverageItems" :key="item.labelKey">
                  <div class="system-statistics-metric system-statistics-metric--small">
                    <div class="system-statistics-metric__value">{{ item.value }}</div>
                    <div class="system-statistics-metric__label">{{ item.label }}</div>
                  </div>
                </n-gi>
              </n-grid>
              <div class="system-statistics-coverage-block__hint">{{ t('systemStatistics.coverage.codeEligibleHint') }}</div>
            </div>
          </n-gi>
        </n-grid>
        <div class="system-statistics-coverage-note">{{ t('systemStatistics.coverage.unknownNote') }}</div>
      </n-card>

      <!-- Basic trends -->
      <n-card class="system-statistics-card" :bordered="false">
        <template #header>
          <div class="system-statistics-card__header">
            <div>
              <div class="system-statistics-card__title">{{ t('systemStatistics.trends.title') }}</div>
              <div class="system-statistics-card__subtitle">{{ t('systemStatistics.trends.subtitle') }}</div>
            </div>
          </div>
        </template>
        <div v-if="trendCharts.length" class="system-statistics-trends">
          <div v-for="chart in trendCharts" :key="chart.labelKey" class="system-statistics-trend">
            <div class="system-statistics-trend__title">{{ chart.label }}</div>
            <v-chart
              v-if="chart.option"
              :option="chart.option"
              autoresize
              class="system-statistics-trend__chart"
            />
            <n-empty
              v-else
              class="system-statistics-trend__empty"
              data-testid="trend-empty"
              size="small"
            >
              {{ t('systemStatistics.trends.noData') }}
            </n-empty>
          </div>
        </div>
        <div v-else class="system-statistics-empty" data-testid="empty-state">
          <n-empty :description="t('systemStatistics.trends.noData')" size="small" />
        </div>
      </n-card>

      <!-- Basic breakdown -->
      <n-card class="system-statistics-card" :bordered="false">
        <template #header>
          <div class="system-statistics-card__header">
            <div>
              <div class="system-statistics-card__title">{{ t('systemStatistics.breakdowns.title') }}</div>
              <div class="system-statistics-card__subtitle">{{ t('systemStatistics.breakdowns.subtitle') }}</div>
            </div>
          </div>
        </template>
        <n-grid
          class="system-statistics-breakdown-grid"
          data-testid="breakdown-grid"
          :cols="stackedBreakdowns ? 1 : 2"
          :x-gap="16"
          :y-gap="16"
        >
          <n-gi :span="stackedBreakdowns ? 1 : 2">
            <div class="system-statistics-breakdown">
              <div class="system-statistics-breakdown__title">{{ t('systemStatistics.breakdowns.projects') }}</div>
              <n-data-table
                :columns="projectColumns"
                :data="breakdowns?.projects ?? []"
                size="small"
                :bordered="false"
                :max-height="440"
              />
            </div>
          </n-gi>
          <n-gi :span="1">
            <div class="system-statistics-breakdown">
              <div class="system-statistics-breakdown__title">{{ t('systemStatistics.breakdowns.providers') }}</div>
              <n-data-table
                :columns="providerColumns"
                :data="breakdowns?.providers ?? []"
                size="small"
                :bordered="false"
                :max-height="440"
              />
            </div>
          </n-gi>
          <n-gi :span="1">
            <div class="system-statistics-breakdown">
              <div class="system-statistics-breakdown__title">{{ t('systemStatistics.breakdowns.harnesses') }}</div>
              <n-data-table
                :columns="harnessColumns"
                :data="breakdowns?.harnesses ?? []"
                size="small"
                :bordered="false"
                :max-height="440"
              />
            </div>
          </n-gi>
        </n-grid>
      </n-card>

      <!-- Data notes -->
      <n-card class="system-statistics-card" :bordered="false">
        <template #header>
          <div class="system-statistics-card__header">
            <div>
              <div class="system-statistics-card__title">{{ t('systemStatistics.dataNotes.title') }}</div>
            </div>
          </div>
        </template>
        <ul class="system-statistics-notes">
          <li>{{ t('systemStatistics.dataNotes.reference') }}</li>
          <li data-testid="coverage-start-note">{{ deletionCoverageNote }}</li>
          <li>{{ t('systemStatistics.dataNotes.unknown') }}</li>
          <li>{{ t('systemStatistics.dataNotes.beforeCapture') }}</li>
          <li>{{ t('systemStatistics.dataNotes.noDetailLink') }}</li>
        </ul>
      </n-card>
    </n-spin>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import {
  NAlert,
  NButton,
  NCard,
  NDataTable,
  NEmpty,
  NGi,
  NGrid,
  NIcon,
  NSelect,
  NSpin,
} from 'naive-ui'
import type { DataTableColumns } from 'naive-ui'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { LineChart } from 'echarts/charts'
import { GridComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import { RefreshOutline } from '@vicons/ionicons5'
import { useI18n } from 'vue-i18n'
import {
  getSystemStatisticsBreakdowns,
  getSystemStatisticsOverview,
  getSystemStatisticsTrends,
  type SystemStatisticsBreakdownRow,
  type SystemStatisticsBreakdowns,
  type SystemStatisticsDataState,
  type SystemStatisticsOverview,
  type SystemStatisticsTrendValue,
  type SystemStatisticsTrends,
} from '../api'
import PageHeader from '../components/PageHeader.vue'
import { useBreakpoints } from '../composables/useBreakpoints'
import { formatDurationSec } from '../utils/format'
import { formatLargeNumber } from '../utils/usageLimits'

use([LineChart, GridComponent, TooltipComponent, CanvasRenderer])

const { t } = useI18n()
const { isMobile, width } = useBreakpoints()

// Below this width the two half-width breakdown tables cannot fit their
// columns (≈520px minimum) without horizontal overflow, so they stack
// full-width like the mobile layout (review EEE-32 P2).
const BREAKDOWN_STACK_BREAKPOINT = 1440
const stackedBreakdowns = computed(() => width.value < BREAKDOWN_STACK_BREAKPOINT)

const loading = ref(false)
const refreshing = ref(false)
const hasLoadedOnce = ref(false)
const overview = ref<SystemStatisticsOverview | null>(null)
const trends = ref<SystemStatisticsTrends | null>(null)
const breakdowns = ref<SystemStatisticsBreakdowns | null>(null)
const dataState = ref<SystemStatisticsDataState>('all')
const range = ref<'90d' | '1y' | 'all'>('all')
const lastRefreshMs = ref<number | null>(null)
let autoRefreshTimer: ReturnType<typeof setInterval> | null = null

const dataStateOptions = computed(() => [
  { label: t('systemStatistics.dataStateAll'), value: 'all' },
  { label: t('systemStatistics.dataStateRetained'), value: 'retained' },
  { label: t('systemStatistics.dataStateDeleted'), value: 'deleted' },
])

const rangeOptions = computed(() => [
  { label: t('systemStatistics.rangeAll'), value: 'all' },
  { label: t('systemStatistics.range90d'), value: '90d' },
  { label: t('systemStatistics.range1y'), value: '1y' },
])

const reportingTimezone = computed(() => overview.value?.reporting_timezone ?? 'Asia/Shanghai')
const lastRefreshAt = computed(() => {
  if (lastRefreshMs.value === null) return null
  return new Date(lastRefreshMs.value).toLocaleTimeString()
})

const coverageStatement = computed(() => {
  if (!overview.value) return ''
  if (overview.value.coverage.capture_enabled) {
    return overview.value.coverage.statement
  }
  return t('systemStatistics.coverageNotEnabled')
})

const deletionCoverageNote = computed(() => {
  if (!overview.value) return ''
  if (overview.value.coverage.capture_enabled && overview.value.coverage.capture_started_at) {
    return t('systemStatistics.dataNotes.deletionStart', {
      capture: overview.value.coverage.capture_started_at,
    })
  }
  return t('systemStatistics.dataNotes.deletionNotEnabled')
})

function fmtNum(value: number | null | undefined): string {
  if (value === null || value === undefined) return '—'
  return formatLargeNumber(value)
}

function fmtRate(value: number | null | undefined): string {
  if (value === null || value === undefined) return '—'
  return `${(value * 100).toFixed(1)}%`
}

function fmtDuration(value: number | null | undefined): string {
  return formatDurationSec(value)
}

interface MetricItem {
  labelKey: string
  label: string
  value: string
}

const currentStateItems = computed<MetricItem[]>(() => {
  const cs = overview.value?.current_state
  if (!cs) return []
  return [
    { labelKey: 'pending', label: t('systemStatistics.currentState.pending'), value: fmtNum(cs.pending) },
    { labelKey: 'queued', label: t('systemStatistics.currentState.queued'), value: fmtNum(cs.queued) },
    { labelKey: 'running', label: t('systemStatistics.currentState.running'), value: fmtNum(cs.running) },
    { labelKey: 'longRunning', label: t('systemStatistics.currentState.longRunning'), value: fmtNum(cs.long_running) },
    { labelKey: 'activeIssues', label: t('systemStatistics.currentState.activeIssues'), value: fmtNum(cs.active_issues) },
    { labelKey: 'avgQueueWait', label: t('systemStatistics.currentState.avgQueueWait'), value: fmtDuration(cs.avg_queue_wait_seconds) },
  ]
})

const lifetimeItems = computed<MetricItem[]>(() => {
  const lt = overview.value?.lifetime
  if (!lt) return []
  return [
    { labelKey: 'taskCount', label: t('systemStatistics.lifetime.taskCount'), value: fmtNum(lt.task_count) },
    { labelKey: 'issueCount', label: t('systemStatistics.lifetime.issueCount'), value: fmtNum(lt.issue_count) },
    { labelKey: 'completed', label: t('systemStatistics.lifetime.completed'), value: fmtNum(lt.completed) },
    { labelKey: 'failed', label: t('systemStatistics.lifetime.failed'), value: fmtNum(lt.failed) },
    { labelKey: 'cancelled', label: t('systemStatistics.lifetime.cancelled'), value: fmtNum(lt.cancelled) },
    { labelKey: 'finished', label: t('systemStatistics.lifetime.finished'), value: fmtNum(lt.finished) },
    { labelKey: 'successRate', label: t('systemStatistics.lifetime.successRate'), value: fmtRate(lt.success_rate) },
    { labelKey: 'failureRate', label: t('systemStatistics.lifetime.failureRate'), value: fmtRate(lt.failure_rate) },
    { labelKey: 'issuesWithMr', label: t('systemStatistics.lifetime.issuesWithMr'), value: fmtNum(lt.issues_with_mr) },
    { labelKey: 'knownTokens', label: t('systemStatistics.lifetime.knownTokens'), value: fmtNum(lt.known_total_tokens) },
    { labelKey: 'knownChanges', label: t('systemStatistics.lifetime.knownChanges'), value: fmtNum(lt.known_total_changes) },
    { labelKey: 'knownExecutionSeconds', label: t('systemStatistics.lifetime.knownExecutionSeconds'), value: fmtDuration(lt.known_total_execution_seconds) },
    { labelKey: 'deletedTask', label: t('systemStatistics.lifetime.deletedTaskCount'), value: fmtNum(overview.value?.deletion.deleted_task_count) },
    { labelKey: 'deletedIssue', label: t('systemStatistics.lifetime.deletedIssueCount'), value: fmtNum(overview.value?.deletion.deleted_issue_count) },
    { labelKey: 'deletedBeforeTerminal', label: t('systemStatistics.lifetime.deletedBeforeTerminal'), value: fmtNum(overview.value?.deletion.deleted_before_terminal) },
  ]
})

const tokenCoverageItems = computed<MetricItem[]>(() => {
  const tc = overview.value?.coverage.token
  if (!tc) return []
  return [
    { labelKey: 'eligible', label: t('systemStatistics.coverage.eligible'), value: fmtNum(tc.eligible_samples) },
    { labelKey: 'complete', label: t('systemStatistics.coverage.complete'), value: fmtNum(tc.complete_samples) },
    { labelKey: 'partial', label: t('systemStatistics.coverage.partial'), value: fmtNum(tc.partial_samples) },
    { labelKey: 'missing', label: t('systemStatistics.coverage.missing'), value: fmtNum(tc.missing_samples) },
    { labelKey: 'rate', label: t('systemStatistics.coverage.coverageRate'), value: fmtRate(tc.coverage_rate) },
  ]
})

const codeCoverageItems = computed<MetricItem[]>(() => {
  const cc = overview.value?.coverage.code
  if (!cc) return []
  return [
    { labelKey: 'eligible', label: t('systemStatistics.coverage.eligible'), value: fmtNum(cc.eligible_samples) },
    { labelKey: 'available', label: t('systemStatistics.coverage.available'), value: fmtNum(cc.available_samples) },
    { labelKey: 'rate', label: t('systemStatistics.coverage.coverageRate'), value: fmtRate(cc.coverage_rate) },
  ]
})

interface TrendChartView {
  labelKey: string
  label: string
  option: Record<string, unknown> | null
}

const MAX_TREND_BARS = 90

const TREND_TIME_BASES = ['created_at', 'terminal_at', 'source_deleted_at', 'issue_created_at']

const TREND_TIME_BASIS_LABELS: Record<string, string> = {
  created_at: 'systemStatistics.trends.taskCreated',
  terminal_at: 'systemStatistics.trends.taskFinished',
  source_deleted_at: 'systemStatistics.trends.taskDeleted',
  issue_created_at: 'systemStatistics.trends.issueCreated',
}

const TREND_PALETTE: Record<string, { line: string; area: string }> = {
  created_at: { line: '#2080f0', area: 'rgba(32, 128, 240, 0.12)' },
  terminal_at: { line: '#36ad6a', area: 'rgba(54, 173, 106, 0.12)' },
  source_deleted_at: { line: '#f0a020', area: 'rgba(240, 160, 32, 0.12)' },
  issue_created_at: { line: '#8b5cf6', area: 'rgba(139, 92, 246, 0.12)' },
}

function parseBucketDate(bucket: string): Date | null {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(bucket)
  if (!m) return null
  return new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]))
}

function formatBucketLabel(bucket: string, granularity: string, allBuckets: string[]): string {
  const date = parseBucketDate(bucket)
  if (!date) return bucket
  const year = date.getFullYear()
  const multiYear = allBuckets.some(b => {
    const d = parseBucketDate(b)
    return d !== null && d.getFullYear() !== year
  })
  const mm = String(date.getMonth() + 1).padStart(2, '0')
  const dd = String(date.getDate()).padStart(2, '0')
  if (granularity === 'month') return `${year}-${mm}`
  const prefix = multiYear ? `${String(year).slice(2)}-` : ''
  return `${prefix}${mm}-${dd}`
}

function formatTooltipBucket(bucket: string): string {
  const date = parseBucketDate(bucket)
  if (!date) return bucket
  const mm = String(date.getMonth() + 1).padStart(2, '0')
  const dd = String(date.getDate()).padStart(2, '0')
  return `${date.getFullYear()}-${mm}-${dd}`
}

function buildTrendOption(
  values: SystemStatisticsTrendValue[],
  label: string,
  timeBasis: string,
  granularity: string,
): Record<string, unknown> {
  const buckets = values.map(v => v.bucket)
  const counts = values.map(v => v.task_count ?? v.issue_count ?? 0)
  const palette = TREND_PALETTE[timeBasis] ?? TREND_PALETTE.created_at
  return {
    tooltip: {
      trigger: 'axis',
      appendTo: 'body',
      textStyle: { fontSize: 12 },
      padding: [6, 10],
      formatter: (params: unknown) => {
        const list = (Array.isArray(params) ? params : [params]) as Array<{
          axisValue?: unknown
          name?: string
          marker?: string
          seriesName?: string
          value?: unknown
        }>
        const first = list[0]
        const head = first
          ? formatTooltipBucket(String(first.axisValue ?? first.name ?? ''))
          : ''
        const rows = list.map(p => `${p.marker ?? ''}${p.seriesName}: ${p.value ?? ''}`).join('<br/>')
        return `<div style="font-weight:600;margin-bottom:4px">${head}</div>${rows}`
      },
    },
    grid: { top: 12, left: 36, right: 12, bottom: 28 },
    xAxis: {
      type: 'category',
      data: buckets,
      boundaryGap: false,
      axisLine: { show: false },
      axisTick: { show: false },
      axisLabel: {
        fontSize: 10,
        color: '#94a3b8',
        formatter: (v: string) => formatBucketLabel(v, granularity, buckets),
      },
    },
    yAxis: {
      type: 'value',
      minInterval: 1,
      splitLine: { lineStyle: { color: '#e2e8f0' } },
      axisLabel: { fontSize: 10, color: '#94a3b8' },
    },
    series: [
      {
        name: label,
        type: 'line',
        data: counts,
        smooth: true,
        // A single bucket has no line segment; render a visible point so the
        // chart is not blank.
        symbol: values.length < 2 ? 'circle' : 'none',
        lineStyle: { width: 2, color: palette.line },
        itemStyle: { color: palette.line },
        areaStyle: { color: palette.area },
      },
    ],
  }
}

const trendCharts = computed<TrendChartView[]>(() => {
  const trendData = trends.value
  if (!trendData) return []
  // No series at all → single global empty state. Otherwise render all four
  // canonical series, showing a placeholder for those without data so the
  // 4-chart layout stays stable and empty series stay visible.
  if (trendData.series.length === 0) return []
  const granularity = trendData.bucket ?? 'day'
  return TREND_TIME_BASES.map(timeBasis => {
    const series = trendData.series.find(s => s.time_basis === timeBasis)
    const values = (series?.values ?? []).slice(-MAX_TREND_BARS)
    const label = t(TREND_TIME_BASIS_LABELS[timeBasis] ?? timeBasis)
    return {
      labelKey: timeBasis,
      label,
      option: values.length > 0 ? buildTrendOption(values, label, timeBasis, granularity) : null,
    }
  })
})

function breakdownColumns(labelColumn: { title: string }): DataTableColumns<SystemStatisticsBreakdownRow> {
  return [
    {
      title: labelColumn.title,
      key: 'label',
      minWidth: 140,
      render: (row) => row.label || t('systemStatistics.breakdowns.unknown'),
      ellipsis: { tooltip: true },
    },
    {
      title: t('systemStatistics.breakdowns.taskCount'),
      key: 'task_count',
      width: 70,
      render: (row) => fmtNum(row.task_count),
    },
    {
      title: t('systemStatistics.breakdowns.successRate'),
      key: 'success_rate',
      width: 80,
      render: (row) => fmtRate(row.success_rate),
    },
    {
      title: t('systemStatistics.breakdowns.deleted'),
      key: 'deleted_count',
      width: 70,
      render: (row) => fmtNum(row.deleted_count),
    },
    {
      title: t('systemStatistics.breakdowns.tokens'),
      key: 'known_total_tokens',
      width: 80,
      render: (row) => fmtNum(row.known_total_tokens),
    },
    {
      title: t('systemStatistics.breakdowns.changes'),
      key: 'known_total_changes',
      width: 80,
      render: (row) => fmtNum(row.known_total_changes),
    },
  ]
}

const projectColumns = computed(() =>
  breakdownColumns({ title: t('systemStatistics.breakdowns.projects') })
)
const providerColumns = computed(() =>
  breakdownColumns({ title: t('systemStatistics.breakdowns.providers') })
)
const harnessColumns = computed(() =>
  breakdownColumns({ title: t('systemStatistics.breakdowns.harnesses') })
)

async function loadOverview(quiet = false) {
  if (!quiet) loading.value = true
  try {
    overview.value = await getSystemStatisticsOverview({
      data_state: dataState.value,
    })
    lastRefreshMs.value = Date.now()
    hasLoadedOnce.value = true
  } finally {
    if (!quiet) loading.value = false
  }
}

async function loadTrendsAndBreakdowns(quiet = false) {
  if (!quiet) loading.value = true
  try {
    const [trendsResult, breakdownsResult] = await Promise.all([
      getSystemStatisticsTrends({
        data_state: dataState.value,
        range: range.value,
      }),
      getSystemStatisticsBreakdowns({
        data_state: dataState.value,
      }),
    ])
    trends.value = trendsResult
    breakdowns.value = breakdownsResult
    hasLoadedOnce.value = true
  } finally {
    if (!quiet) loading.value = false
  }
}

async function loadAll(quiet = false) {
  await Promise.all([loadOverview(quiet), loadTrendsAndBreakdowns(quiet)])
}

async function refreshAll() {
  refreshing.value = true
  try {
    await loadAll()
  } finally {
    refreshing.value = false
  }
}

async function startAutoRefresh() {
  stopAutoRefresh()
  autoRefreshTimer = setInterval(() => {
    void loadOverview(true)
  }, 60_000)
}

function stopAutoRefresh() {
  if (autoRefreshTimer !== null) {
    clearInterval(autoRefreshTimer)
    autoRefreshTimer = null
  }
}

onMounted(() => {
  void loadAll()
  startAutoRefresh()
})

onBeforeUnmount(() => {
  stopAutoRefresh()
})

watch(dataState, () => {
  void loadAll()
})

watch(range, () => {
  void loadTrendsAndBreakdowns()
})
</script>

<style scoped>
.system-statistics-page {
  max-width: var(--app-page-max-width-wide, 1400px);
  margin: 0 auto;
}

.system-statistics-hero {
  margin-bottom: 16px;
}

.system-statistics-coverage {
  margin-bottom: 16px;
}

.system-statistics-filters {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 14px;
  margin-bottom: 16px;
}

.system-statistics-filter {
  display: inline-flex;
  align-items: center;
  gap: 8px;
}

.system-statistics-filter__label {
  font-size: 13px;
  color: rgba(15, 23, 42, 0.68);
}

.system-statistics-filter__control {
  width: 150px;
}

.system-statistics-filter--meta {
  margin-left: auto;
  gap: 16px;
}

.system-statistics-filter__meta {
  font-size: 12px;
  color: rgba(15, 23, 42, 0.5);
}

.system-statistics-card {
  margin-bottom: 16px;
  border-radius: var(--app-card-radius, 18px);
  box-shadow: var(--app-card-shadow-soft, 0 10px 24px rgba(15, 23, 42, 0.05));
}

.system-statistics-card__header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.system-statistics-card__title {
  font-size: 16px;
  font-weight: 700;
}

.system-statistics-card__subtitle {
  margin-top: 2px;
  font-size: 12.5px;
  color: rgba(15, 23, 42, 0.55);
}

.system-statistics-metric {
  padding: 14px 12px;
  border-radius: 14px;
  background: linear-gradient(180deg, rgba(32, 128, 240, 0.05), rgba(32, 128, 240, 0.02));
  border: 1px solid rgba(32, 128, 240, 0.1);
}

.system-statistics-metric--small {
  padding: 10px 8px;
}

.system-statistics-metric__value {
  font-size: 22px;
  font-weight: 700;
  line-height: 1.1;
  color: #0f172a;
}

.system-statistics-metric--small .system-statistics-metric__value {
  font-size: 16px;
}

.system-statistics-metric__label {
  margin-top: 6px;
  font-size: 12px;
  color: rgba(15, 23, 42, 0.6);
}

.system-statistics-coverage-block {
  padding: 14px;
  border-radius: 14px;
  background: rgba(148, 163, 184, 0.08);
  border: 1px solid rgba(148, 163, 184, 0.16);
}

.system-statistics-coverage-block__title {
  font-size: 13px;
  font-weight: 600;
  margin-bottom: 10px;
}

.system-statistics-coverage-block__hint {
  margin-top: 10px;
  font-size: 12px;
  color: rgba(15, 23, 42, 0.5);
}

.system-statistics-coverage-note {
  margin-top: 12px;
  font-size: 12.5px;
  color: rgba(15, 23, 42, 0.55);
}

.system-statistics-trends {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 16px;
}

.system-statistics-trend {
  padding: 12px;
  border-radius: 14px;
  background: rgba(248, 250, 252, 0.8);
  border: 1px solid rgba(15, 23, 42, 0.06);
}

.system-statistics-trend__title {
  font-size: 13px;
  font-weight: 600;
  margin-bottom: 10px;
}

.system-statistics-trend__chart {
  width: 100%;
  height: 220px;
}

.system-statistics-trend__empty {
  height: 220px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: rgba(15, 23, 42, 0.45);
}

.system-statistics-empty {
  padding: 20px 0;
  text-align: center;
  color: rgba(15, 23, 42, 0.45);
}

.system-statistics-breakdown__title {
  font-size: 13px;
  font-weight: 600;
  margin-bottom: 10px;
}

.system-statistics-notes {
  margin: 0;
  padding-left: 18px;
  font-size: 13px;
  line-height: 1.8;
  color: rgba(15, 23, 42, 0.72);
}

@media (max-width: 767px) {
  .system-statistics-filter--meta {
    margin-left: 0;
    flex-direction: column;
    gap: 4px;
  }

  .system-statistics-trends {
    grid-template-columns: 1fr;
  }
}
</style>
