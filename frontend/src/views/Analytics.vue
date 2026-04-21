<template>
  <div class="analytics-page">
    <n-spin :show="initialLoading" :description="t('analytics.loading')">
      <n-space vertical :size="20">
        <PageHeader
          :title="t('analytics.title')"
          :subtitle="t('analytics.subtitle')"
          root-class="analytics-page__hero"
          title-class="analytics-page__title"
          subtitle-class="analytics-page__subtitle"
          actions-class="analytics-page__controls"
        >
          <template #actions>
            <n-select
              v-model:value="windowDays"
              :options="windowOptions"
              :style="{ width: isMobile ? '100%' : '140px' }"
            />
            <n-select
              v-model:value="selectedProjectId"
              :options="projectOptions"
              :loading="projectsLoading"
              :placeholder="t('analytics.projectFilterPlaceholder')"
              clearable
              filterable
              :style="{ width: isMobile ? '100%' : '220px' }"
            />
            <n-select
              v-model:value="selectedInitiatorUsername"
              :options="initiatorOptions"
              :placeholder="t('analytics.initiatorFilterPlaceholder')"
              clearable
              filterable
              :style="{ width: isMobile ? '100%' : '220px' }"
            />
            <n-button @click="refresh" :loading="loading" :style="{ width: isMobile ? '100%' : undefined }">
              {{ t('common.refresh') }}
            </n-button>
          </template>
        </PageHeader>

        <n-alert type="info" :show-icon="false">
          {{ t('analytics.projectInfo') }}
        </n-alert>

        <n-grid v-if="hasLoadedOnce" :cols="isMobile ? 2 : 3" :x-gap="16" :y-gap="16">
          <n-gi v-for="item in summaryItems" :key="item.label" class="analytics-grid-cell">
            <SummaryCard
              :label="item.label"
              :value="item.value"
              :note="item.note"
              card-class="analytics-summary-card"
              label-class="analytics-summary-card__label"
              value-class="analytics-summary-card__value"
              note-class="analytics-summary-card__note"
            />
          </n-gi>
        </n-grid>

        <n-grid v-if="hasLoadedOnce" :cols="isMobile ? 1 : 2" :x-gap="16" :y-gap="16">
          <n-gi class="analytics-grid-cell">
            <n-card class="analytics-card analytics-card--stretch" :bordered="false" data-testid="analytics-issue-status-card">
              <template #header>
                <div class="analytics-card__header">
                  <div>
                    <div class="analytics-card__title">{{ t('analytics.issueStatusDistribution') }}</div>
                    <div class="analytics-card__subtitle">{{ t('analytics.issueStatusDistributionSubtitle') }}</div>
                  </div>
                  <div class="analytics-card__header-actions analytics-card__header-actions--status">
                    <div class="analytics-chart-toggle" role="tablist" :aria-label="t('analytics.issueStatusDistribution')">
                      <button
                        type="button"
                        class="analytics-chart-toggle__button"
                        :class="{ 'analytics-chart-toggle__button--active': issueStatusChartMode === 'bar' }"
                        data-testid="issue-status-chart-mode-bar"
                        :disabled="!hasIssueStatusData"
                        @click="issueStatusChartMode = 'bar'"
                      >
                        {{ t('analytics.barChart') }}
                      </button>
                      <button
                        type="button"
                        class="analytics-chart-toggle__button"
                        :class="{ 'analytics-chart-toggle__button--active': issueStatusChartMode === 'donut' }"
                        data-testid="issue-status-chart-mode-donut"
                        :disabled="!hasIssueStatusData"
                        @click="issueStatusChartMode = 'donut'"
                      >
                        {{ t('analytics.donutChart') }}
                      </button>
                    </div>
                  </div>
                </div>
              </template>

              <div class="analytics-status-card__body">
                <div v-if="!hasIssueStatusData" class="analytics-empty-state">
                  <div class="analytics-empty-state__title">{{ t('analytics.issueStatusDistributionEmpty') }}</div>
                </div>
                <div v-else-if="issueStatusChartMode === 'bar'" class="status-chart status-chart--bar">
                  <div v-for="row in issueStatusRows" :key="`issue-${row.status}`" class="status-chart__bar-row">
                    <div class="status-chart__row-meta">
                      <span class="status-chart__legend-dot" :style="{ background: row.color }" />
                      <span class="status-chart__row-label">{{ row.label }}</span>
                    </div>
                    <div class="status-chart__bar-track">
                      <div class="status-chart__bar-fill" :style="{ width: `${row.barWidthPercent}%`, background: row.color }" />
                    </div>
                    <div class="status-chart__row-value">{{ row.count }}</div>
                    <div class="status-chart__row-share">{{ row.shareLabel }}</div>
                  </div>
                </div>

                <div v-else-if="issueStatusChartMode === 'donut'" class="status-chart status-chart--donut">
                  <div class="status-chart__donut-shell">
                    <div class="status-chart__donut" :style="issueStatusDonutStyle">
                      <div class="status-chart__donut-hole">
                        <div class="status-chart__donut-total">{{ issueStatusTotal }}</div>
                        <div class="status-chart__donut-total-label">{{ t('analytics.issues') }}</div>
                      </div>
                    </div>
                  </div>
                  <div class="status-chart__legend">
                    <div v-for="row in issueStatusRows" :key="`issue-legend-${row.status}`" class="status-chart__legend-row">
                      <div class="status-chart__row-meta">
                        <span class="status-chart__legend-dot" :style="{ background: row.color }" />
                        <span class="status-chart__row-label">{{ row.label }}</span>
                      </div>
                      <div class="status-chart__legend-values">
                        <span class="status-chart__row-value">{{ row.count }}</span>
                        <span class="status-chart__row-share">{{ row.shareLabel }}</span>
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            </n-card>
          </n-gi>

          <n-gi class="analytics-grid-cell">
            <n-card class="analytics-card analytics-card--stretch" :bordered="false" data-testid="analytics-task-status-card">
              <template #header>
                <div class="analytics-card__header">
                  <div>
                    <div class="analytics-card__title">{{ t('analytics.taskStatusDistribution') }}</div>
                    <div class="analytics-card__subtitle">{{ t('analytics.taskStatusDistributionSubtitle') }}</div>
                  </div>
                  <div class="analytics-card__header-actions analytics-card__header-actions--status">
                    <div class="analytics-chart-toggle" role="tablist" :aria-label="t('analytics.taskStatusDistribution')">
                      <button
                        type="button"
                        class="analytics-chart-toggle__button"
                        :class="{ 'analytics-chart-toggle__button--active': taskStatusChartMode === 'bar' }"
                        data-testid="task-status-chart-mode-bar"
                        :disabled="!hasTaskStatusData"
                        @click="taskStatusChartMode = 'bar'"
                      >
                        {{ t('analytics.barChart') }}
                      </button>
                      <button
                        type="button"
                        class="analytics-chart-toggle__button"
                        :class="{ 'analytics-chart-toggle__button--active': taskStatusChartMode === 'donut' }"
                        data-testid="task-status-chart-mode-donut"
                        :disabled="!hasTaskStatusData"
                        @click="taskStatusChartMode = 'donut'"
                      >
                        {{ t('analytics.donutChart') }}
                      </button>
                    </div>
                  </div>
                </div>
              </template>

              <div class="analytics-status-card__body">
                <div v-if="!hasTaskStatusData" class="analytics-empty-state">
                  <div class="analytics-empty-state__title">{{ t('analytics.taskStatusDistributionEmpty') }}</div>
                </div>
                <div v-else-if="taskStatusChartMode === 'bar'" class="status-chart status-chart--bar">
                  <div v-for="row in taskStatusRows" :key="`task-${row.status}`" class="status-chart__bar-row">
                    <div class="status-chart__row-meta">
                      <span class="status-chart__legend-dot" :style="{ background: row.color }" />
                      <span class="status-chart__row-label">{{ row.label }}</span>
                    </div>
                    <div class="status-chart__bar-track">
                      <div class="status-chart__bar-fill" :style="{ width: `${row.barWidthPercent}%`, background: row.color }" />
                    </div>
                    <div class="status-chart__row-value">{{ row.count }}</div>
                    <div class="status-chart__row-share">{{ row.shareLabel }}</div>
                  </div>
                </div>

                <div v-else-if="taskStatusChartMode === 'donut'" class="status-chart status-chart--donut">
                  <div class="status-chart__donut-shell">
                    <div class="status-chart__donut" :style="taskStatusDonutStyle">
                      <div class="status-chart__donut-hole">
                        <div class="status-chart__donut-total">{{ taskStatusTotal }}</div>
                        <div class="status-chart__donut-total-label">{{ t('analytics.tasks') }}</div>
                      </div>
                    </div>
                  </div>
                  <div class="status-chart__legend">
                    <div v-for="row in taskStatusRows" :key="`task-legend-${row.status}`" class="status-chart__legend-row">
                      <div class="status-chart__row-meta">
                        <span class="status-chart__legend-dot" :style="{ background: row.color }" />
                        <span class="status-chart__row-label">{{ row.label }}</span>
                      </div>
                      <div class="status-chart__legend-values">
                        <span class="status-chart__row-value">{{ row.count }}</span>
                        <span class="status-chart__row-share">{{ row.shareLabel }}</span>
                      </div>
                    </div>
                  </div>
                </div>
              </div>
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

            <div v-if="taskTrendBars.length" ref="taskChartRef" class="trend-chart-scroll">
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

            <div v-if="changeTrendBars.length" ref="changeChartRef" class="trend-chart-scroll">
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

            <div v-if="durationTrendBars.length" ref="durationChartRef" class="trend-chart-scroll">
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

            <div v-if="tokenTrendBars.length" ref="tokenChartRef" class="trend-chart-scroll">
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

        <n-card class="analytics-card analytics-card--stretch analytics-breakdown-card" :bordered="false" data-testid="analytics-breakdown-card">
          <template #header>
            <div class="analytics-card__header analytics-card__header--breakdown">
              <div>
                <div class="analytics-card__title">{{ analyticsBreakdownTitle }}</div>
                <div class="analytics-card__subtitle">{{ analyticsBreakdownSubtitle }}</div>
              </div>
              <div class="analytics-card__header-actions analytics-card__header-actions--breakdown">
                <n-tabs v-model:value="analyticsBreakdownTab" type="segment" size="small" class="analytics-breakdown-tabs">
                  <n-tab-pane name="project" :tab="t('analytics.byProject')" />
                  <n-tab-pane name="initiator" :tab="t('analytics.byInitiator')" />
                </n-tabs>
                <n-button text size="small" @click="showBreakdownModal = true" class="analytics-card__expand-btn" :title="t('analytics.expand')">
                  <template #icon><n-icon :component="ExpandOutline" /></template>
                </n-button>
              </div>
            </div>
          </template>

          <n-data-table
            :columns="analyticsBreakdownColumns"
            :data="analyticsBreakdownData"
            :bordered="false"
            :pagination="{ pageSize: 8 }"
            :scroll-x="analyticsBreakdownScrollX"
          />
        </n-card>

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

    <n-modal v-model:show="showBreakdownModal" :mask-closable="true" style="width: 90vw; max-width: 1400px;">
      <n-card class="analytics-card" :bordered="false">
        <template #header>
          <div class="analytics-card__header">
            <div>
              <div class="analytics-card__title">{{ analyticsBreakdownTitle }}</div>
              <div class="analytics-card__subtitle">{{ analyticsBreakdownSubtitle }}</div>
            </div>
            <n-button text size="small" @click="showBreakdownModal = false">
              <template #icon><n-icon :component="CloseOutline" /></template>
            </n-button>
          </div>
        </template>
        <n-data-table
          :columns="analyticsBreakdownColumns"
          :data="analyticsBreakdownData"
          :bordered="false"
          :pagination="{ pageSize: 20 }"
          :scroll-x="analyticsBreakdownModalScrollX"
        />
      </n-card>
    </n-modal>
  </div>
</template>

<script setup lang="ts">
import { computed, h, nextTick, onMounted, ref, watch } from 'vue'
import {
  NAlert,
  NButton,
  NCard,
  NDataTable,
  NGi,
  NGrid,
  NModal,
  NTabPane,
  NTabs,
  NSelect,
  NSpace,
  NSpin,
  NIcon,
  useMessage,
  type DataTableColumns
} from 'naive-ui'
import { useI18n } from 'vue-i18n'
import {
  getAnalytics,
  getProjects,
  getStats,
  type AnalyticsErrorRow,
  type AnalyticsInitiatorOption,
  type AnalyticsInitiatorRow,
  type AnalyticsPriorityWaitRow,
  type AnalyticsProjectRow,
  type AnalyticsResponse,
  type AnalyticsStatusRow,
  type Project
} from '../api'
import PageHeader from '../components/PageHeader.vue'
import SummaryCard from '../components/SummaryCard.vue'
import { useBreakpoints } from '../composables/useBreakpoints'
import { formatDateTimeLocal, formatMonthDayLocal } from '../utils/datetime'
import { formatDurationSec } from '../utils/format'
import { ExpandOutline, CloseOutline } from '@vicons/ionicons5'

type TrendBar = {
  key: string
  label: string
  value: number
  displayValue: string
  heightPercent: number
}

type StatusChartMode = 'bar' | 'donut'

type StatusChartRow = AnalyticsStatusRow & {
  label: string
  color: string
  barWidthPercent: number
  shareLabel: string
}

const message = useMessage()
const { t } = useI18n()
const { isMobile } = useBreakpoints()

const ISSUE_STATUS_COLORS: Record<string, string> = {
  open: 'rgba(59, 130, 246, 0.9)',
  in_progress: 'rgba(245, 158, 11, 0.9)',
  in_review: 'rgba(168, 85, 247, 0.9)',
  closed: 'rgba(34, 197, 94, 0.9)'
}

const TASK_STATUS_COLORS: Record<string, string> = {
  pending: 'rgba(148, 163, 184, 0.95)',
  queued: 'rgba(56, 189, 248, 0.9)',
  running: 'rgba(245, 158, 11, 0.9)',
  completed: 'rgba(34, 197, 94, 0.9)',
  failed: 'rgba(239, 68, 68, 0.9)',
  cancelled: 'rgba(100, 116, 139, 0.9)'
}

const FALLBACK_STATUS_COLORS = [
  'rgba(59, 130, 246, 0.9)',
  'rgba(245, 158, 11, 0.9)',
  'rgba(168, 85, 247, 0.9)',
  'rgba(34, 197, 94, 0.9)',
  'rgba(239, 68, 68, 0.9)',
  'rgba(100, 116, 139, 0.9)'
]

const analytics = ref<AnalyticsResponse | null>(null)
const availableProjects = ref<Project[]>([])
const loading = ref(false)
const projectsLoading = ref(false)
const hasLoadedOnce = ref(false)
const issueTotal = ref(0)
const windowDays = ref<number>(30)
const selectedProjectId = ref<number | null>(null)
const selectedInitiatorUsername = ref<string | null>(null)
const taskChartRef = ref<HTMLElement | null>(null)
const changeChartRef = ref<HTMLElement | null>(null)
const durationChartRef = ref<HTMLElement | null>(null)
const tokenChartRef = ref<HTMLElement | null>(null)
const analyticsBreakdownTab = ref<'project' | 'initiator'>('project')
const showBreakdownModal = ref(false)
const issueStatusChartMode = ref<StatusChartMode>('bar')
const taskStatusChartMode = ref<StatusChartMode>('bar')

const windowOptions = computed(() => [
  { label: t('analytics.last7Days'), value: 7 },
  { label: t('analytics.last30Days'), value: 30 },
  { label: t('analytics.last90Days'), value: 90 }
])
const projectOptions = computed(() =>
  availableProjects.value.map((project) => ({
    label: project.path_with_namespace || project.name,
    value: project.id
  }))
)
const initiatorOptions = computed(() =>
  (analytics.value?.available_initiators || []).map((initiator: AnalyticsInitiatorOption) => ({
    label: `${initiator.initiator_username} (${initiator.task_count})`,
    value: initiator.initiator_username
  }))
)

const initialLoading = computed(() => loading.value && !hasLoadedOnce.value)
const trendChartMinWidth = computed(() => {
  const points = analytics.value?.trends?.length ?? 0
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

const secondaryTextStyle = { fontSize: '11px', color: 'rgba(15,23,42,0.45)', marginTop: '2px', lineHeight: '1.4' }

function buildTrendBars(values: { key: string; label: string; value: number; displayValue?: string }[]) {
  const max = Math.max(...values.map((item) => item.value), 1)
  return values.map<TrendBar>((item) => ({
    ...item,
    displayValue: item.displayValue ?? String(item.value),
    heightPercent: item.value === 0 ? 10 : Math.max((item.value / max) * 100, 14)
  }))
}

function resolveStatusLabel(kind: 'issue' | 'task', status: string) {
  return kind === 'issue' ? t(`issue.status.${status}`) : t(`status.${status}`)
}

function buildStatusChartRows(kind: 'issue' | 'task', rows: AnalyticsStatusRow[]) {
  const palette = kind === 'issue' ? ISSUE_STATUS_COLORS : TASK_STATUS_COLORS
  const max = Math.max(...rows.map((row) => row.count), 1)

  return rows.map<StatusChartRow>((row, index) => ({
    ...row,
    label: resolveStatusLabel(kind, row.status),
    color: palette[row.status] ?? FALLBACK_STATUS_COLORS[index % FALLBACK_STATUS_COLORS.length],
    barWidthPercent: row.count === 0 ? 0 : Math.max((row.count / max) * 100, 8),
    shareLabel: formatPercentage(row.share)
  }))
}

function buildStatusDonutStyle(rows: StatusChartRow[]) {
  let cursor = 0
  const segments = rows
    .filter((row) => row.count > 0)
    .map((row, idx, arr) => {
      const start = cursor
      cursor += row.share * 100
      const end = idx === arr.length - 1 ? 100 : cursor
      return `${row.color} ${start}% ${end}%`
    })

  return {
    background: segments.length
      ? `conic-gradient(${segments.join(', ')})`
      : 'conic-gradient(rgba(148, 163, 184, 0.18) 0% 100%)'
  }
}

const summaryItems = computed(() => {
  const summary = analytics.value?.summary
  const items: Array<{ label: string; value: string; note?: string }> = []

  // Always show Issues card
  items.push({
    label: t('analytics.issues'),
    value: String(issueTotal.value)
  })

  if (!summary) {
    return items
  }

  items.push(
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
      value: formatDurationSec(summary.avg_execution_seconds),
      note:
        summary.max_execution_seconds !== null
          ? t('analytics.maxDuration', { value: formatDurationSec(summary.max_execution_seconds) })
          : t('analytics.noExecutionData')
    },
    {
      label: t('analytics.avgQueueWait'),
      value: formatDurationSec(summary.avg_queue_wait_seconds),
      note:
        summary.max_queue_wait_seconds !== null
          ? t('analytics.maxQueueWait', { value: formatDurationSec(summary.max_queue_wait_seconds) })
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
  )

  return items
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
      displayValue: formatDurationSec(point.avg_execution_seconds)
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

const issueStatusRows = computed(() =>
  buildStatusChartRows('issue', analytics.value?.issue_status_breakdown || [])
)

const taskStatusRows = computed(() =>
  buildStatusChartRows('task', analytics.value?.task_status_breakdown || [])
)

const issueStatusTotal = computed(() =>
  issueStatusRows.value.reduce((sum, row) => sum + row.count, 0)
)

const taskStatusTotal = computed(() =>
  taskStatusRows.value.reduce((sum, row) => sum + row.count, 0)
)

const hasIssueStatusData = computed(() => issueStatusTotal.value > 0)
const hasTaskStatusData = computed(() => taskStatusTotal.value > 0)

const issueStatusDonutStyle = computed(() =>
  buildStatusDonutStyle(issueStatusRows.value)
)

const taskStatusDonutStyle = computed(() =>
  buildStatusDonutStyle(taskStatusRows.value)
)

const analyticsBreakdownTitle = computed(() =>
  analyticsBreakdownTab.value === 'project' ? t('analytics.byProject') : t('analytics.byInitiator')
)

const analyticsBreakdownSubtitle = computed(() =>
  analyticsBreakdownTab.value === 'project'
    ? t('analytics.byProjectSubtitle')
    : t('analytics.byInitiatorSubtitle')
)

const projectColumns = computed<DataTableColumns<AnalyticsProjectRow>>(() => [
  {
    title: t('common.project'),
    key: 'project_name',
    minWidth: 180,
    sorter: (a, b) => a.project_name.localeCompare(b.project_name),
    render: (row) =>
      h('div', [
        h('div', { style: { fontWeight: 500 } }, row.project_name),
        row.project_path_with_namespace
          ? h('div', { style: { fontSize: '11px', color: 'rgba(15,23,42,0.45)', marginTop: '2px', lineHeight: '1.4' } }, row.project_path_with_namespace)
          : null
      ])
  },
  { title: t('analytics.tasks'), key: 'task_count', width: 80, sorter: (a, b) => a.task_count - b.task_count },
  {
    title: t('analytics.success'),
    key: 'success_rate',
    width: 110,
    sorter: (a, b) => (a.success_rate ?? -1) - (b.success_rate ?? -1),
    render: (row) => formatPercentage(row.success_rate)
  },
  {
    title: t('analytics.avgDuration'),
    key: 'avg_execution_seconds',
    width: 120,
    sorter: (a, b) => (a.avg_execution_seconds ?? -1) - (b.avg_execution_seconds ?? -1),
    render: (row) => formatDurationSec(row.avg_execution_seconds)
  },
  {
    title: t('analytics.avgWait'),
    key: 'avg_queue_wait_seconds',
    width: 120,
    sorter: (a, b) => (a.avg_queue_wait_seconds ?? -1) - (b.avg_queue_wait_seconds ?? -1),
    render: (row) => formatDurationSec(row.avg_queue_wait_seconds)
  },
  {
    title: t('common.changes'),
    key: 'total_changes',
    width: 110,
    sorter: (a, b) => a.total_changes - b.total_changes,
    render: (row) =>
      h('div', [
        h('div', String(row.total_changes)),
        h('div', { style: secondaryTextStyle }, t('analytics.changeBreakdown', { additions: row.additions, deletions: row.deletions }))
      ])
  },
  {
    title: t('analytics.tokens'),
    key: 'total_tokens',
    width: 140,
    sorter: (a, b) => a.total_tokens - b.total_tokens,
    render: (row) =>
      h('div', [
        h('div', formatNumber(row.total_tokens)),
        h('div', { style: secondaryTextStyle }, t('analytics.tokenInputLine', { value: formatNumber(row.input_tokens) })),
        h('div', { style: secondaryTextStyle }, t('analytics.tokenOutputLine', { value: formatNumber(row.output_tokens) }))
      ])
  },
  {
    title: t('analytics.lastTask'),
    key: 'last_task_at',
    width: 150,
    sorter: (a, b) => (a.last_task_at ?? '').localeCompare(b.last_task_at ?? ''),
    render: (row) => formatDateTime(row.last_task_at)
  }
])

const initiatorColumns = computed<DataTableColumns<AnalyticsInitiatorRow>>(() => [
  {
    title: t('analytics.initiator'),
    key: 'initiator_username',
    minWidth: 160,
    sorter: (a, b) => a.initiator_username.localeCompare(b.initiator_username),
    render: (row) =>
      h('div', [
        h('div', { style: { fontWeight: 500 } }, row.initiator_username),
        row.initiator_gitlab_user_id !== null
          ? h('div', { style: secondaryTextStyle }, t('analytics.gitlabId', { id: row.initiator_gitlab_user_id }))
          : null
      ])
  },
  { title: t('analytics.tasks'), key: 'task_count', width: 80, sorter: (a, b) => a.task_count - b.task_count },
  {
    title: t('analytics.success'),
    key: 'success_rate',
    width: 110,
    sorter: (a, b) => (a.success_rate ?? -1) - (b.success_rate ?? -1),
    render: (row) => formatPercentage(row.success_rate)
  },
  {
    title: t('analytics.avgDuration'),
    key: 'avg_execution_seconds',
    width: 120,
    sorter: (a, b) => (a.avg_execution_seconds ?? -1) - (b.avg_execution_seconds ?? -1),
    render: (row) => formatDurationSec(row.avg_execution_seconds)
  },
  {
    title: t('analytics.avgWait'),
    key: 'avg_queue_wait_seconds',
    width: 120,
    sorter: (a, b) => (a.avg_queue_wait_seconds ?? -1) - (b.avg_queue_wait_seconds ?? -1),
    render: (row) => formatDurationSec(row.avg_queue_wait_seconds)
  },
  {
    title: t('common.changes'),
    key: 'total_changes',
    width: 110,
    sorter: (a, b) => a.total_changes - b.total_changes,
    render: (row) =>
      h('div', [
        h('div', String(row.total_changes)),
        h('div', { style: secondaryTextStyle }, t('analytics.changeBreakdown', { additions: row.additions, deletions: row.deletions }))
      ])
  },
  {
    title: t('analytics.tokens'),
    key: 'total_tokens',
    width: 140,
    sorter: (a, b) => a.total_tokens - b.total_tokens,
    render: (row) =>
      h('div', [
        h('div', formatNumber(row.total_tokens)),
        h('div', { style: secondaryTextStyle }, t('analytics.tokenInputLine', { value: formatNumber(row.input_tokens) })),
        h('div', { style: secondaryTextStyle }, t('analytics.tokenOutputLine', { value: formatNumber(row.output_tokens) }))
      ])
  },
  {
    title: t('analytics.lastTask'),
    key: 'last_task_at',
    width: 150,
    sorter: (a, b) => (a.last_task_at ?? '').localeCompare(b.last_task_at ?? ''),
    render: (row) => formatDateTime(row.last_task_at)
  }
])

const analyticsBreakdownColumns = computed(() =>
  analyticsBreakdownTab.value === 'project' ? projectColumns.value : initiatorColumns.value
)

const analyticsBreakdownData = computed(() =>
  analyticsBreakdownTab.value === 'project'
    ? (analytics.value?.projects || [])
    : (analytics.value?.initiators || [])
)

const analyticsBreakdownScrollX = computed(() => {
  if (isMobile.value) {
    return undefined
  }

  return analyticsBreakdownTab.value === 'project' ? 1130 : 1050
})

const analyticsBreakdownModalScrollX = computed(() =>
  analyticsBreakdownTab.value === 'project' ? 1130 : 1050
)

const priorityColumns = computed<DataTableColumns<AnalyticsPriorityWaitRow>>(() => [
  { title: t('common.priority'), key: 'priority', width: 90 },
  { title: t('analytics.startedTasks'), key: 'task_count', width: 120 },
  {
    title: t('analytics.avgWait'),
    key: 'avg_queue_wait_seconds',
    width: 130,
    render: (row) => formatDurationSec(row.avg_queue_wait_seconds)
  },
  {
    title: t('analytics.maxWait'),
    key: 'max_queue_wait_seconds',
    width: 130,
    render: (row) => formatDurationSec(row.max_queue_wait_seconds)
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
    analytics.value = await getAnalytics(
      windowDays.value,
      selectedProjectId.value,
      selectedInitiatorUsername.value
    )
    await nextTick()
    scrollChartsToEnd()
  } catch (error: any) {
    message.error(error?.response?.data?.detail || t('analytics.failedToLoad'))
  } finally {
    hasLoadedOnce.value = true
    loading.value = false
  }
}

function scrollChartsToEnd() {
  const charts = [taskChartRef.value, changeChartRef.value, durationChartRef.value, tokenChartRef.value]
  for (const chart of charts) {
    if (chart) {
      chart.scrollLeft = chart.scrollWidth
    }
  }
}

async function fetchProjects() {
  projectsLoading.value = true
  try {
    availableProjects.value = await getProjects()
  } catch (error: any) {
    message.error(error?.response?.data?.detail || t('analytics.failedToLoadProjects'))
  } finally {
    projectsLoading.value = false
  }
}

async function fetchIssueStats() {
  try {
    const stats = await getStats()
    issueTotal.value = stats.issues?.total ?? 0
  } catch {
    // Non-critical — don't block analytics
  }
}

function refresh() {
  fetchAnalytics()
  fetchIssueStats()
}

watch(windowDays, () => {
  if (hasLoadedOnce.value) {
    fetchAnalytics()
  }
})

watch(selectedProjectId, (value, previousValue) => {
  if (value === previousValue) {
    return
  }

  if (selectedInitiatorUsername.value) {
    selectedInitiatorUsername.value = null
    return
  }

  if (hasLoadedOnce.value) {
    fetchAnalytics()
  }
})

watch(selectedInitiatorUsername, () => {
  if (hasLoadedOnce.value) {
    fetchAnalytics()
  }
})

onMounted(() => {
  fetchProjects()
  fetchAnalytics()
  fetchIssueStats()
})
</script>

<style scoped>
.analytics-page {
  max-width: var(--app-page-max-width);
}

.analytics-summary-card,
.analytics-card {
  border-radius: var(--app-card-radius);
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

.analytics-summary-card__value {
  font-size: 22px;
}

.analytics-summary-card__note {
  margin-top: 10px;
}

.analytics-card__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.analytics-card__header--breakdown {
  align-items: flex-start;
}

.analytics-card__header-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.analytics-card__header-actions--breakdown {
  flex-wrap: wrap;
  justify-content: flex-end;
}

.analytics-card__header-actions--status {
  align-items: flex-start;
}

.analytics-breakdown-card {
  width: 100%;
}

.analytics-breakdown-tabs {
  flex: 1 1 auto;
  min-width: 280px;
}

.analytics-card__expand-btn {
  flex-shrink: 0;
  color: rgba(15, 23, 42, 0.45);
  font-size: 16px;
}

.analytics-card__expand-btn:hover {
  color: rgba(15, 23, 42, 0.8);
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

.analytics-chart-toggle {
  display: inline-flex;
  align-items: center;
  padding: 4px;
  border-radius: 999px;
  background: rgba(148, 163, 184, 0.12);
  border: 1px solid rgba(148, 163, 184, 0.18);
}

.analytics-chart-toggle__button {
  border: none;
  background: transparent;
  color: rgba(15, 23, 42, 0.62);
  padding: 7px 12px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  transition: background-color 0.18s ease, color 0.18s ease, box-shadow 0.18s ease;
}

.analytics-chart-toggle__button--active {
  background: rgba(255, 255, 255, 0.92);
  color: rgba(15, 23, 42, 0.92);
  box-shadow: 0 1px 3px rgba(15, 23, 42, 0.12);
}

.status-chart {
  display: flex;
  gap: 20px;
}

.status-chart--bar {
  flex-direction: column;
}

.status-chart__bar-row,
.status-chart__legend-row {
  display: grid;
  grid-template-columns: minmax(120px, 150px) minmax(0, 1fr) 44px 60px;
  align-items: center;
  gap: 12px;
}

.status-chart__bar-row + .status-chart__bar-row,
.status-chart__legend-row + .status-chart__legend-row {
  margin-top: 12px;
}

.status-chart__row-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.status-chart__row-label {
  min-width: 0;
  font-size: 13px;
  color: rgba(15, 23, 42, 0.84);
}

.status-chart__legend-dot {
  width: 10px;
  height: 10px;
  border-radius: 999px;
  flex-shrink: 0;
}

.status-chart__bar-track {
  position: relative;
  height: 12px;
  border-radius: 999px;
  background: rgba(148, 163, 184, 0.16);
  overflow: hidden;
}

.status-chart__bar-fill {
  height: 100%;
  border-radius: 999px;
}

.status-chart__row-value,
.status-chart__row-share {
  font-variant-numeric: tabular-nums;
  text-align: right;
}

.status-chart__row-value {
  font-size: 13px;
  font-weight: 600;
  color: rgba(15, 23, 42, 0.88);
}

.status-chart__row-share {
  font-size: 12px;
  color: rgba(15, 23, 42, 0.55);
}

.status-chart--donut {
  align-items: center;
}

.status-chart__donut-shell {
  display: flex;
  align-items: center;
  justify-content: center;
  min-width: 180px;
}

.status-chart__donut {
  position: relative;
  width: 168px;
  height: 168px;
  border-radius: 50%;
}

.status-chart__donut-hole {
  position: absolute;
  inset: 22px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
  background: rgba(255, 255, 255, 0.96);
  box-shadow: inset 0 0 0 1px rgba(148, 163, 184, 0.12);
}

.status-chart__donut-total {
  font-size: 28px;
  font-weight: 700;
  line-height: 1;
  color: rgba(15, 23, 42, 0.92);
}

.status-chart__donut-total-label {
  margin-top: 6px;
  font-size: 12px;
  color: rgba(15, 23, 42, 0.52);
}

.status-chart__legend {
  flex: 1;
}

.status-chart__legend-values {
  display: contents;
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
  flex: 0 0 auto;
  min-width: 36px;
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
  font-variant-numeric: tabular-nums;
  font-family: 'SF Mono', 'Monaco', 'Consolas', monospace;
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

.analytics-status-card__body {
  min-height: 320px;
  display: flex;
  flex-direction: column;
  justify-content: center;
}

.analytics-empty-state {
  min-height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  text-align: center;
  padding: 24px;
  border-radius: 18px;
  background: rgba(148, 163, 184, 0.08);
  border: 1px dashed rgba(148, 163, 184, 0.28);
}

.analytics-empty-state__title {
  max-width: 320px;
  font-size: 14px;
  line-height: 1.6;
  color: rgba(15, 23, 42, 0.6);
}

@media (max-width: 768px) {
  .analytics-page__controls {
    width: 100%;
  }

  .analytics-page__controls > * {
    width: 100%;
  }

  .trend-chart__label {
    writing-mode: horizontal-tb;
    transform: none;
    font-variant-numeric: tabular-nums;
    font-family: 'SF Mono', 'Monaco', 'Consolas', monospace;
  }

  .analytics-card__header,
  .analytics-card__header-actions,
  .analytics-card__header-actions--breakdown,
  .analytics-card__header-actions--status,
  .analytics-breakdown-tabs,
  .analytics-chart-toggle {
    width: 100%;
  }

  .analytics-card__header {
    align-items: flex-start;
    flex-direction: column;
  }

  .status-chart,
  .status-chart--donut {
    flex-direction: column;
  }

  .status-chart__bar-row,
  .status-chart__legend-row {
    grid-template-columns: minmax(0, 1fr);
    gap: 8px;
  }

  .status-chart__row-value,
  .status-chart__row-share {
    text-align: left;
  }

  .status-chart__legend-values {
    display: flex;
    gap: 12px;
  }

  .status-chart__donut-shell {
    min-width: 0;
  }
}
</style>
