<template>
  <div class="schedule-overview">
    <n-spin :show="initialLoading" :description="t('scheduleOverview.loading')">
      <n-space vertical :size="20">
        <div class="schedule-overview__hero">
          <div>
            <h2 class="schedule-overview__title">{{ t('scheduleOverview.title') }}</h2>
            <p class="schedule-overview__subtitle">
              {{ t('scheduleOverview.subtitle') }}
            </p>
          </div>
          <n-space align="center" wrap class="schedule-overview__actions">
            <n-button @click="refresh" :loading="loading">
              {{ t('common.refresh') }}
            </n-button>
          </n-space>
        </div>

        <n-grid :cols="isMobile ? 2 : 3" :x-gap="16" :y-gap="16">
          <n-gi v-for="item in summaryItems" :key="item.label">
            <n-card size="small" class="schedule-summary-card" :bordered="false">
              <div class="schedule-summary-card__label">{{ item.label }}</div>
              <div class="schedule-summary-card__value">{{ item.value }}</div>
              <div v-if="item.note" class="schedule-summary-card__note">{{ item.note }}</div>
            </n-card>
          </n-gi>
        </n-grid>

        <n-grid class="schedule-overview__insights-grid" :cols="isMobile ? 1 : 2" :x-gap="16" :y-gap="16">
          <n-gi>
            <n-card class="schedule-card schedule-card--stretch" :bordered="false">
              <template #header>
                <div class="schedule-card__header">
                  <div>
                    <div class="schedule-card__title">{{ t('scheduleOverview.next24Hours') }}</div>
                    <div class="schedule-card__subtitle">{{ t('scheduleOverview.next24HoursSubtitle') }}</div>
                  </div>
                  <div class="schedule-card__hint">
                    <span class="schedule-chip schedule-chip--interactive">
                      {{ t('scheduleOverview.clickableHint') }}
                    </span>
                    <span v-if="selectedWindow" class="schedule-chip schedule-chip--active">
                      {{ t('scheduleOverview.selectedHint') }}
                    </span>
                  </div>
                </div>
              </template>

              <div v-if="hourlyBuckets.length" class="hourly-chart">
                <div
                  v-for="bucket in hourlyBuckets"
                  :key="bucket.key"
                  class="hourly-chart__item"
                  :class="{
                    'hourly-chart__item--clickable': bucket.count > 0,
                    'hourly-chart__item--active': isSelectedWindow(bucket.startMs, bucket.startMs + 60 * 60 * 1000)
                  }"
                  @click="handleHourlyBucketSelect(bucket)"
                >
                  <div class="hourly-chart__count">{{ bucket.count }}</div>
                  <div class="hourly-chart__bar-wrap">
                    <div
                      class="hourly-chart__bar"
                      :style="{ height: `${bucket.heightPercent}%` }"
                    />
                  </div>
                  <div class="hourly-chart__label">{{ bucket.shortLabel }}</div>
                </div>
              </div>
              <div class="schedule-section-tip">
                {{ t('scheduleOverview.chartTip') }}
              </div>
            </n-card>
          </n-gi>

          <n-gi>
            <n-card class="schedule-card schedule-card--stretch" :bordered="false">
              <template #header>
                <div class="schedule-card__header">
                  <div>
                    <div class="schedule-card__title">{{ t('scheduleOverview.busyIdleWindows') }}</div>
                    <div class="schedule-card__subtitle">{{ t('scheduleOverview.busyIdleWindowsSubtitle') }}</div>
                  </div>
                </div>
              </template>

              <div class="window-insights">
                <div class="window-insights__group">
                  <div class="window-insights__heading">{{ t('scheduleOverview.busiestSlots') }}</div>
                  <div v-if="busyWindows.length" class="window-insights__list">
                    <button
                      v-for="bucket in busyWindows"
                      :key="bucket.key"
                      type="button"
                      class="window-insights__item window-insights__item--button"
                      :class="{ 'window-insights__item--active': isSelectedWindow(bucket.startMs, bucket.startMs + 60 * 60 * 1000) }"
                      @click="handleHourlyBucketSelect(bucket)"
                    >
                      <span>{{ bucket.label }}</span>
                      <n-tag size="small" type="warning">{{ bucket.count }}</n-tag>
                    </button>
                  </div>
                  <div v-else class="window-insights__empty">{{ t('scheduleOverview.noScheduledWork24h') }}</div>
                </div>

                <div class="window-insights__group">
                  <div class="window-insights__heading">{{ t('scheduleOverview.idleSlots') }}</div>
                  <div v-if="idleWindows.length" class="window-insights__list">
                    <div v-for="bucket in idleWindows" :key="bucket.key" class="window-insights__item">
                      <span>{{ bucket.label }}</span>
                      <n-tag size="small">{{ t('scheduleOverview.idle') }}</n-tag>
                    </div>
                  </div>
                  <div v-else class="window-insights__empty">{{ t('scheduleOverview.everyHourBusy') }}</div>
                </div>
              </div>
            </n-card>
          </n-gi>
        </n-grid>

        <n-card class="schedule-card" :bordered="false">
          <template #header>
            <div class="schedule-card__header">
              <div>
                  <div class="schedule-card__title">{{ t('scheduleOverview.heatmap') }}</div>
                  <div class="schedule-card__subtitle">{{ t('scheduleOverview.heatmapSubtitle') }}</div>
              </div>
              <div class="heatmap-legend">
                <span class="heatmap-legend__label">{{ t('scheduleOverview.light') }}</span>
                <div class="heatmap-legend__scale">
                  <span class="heatmap-legend__swatch heatmap-legend__swatch--1"></span>
                  <span class="heatmap-legend__swatch heatmap-legend__swatch--2"></span>
                  <span class="heatmap-legend__swatch heatmap-legend__swatch--3"></span>
                  <span class="heatmap-legend__swatch heatmap-legend__swatch--4"></span>
                </div>
                <span class="heatmap-legend__label">{{ t('scheduleOverview.busy') }}</span>
                <span class="schedule-chip schedule-chip--interactive">
                  {{ t('scheduleOverview.clickableHint') }}
                </span>
              </div>
            </div>
          </template>

          <div class="heatmap">
            <div class="heatmap__header heatmap__header--spacer"></div>
            <div
              v-for="day in heatmapDays"
              :key="day.dateKey"
              class="heatmap__header"
            >
              {{ day.label }}
            </div>

            <template v-for="row in heatmapRows" :key="row.hour">
              <div class="heatmap__hour">{{ row.label }}</div>
                <div
                  v-for="cell in row.cells"
                  :key="cell.key"
                  class="heatmap__cell"
                  :class="{
                    'heatmap__cell--clickable': cell.count > 0,
                    'heatmap__cell--active': isSelectedWindow(cell.startMs, cell.endMs)
                  }"
                  :style="heatmapCellStyle(cell.count, heatmapMax)"
                  :title="t('scheduleOverview.taskCountTitle', { label: cell.label, count: cell.count })"
                  @click="handleHeatmapCellSelect(cell)"
                >
                  {{ cell.count > 0 ? cell.count : '' }}
                </div>
            </template>
          </div>
          <div class="schedule-section-tip">
            {{ t('scheduleOverview.heatmapTip') }}
          </div>
        </n-card>

        <n-card v-if="selectedWindow" class="schedule-card" :bordered="false">
          <template #header>
            <div class="schedule-card__header">
              <div>
                <div class="schedule-card__title">{{ t('scheduleOverview.selectedWindow') }}</div>
                <div class="schedule-card__subtitle">
                  {{ t('scheduleOverview.selectedWindowSubtitle') }}
                </div>
              </div>
              <div class="schedule-card__hint">
                <span class="schedule-chip schedule-chip--active">
                  {{ t('scheduleOverview.selectedHint') }}
                </span>
                <span v-if="!canEditScheduleOverview" class="schedule-chip schedule-chip--readonly">
                  {{ t('scheduleOverview.adminOnlyEditing') }}
                </span>
                <n-button quaternary @click="clearSelectedWindow">
                  {{ t('scheduleOverview.clearSelectedWindow') }}
                </n-button>
              </div>
            </div>
          </template>

          <div class="slot-detail">
            <div class="slot-detail__summary">
              <div class="slot-detail__window">{{ selectedWindow.label }}</div>
              <div class="slot-detail__meta">
                {{ t('scheduleOverview.slotTaskCount', { count: selectedWindowTasks.length }) }}
              </div>
            </div>

            <div v-if="!canEditScheduleOverview" class="slot-detail__notice">
              {{ t('scheduleOverview.adminOnlyEditingDescription') }}
            </div>

            <div v-if="selectedWindowTasks.length" class="slot-detail__list">
              <div
                v-for="task in selectedWindowTasks"
                :key="task.id"
                class="slot-task-card"
              >
                <div class="slot-task-card__main" @click="goToTask(task)">
                  <div class="slot-task-card__header">
                    <div class="slot-task-card__title">
                      #{{ task.id }} · {{ getProjectLabel(task) }}
                    </div>
                  </div>
                  <div class="slot-task-card__meta-row">
                    <div class="slot-task-card__badges">
                      <span class="slot-task-card__badge">{{ t(`status.${task.status}`) }}</span>
                      <span class="slot-task-card__badge">{{ formatPriority(task.priority) }}</span>
                    </div>
                  </div>
                  <div class="slot-task-card__time">
                    {{ t('scheduleOverview.currentSchedule') }}: {{ formatShortDateTime(task.scheduled_at) }}
                  </div>
                  <div class="slot-task-card__branch">
                    {{ t('common.branch') }}: {{ task.branch_name || '-' }}
                  </div>
                  <div class="slot-task-card__prompt">{{ task.user_prompt }}</div>
                </div>

                <div class="slot-task-card__actions">
                  <template v-if="canRescheduleTask(task) && canEditScheduleOverview">
                    <n-date-picker
                      v-model:value="scheduleDrafts[task.id]"
                      type="datetime"
                      class="slot-task-card__date-picker"
                      :placeholder="t('scheduleOverview.selectNewTime')"
                      :is-date-disabled="isScheduledDateDisabled"
                      :is-time-disabled="isScheduledTimeDisabled"
                    />
                    <n-button
                      type="info"
                      secondary
                      strong
                      round
                      class="slot-task-card__save-button"
                      @click.stop="handleTaskReschedule(task)"
                      :loading="savingTaskId === task.id"
                      :disabled="scheduleDrafts[task.id] === null || (savingTaskId !== null && savingTaskId !== task.id)"
                    >
                      {{ t('scheduleOverview.saveTime') }}
                    </n-button>
                  </template>
                  <div v-else class="slot-task-card__readonly">
                    {{
                      !canEditScheduleOverview
                        ? t('scheduleOverview.adminOnlyEditingDescription')
                        : t('scheduleOverview.onlyPendingTasksEditable')
                    }}
                  </div>
                </div>
              </div>
            </div>

            <div v-else class="slot-detail__empty">
              {{ t('scheduleOverview.noTasksInSelectedWindow') }}
            </div>
          </div>
        </n-card>

        <n-card class="schedule-card" :bordered="false">
          <template #header>
            <div class="schedule-card__header">
              <div>
                  <div class="schedule-card__title">{{ t('scheduleOverview.scheduledTasks') }}</div>
                  <div class="schedule-card__subtitle">{{ t('scheduleOverview.scheduledTasksSubtitle') }}</div>
              </div>
            </div>
          </template>

          <n-data-table
            :columns="columns"
            :data="tasks"
            :loading="tableLoading"
            :bordered="false"
            :row-key="(row: Task) => row.id"
            :row-props="getRowProps"
            :pagination="pagination"
            :scroll-x="isMobile ? undefined : 980"
          />
        </n-card>
      </n-space>
    </n-spin>
  </div>
</template>

<script setup lang="ts">
import { computed, h, onBeforeUnmount, onMounted, ref } from 'vue'
import {
  NButton,
  NCard,
  NDataTable,
  NDatePicker,
  NGrid,
  NGi,
  NSpace,
  NSpin,
  NTag,
  useMessage,
  type DataTableColumns,
} from 'naive-ui'
import { useWindowSize } from '@vueuse/core'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { authState, isAdmin, initializeAuth } from '../auth'
import { getScheduledTasks, rescheduleTask, type Task } from '../api'
import { formatDateTimeUtc8Compact, formatMonthDayTimeUtc8, formatMonthDayWeekdayUtc8, formatTimeUtc8, parseUtcDate } from '../utils/datetime'

type HourBucket = {
  key: string
  label: string
  shortLabel: string
  count: number
  heightPercent: number
  startMs: number
}

type HeatmapDay = {
  dateKey: string
  label: string
}

type HeatmapCell = {
  key: string
  label: string
  count: number
  startMs: number
  endMs: number
}

type SelectedWindow = {
  key: string
  label: string
  startMs: number
  endMs: number
}

type HeatmapRow = {
  hour: number
  label: string
  cells: HeatmapCell[]
}

const message = useMessage()
const router = useRouter()
const { t } = useI18n()
const { width } = useWindowSize()
const isMobile = computed(() => width.value < 768)

const tasks = ref<Task[]>([])
const loading = ref(false)
const hasLoadedOnce = ref(false)
const selectedWindow = ref<SelectedWindow | null>(null)
const scheduleDrafts = ref<Record<number, number | null>>({})
const savingTaskId = ref<number | null>(null)
let pollTimer: number | null = null

const pagination = {
  pageSize: 20,
  responsive: true,
}

const canEditScheduleOverview = computed(() => !authState.oidcEnabled || isAdmin.value)

const statusColors: Record<string, 'default' | 'info' | 'warning' | 'success' | 'error'> = {
  pending: 'default',
  queued: 'info',
  running: 'warning',
  completed: 'success',
  failed: 'error',
  cancelled: 'default',
}

const shanghaiPartsFormatter = new Intl.DateTimeFormat('en-CA', {
  timeZone: 'Asia/Shanghai',
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
  hour: '2-digit',
  hour12: false,
})

function getProjectLabel(task: Task): string {
  return task.project_path_with_namespace || task.project_name || t('dashboard.projectFallback', { id: task.project_id })
}

function getStatusTagType(status: string) {
  return statusColors[status] || 'default'
}

function formatPriority(priority?: string | number | null): string {
  if (priority === null || priority === undefined || priority === '') {
    return '-'
  }

  const normalized = String(priority).toLowerCase().trim()
  if (normalized === '0' || normalized === 'p0') return 'P0'
  if (normalized === '1' || normalized === 'p1') return 'P1'
  if (normalized === '2' || normalized === 'p2') return 'P2'
  return String(priority)
}

function formatShortDateTime(value?: string | null): string {
  if (!value) return '-'
  return formatDateTimeUtc8Compact(value)
}

function getScheduledTimestamp(value?: string | null): number | null {
  if (!value) return null
  return parseUtcDate(value).getTime()
}

function getShanghaiParts(date: Date): Record<string, string> {
  return shanghaiPartsFormatter.formatToParts(date).reduce<Record<string, string>>((acc, part) => {
    if (part.type !== 'literal') {
      acc[part.type] = part.value
    }
    return acc
  }, {})
}

function getShanghaiDateKey(date: Date): string {
  const parts = getShanghaiParts(date)
  return `${parts.year}-${parts.month}-${parts.day}`
}

function buildHeatmapDays(days: number): HeatmapDay[] {
  const nowParts = getShanghaiParts(new Date())
  const baseDate = new Date(
    Date.UTC(Number(nowParts.year), Number(nowParts.month) - 1, Number(nowParts.day))
  )

  return Array.from({ length: days }, (_, index) => {
    const date = new Date(baseDate.getTime() + index * 24 * 60 * 60 * 1000)
    const year = date.getUTCFullYear()
    const month = String(date.getUTCMonth() + 1).padStart(2, '0')
    const day = String(date.getUTCDate()).padStart(2, '0')
      return {
        dateKey: `${year}-${month}-${day}`,
        label: formatMonthDayWeekdayUtc8(date),
      }
    })
}

const initialLoading = computed(() => loading.value && !hasLoadedOnce.value)
const tableLoading = computed(() => loading.value && hasLoadedOnce.value)

const summaryItems = computed(() => {
  const now = Date.now()
  const next24Hours = now + 24 * 60 * 60 * 1000
  const readyNow = tasks.value.filter((task) => {
    const scheduledMs = getScheduledTimestamp(task.scheduled_at)
    if (scheduledMs === null) return false
    return scheduledMs <= now
  }).length
  const next24HoursCount = tasks.value.filter((task) => {
    const scheduledMs = getScheduledTimestamp(task.scheduled_at)
    if (scheduledMs === null) return false
    return scheduledMs > now && scheduledMs <= next24Hours
  }).length
  const laterCount = tasks.value.filter((task) => {
    const scheduledMs = getScheduledTimestamp(task.scheduled_at)
    if (scheduledMs === null) return false
    return scheduledMs > next24Hours
  }).length
  const queuedCount = tasks.value.filter((task) => task.status === 'queued').length
  const runningCount = tasks.value.filter((task) => task.status === 'running').length
  const busiest = [...hourlyBuckets.value].sort((left, right) => right.count - left.count)[0]

  return [
    { label: t('scheduleOverview.scheduledQueue'), value: String(tasks.value.length), note: t('scheduleOverview.activeScheduledTasks') },
    { label: t('scheduleOverview.readyNow'), value: String(readyNow), note: t('scheduleOverview.alreadyDue') },
    { label: t('scheduleOverview.upcoming24h'), value: String(next24HoursCount), note: t('scheduleOverview.upcomingScheduledWork') },
    { label: t('scheduleOverview.after24h'), value: String(laterCount), note: t('scheduleOverview.laterBacklog') },
    { label: t('scheduleOverview.queuedRunning'), value: `${queuedCount} / ${runningCount}`, note: t('scheduleOverview.executionStateSplit') },
    {
      label: t('scheduleOverview.busiestHour'),
      value: busiest && busiest.count > 0 ? String(busiest.count) : '0',
      note: busiest && busiest.count > 0 ? busiest.label : t('scheduleOverview.noScheduledWork'),
    },
  ]
})

const hourlyBuckets = computed<HourBucket[]>(() => {
  const start = new Date()
  start.setMinutes(0, 0, 0)
  const startMs = start.getTime()
  const buckets = Array.from({ length: 24 }, (_, index) => {
    const bucketStartMs = startMs + index * 60 * 60 * 1000
    const bucketDate = new Date(bucketStartMs)
      return {
        key: `${bucketStartMs}`,
        label: formatMonthDayTimeUtc8(bucketDate),
        shortLabel: formatTimeUtc8(bucketDate),
        count: 0,
        heightPercent: 0,
        startMs: bucketStartMs,
    }
  })

  tasks.value.forEach((task) => {
    const scheduledMs = getScheduledTimestamp(task.scheduled_at)
    if (scheduledMs === null) return
    if (scheduledMs < startMs || scheduledMs >= startMs + 24 * 60 * 60 * 1000) {
      return
    }

    const bucketIndex = Math.floor((scheduledMs - startMs) / (60 * 60 * 1000))
    if (bucketIndex >= 0 && bucketIndex < buckets.length) {
      buckets[bucketIndex].count += 1
    }
  })

  const maxCount = Math.max(...buckets.map((bucket) => bucket.count), 0)
  return buckets.map((bucket) => ({
    ...bucket,
    heightPercent: maxCount > 0 ? Math.max((bucket.count / maxCount) * 100, bucket.count > 0 ? 10 : 0) : 0,
  }))
})

const busyWindows = computed(() =>
  [...hourlyBuckets.value]
    .filter((bucket) => bucket.count > 0)
    .sort((left, right) => right.count - left.count || left.startMs - right.startMs)
    .slice(0, 5)
)

const idleWindows = computed(() =>
  hourlyBuckets.value
    .filter((bucket) => bucket.count === 0)
    .slice(0, 5)
)

const heatmapDays = computed(() => buildHeatmapDays(7))

const heatmapRows = computed<HeatmapRow[]>(() => {
  const dayKeys = heatmapDays.value.map((day) => day.dateKey)
  const counts = new Map<string, number>()

  tasks.value.forEach((task) => {
    if (!task.scheduled_at) return
    const scheduledDate = parseUtcDate(task.scheduled_at)
    const dateKey = getShanghaiDateKey(scheduledDate)
    if (!dayKeys.includes(dateKey)) return

    const parts = getShanghaiParts(scheduledDate)
    const hour = Number(parts.hour)
    const key = `${dateKey}-${hour}`
    counts.set(key, (counts.get(key) || 0) + 1)
  })

  return Array.from({ length: 24 }, (_, hour) => ({
    hour,
    label: `${String(hour).padStart(2, '0')}:00`,
    cells: heatmapDays.value.map((day) => {
      const key = `${day.dateKey}-${hour}`
      const startMs = new Date(`${day.dateKey}T${String(hour).padStart(2, '0')}:00:00+08:00`).getTime()
      return {
        key,
        label: `${day.label} ${String(hour).padStart(2, '0')}:00`,
        count: counts.get(key) || 0,
        startMs,
        endMs: startMs + 60 * 60 * 1000,
      }
    }),
  }))
})

const heatmapMax = computed(() =>
  heatmapRows.value.reduce((max, row) => {
    return Math.max(max, ...row.cells.map((cell) => cell.count))
  }, 0)
)

function heatmapCellStyle(count: number, maxCount: number) {
  if (count === 0 || maxCount === 0) {
    return {
      background: 'rgba(148, 163, 184, 0.12)',
      color: 'rgba(15, 23, 42, 0.45)',
    }
  }

  const intensity = count / maxCount
  const alpha = 0.18 + intensity * 0.52
  return {
    background: `rgba(32, 128, 240, ${alpha.toFixed(3)})`,
    color: intensity > 0.58 ? '#fff' : '#0f172a',
  }
}

function isSameLocalDay(left: Date, right: Date): boolean {
  return (
    left.getFullYear() === right.getFullYear()
    && left.getMonth() === right.getMonth()
    && left.getDate() === right.getDate()
  )
}

function isScheduledDateDisabled(timestamp: number): boolean {
  const candidate = new Date(timestamp)
  const today = new Date()

  candidate.setHours(0, 0, 0, 0)
  today.setHours(0, 0, 0, 0)

  return candidate.getTime() < today.getTime()
}

function isScheduledTimeDisabled(timestamp: number) {
  const selectedDate = new Date(timestamp)
  const now = new Date()

  if (!isSameLocalDay(selectedDate, now)) {
    return {}
  }

  const currentHour = now.getHours()
  const currentMinute = now.getMinutes()
  const currentSecond = now.getSeconds()

  return {
    isHourDisabled: (hour: number) => hour < currentHour,
    isMinuteDisabled: (minute: number, hour: number | null) => (
      hour !== null
      && hour === currentHour
      && minute < currentMinute
    ),
    isSecondDisabled: (second: number, minute: number | null, hour: number | null) => (
      hour !== null
      && minute !== null
      && hour === currentHour
      && minute === currentMinute
      && second < currentSecond
    )
  }
}

function setSelectedWindow(nextWindow: SelectedWindow) {
  selectedWindow.value = nextWindow
  syncScheduleDrafts()
}

function clearSelectedWindow() {
  selectedWindow.value = null
  scheduleDrafts.value = {}
}

function isSelectedWindow(startMs: number, endMs: number): boolean {
  return (
    selectedWindow.value?.startMs === startMs
    && selectedWindow.value?.endMs === endMs
  )
}

function handleHourlyBucketSelect(bucket: HourBucket) {
  if (bucket.count === 0) return
  setSelectedWindow({
    key: `hour-${bucket.startMs}`,
    label: bucket.label,
    startMs: bucket.startMs,
    endMs: bucket.startMs + 60 * 60 * 1000,
  })
}

function handleHeatmapCellSelect(cell: HeatmapCell) {
  if (cell.count === 0) return
  setSelectedWindow({
    key: cell.key,
    label: cell.label,
    startMs: cell.startMs,
    endMs: cell.endMs,
  })
}

function canRescheduleTask(task: Task): boolean {
  return task.status === 'pending' && !!task.scheduled_at
}

function isTaskInSelectedWindow(task: Task, window: SelectedWindow): boolean {
  const scheduledMs = getScheduledTimestamp(task.scheduled_at)
  if (scheduledMs === null) return false
  return scheduledMs >= window.startMs && scheduledMs < window.endMs
}

const selectedWindowTasks = computed(() => {
  if (!selectedWindow.value) return []

  return tasks.value
    .filter((task) => isTaskInSelectedWindow(task, selectedWindow.value!))
    .sort((left, right) => {
      const leftMs = getScheduledTimestamp(left.scheduled_at) ?? 0
      const rightMs = getScheduledTimestamp(right.scheduled_at) ?? 0
      return leftMs - rightMs || right.priority - left.priority || left.id - right.id
    })
})

function syncScheduleDrafts() {
  if (!selectedWindow.value) {
    scheduleDrafts.value = {}
    return
  }

  scheduleDrafts.value = Object.fromEntries(
    selectedWindowTasks.value.map((task) => [
      task.id,
      task.scheduled_at ? parseUtcDate(task.scheduled_at).getTime() : null,
    ])
  )
}

function goToTask(task: Task) {
  router.push({ name: 'TaskView', params: { id: task.id } })
}

function isInteractiveTarget(target: EventTarget | null): boolean {
  if (!(target instanceof Element)) {
    return false
  }

  return Boolean(target.closest('a, button, input, textarea, select, summary, [role="button"], .n-button, .n-base-selection'))
}

function getRowProps(row: Task) {
  return {
    style: 'cursor: pointer;',
    onClick: (event: MouseEvent) => {
      if (isInteractiveTarget(event.target)) {
        return
      }
      goToTask(row)
    },
  }
}

const columns = computed<DataTableColumns<Task>>(() => {
  const mobileColumns: DataTableColumns<Task> = [
    {
      title: t('scheduleOverview.task'),
      key: 'task',
      render: (row) =>
        h('div', { style: 'line-height: 1.45' }, [
          h('div', { style: 'font-weight: 600;' }, `#${row.id} · ${getProjectLabel(row)}`),
          h('div', { style: 'font-size: 12px; color: rgba(15, 23, 42, 0.58);' }, formatShortDateTime(row.scheduled_at)),
        ]),
    },
    {
      title: t('common.status'),
      key: 'status',
      width: 92,
      render: (row) => h(NTag, { size: 'small', type: getStatusTagType(row.status) }, () => t(`status.${row.status}`)),
    },
  ]

  const desktopColumns: DataTableColumns<Task> = [
    { title: t('scheduleOverview.id'), key: 'id', width: 64 },
    {
      title: t('common.project'),
      key: 'project',
      width: 180,
      ellipsis: { tooltip: true },
      render: (row) => getProjectLabel(row),
    },
    {
      title: t('common.status'),
      key: 'status',
      width: 96,
      render: (row) => h(NTag, { size: 'small', type: getStatusTagType(row.status) }, () => t(`status.${row.status}`)),
    },
    {
      title: t('common.priority'),
      key: 'priority',
      width: 72,
      render: (row) => formatPriority(row.priority),
    },
    {
      title: t('common.scheduled'),
      key: 'scheduled_at',
      width: 150,
      render: (row) => formatShortDateTime(row.scheduled_at),
    },
    {
      title: t('common.branch'),
      key: 'branch_name',
      width: 150,
      ellipsis: { tooltip: true },
      render: (row) => row.branch_name || '-',
    },
    {
      title: t('scheduleOverview.prompt'),
      key: 'user_prompt',
      width: 320,
      render: (row) => h('div', { class: 'schedule-table__ellipsis', title: row.user_prompt }, row.user_prompt),
    },
  ]

  return isMobile.value ? mobileColumns : desktopColumns
})

async function fetchData() {
  if (loading.value) return
  loading.value = true
  try {
    tasks.value = await getScheduledTasks()
    syncScheduleDrafts()
    hasLoadedOnce.value = true
  } catch (error) {
    message.error(t('scheduleOverview.failedToFetch'))
  } finally {
    hasLoadedOnce.value = true
    loading.value = false
  }
}

function refresh() {
  fetchData()
}

async function handleTaskReschedule(task: Task) {
  const draft = scheduleDrafts.value[task.id]

  if (!draft) {
    message.error(t('scheduleOverview.selectNewTime'))
    return
  }

  if (draft <= Date.now()) {
    message.error(t('scheduleOverview.rescheduleTimeFuture'))
    return
  }

  savingTaskId.value = task.id
  try {
    const updatedTask = await rescheduleTask(task.id, {
      scheduled_datetime: new Date(draft).toISOString()
    })
    tasks.value = tasks.value.map((item) => (item.id === updatedTask.id ? updatedTask : item))
    clearSelectedWindow()
    message.success(t('scheduleOverview.taskRescheduled'))
  } catch (error) {
    message.error(t('scheduleOverview.failedToRescheduleTask'))
  } finally {
    savingTaskId.value = null
  }
}

onMounted(() => {
  void initializeAuth()
  fetchData()
  pollTimer = window.setInterval(() => {
    if (document.visibilityState !== 'visible') return
    fetchData()
  }, 15000)
})

onBeforeUnmount(() => {
  if (pollTimer !== null) {
    clearInterval(pollTimer)
    pollTimer = null
  }
})
</script>

<style scoped>
.schedule-overview {
  max-width: 1240px;
}

.schedule-overview__hero {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 16px;
  flex-wrap: wrap;
}

.schedule-overview__title {
  margin: 0;
  font-size: 28px;
  line-height: 1.2;
}

.schedule-overview__subtitle {
  margin: 8px 0 0;
  color: rgba(15, 23, 42, 0.68);
  max-width: 780px;
}

.schedule-overview__actions {
  justify-content: flex-end;
}

.schedule-summary-card {
  border-radius: 12px;
  background: linear-gradient(180deg, rgba(32, 128, 240, 0.06), rgba(32, 128, 240, 0.02));
}

.schedule-summary-card__label {
  margin-bottom: 8px;
  font-size: 12px;
  color: rgba(15, 23, 42, 0.6);
}

.schedule-summary-card__value {
  font-size: 22px;
  font-weight: 600;
  color: var(--n-text-color-1);
}

.schedule-summary-card__note {
  margin-top: 6px;
  font-size: 12px;
  color: rgba(15, 23, 42, 0.58);
}

.schedule-card {
  border-radius: 18px;
}

.schedule-overview__insights-grid {
  align-items: stretch;
}

.schedule-overview__insights-grid :deep(.n-grid-item) {
  display: flex;
}

.schedule-card--stretch {
  width: 100%;
  height: 100%;
}

.schedule-card--stretch :deep(.n-card__content) {
  height: 100%;
}

.schedule-card__header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 12px;
  flex-wrap: wrap;
}

.schedule-card__title {
  font-size: 18px;
  font-weight: 600;
}

.schedule-card__subtitle {
  margin-top: 4px;
  font-size: 13px;
  color: rgba(15, 23, 42, 0.58);
}

.schedule-card__hint {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.schedule-chip {
  display: inline-flex;
  align-items: center;
  padding: 6px 10px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 600;
}

.schedule-chip--interactive {
  background: rgba(32, 128, 240, 0.1);
  color: rgba(32, 128, 240, 0.95);
}

.schedule-chip--active {
  background: rgba(24, 160, 88, 0.12);
  color: rgba(24, 160, 88, 0.95);
}

.schedule-chip--readonly {
  background: rgba(240, 160, 32, 0.12);
  color: rgba(163, 94, 12, 0.92);
}

.schedule-section-tip {
  margin-top: 12px;
  font-size: 12px;
  color: rgba(15, 23, 42, 0.58);
}

.schedule-table__ellipsis {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.hourly-chart {
  display: grid;
  grid-template-columns: repeat(24, minmax(0, 1fr));
  gap: 8px;
  align-items: end;
  min-height: 240px;
}

.hourly-chart__item {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
  min-width: 0;
}

.hourly-chart__item--clickable {
  cursor: pointer;
}

.hourly-chart__item--clickable:hover .hourly-chart__bar-wrap {
  background: rgba(32, 128, 240, 0.14);
}

.hourly-chart__item--active .hourly-chart__bar-wrap {
  outline: 2px solid rgba(32, 128, 240, 0.45);
  outline-offset: 2px;
  background: rgba(32, 128, 240, 0.16);
}

.hourly-chart__count {
  min-height: 20px;
  font-size: 12px;
  color: rgba(15, 23, 42, 0.64);
}

.hourly-chart__bar-wrap {
  width: 100%;
  height: 148px;
  display: flex;
  align-items: flex-end;
  justify-content: center;
  background: rgba(148, 163, 184, 0.08);
  border-radius: 999px;
  overflow: hidden;
}

.hourly-chart__bar {
  width: 100%;
  min-height: 0;
  border-radius: 999px;
  background: linear-gradient(180deg, rgba(32, 128, 240, 0.95), rgba(54, 173, 106, 0.78));
}

.hourly-chart__label {
  font-size: 11px;
  color: rgba(15, 23, 42, 0.58);
  writing-mode: vertical-rl;
  text-orientation: mixed;
}

.window-insights {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 18px;
}

.window-insights__group {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.window-insights__heading {
  font-size: 14px;
  font-weight: 600;
}

.window-insights__list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.window-insights__item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  padding: 10px 12px;
  border-radius: 12px;
  background: rgba(148, 163, 184, 0.08);
  font-size: 13px;
}

.window-insights__item--button {
  width: 100%;
  border: 0;
  text-align: left;
  cursor: pointer;
}

.window-insights__item--active {
  background: rgba(32, 128, 240, 0.12);
  box-shadow: inset 0 0 0 1px rgba(32, 128, 240, 0.22);
}

.window-insights__empty {
  font-size: 13px;
  color: rgba(15, 23, 42, 0.58);
}

.heatmap-legend {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 12px;
  color: rgba(15, 23, 42, 0.58);
}

.heatmap-legend__scale {
  display: flex;
  gap: 6px;
}

.heatmap-legend__swatch {
  width: 16px;
  height: 10px;
  border-radius: 999px;
}

.heatmap-legend__swatch--1 { background: rgba(32, 128, 240, 0.2); }
.heatmap-legend__swatch--2 { background: rgba(32, 128, 240, 0.34); }
.heatmap-legend__swatch--3 { background: rgba(32, 128, 240, 0.5); }
.heatmap-legend__swatch--4 { background: rgba(32, 128, 240, 0.68); }

.heatmap {
  display: grid;
  grid-template-columns: 64px repeat(7, minmax(0, 1fr));
  gap: 8px;
  align-items: center;
}

.heatmap__header {
  text-align: center;
  font-size: 12px;
  color: rgba(15, 23, 42, 0.64);
}

.heatmap__header--spacer {
  visibility: hidden;
}

.heatmap__hour {
  font-size: 12px;
  color: rgba(15, 23, 42, 0.58);
}

.heatmap__cell {
  min-height: 30px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
  font-weight: 600;
}

.heatmap__cell--clickable {
  cursor: pointer;
}

.heatmap__cell--clickable:not(.heatmap__cell--active):hover {
  transform: translateY(-1px);
  box-shadow: inset 0 0 0 1px rgba(32, 128, 240, 0.22);
}

.heatmap__cell--active {
  box-shadow: inset 0 0 0 2px rgba(15, 23, 42, 0.32), 0 0 0 2px rgba(24, 160, 88, 0.16);
}

.heatmap__cell--active:hover {
  transform: none;
  box-shadow: inset 0 0 0 2px rgba(15, 23, 42, 0.32), 0 0 0 2px rgba(24, 160, 88, 0.16);
}

.slot-detail {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.slot-detail__summary {
  display: flex;
  flex-wrap: wrap;
  justify-content: space-between;
  gap: 8px 16px;
}

.slot-detail__window {
  font-size: 16px;
  font-weight: 600;
}

.slot-detail__meta,
.slot-detail__empty,
.slot-detail__notice,
.slot-task-card__time,
.slot-task-card__branch,
.slot-task-card__readonly {
  font-size: 13px;
  color: rgba(15, 23, 42, 0.6);
}

.slot-detail__notice {
  padding: 12px 14px;
  border-radius: 12px;
  background: rgba(240, 160, 32, 0.08);
  color: rgba(163, 94, 12, 0.92);
}

.slot-detail__list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.slot-task-card {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(280px, 320px);
  gap: 16px;
  padding: 14px 16px;
  border-radius: 14px;
  background: rgba(148, 163, 184, 0.08);
}

.slot-task-card__main {
  min-width: 0;
  cursor: pointer;
}

.slot-task-card__header {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: flex-start;
  flex-wrap: wrap;
}

.slot-task-card__title {
  font-size: 14px;
  font-weight: 600;
}

.slot-task-card__meta-row {
  margin-top: 8px;
}

.slot-task-card__badges {
  display: inline-flex;
  gap: 8px;
  flex-wrap: wrap;
}

.slot-task-card__badge {
  display: inline-flex;
  align-items: center;
  padding: 4px 9px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 500;
  color: rgba(15, 23, 42, 0.72);
  background: rgba(148, 163, 184, 0.14);
}

.slot-task-card__time,
.slot-task-card__branch {
  margin-top: 6px;
}

.slot-task-card__prompt {
  margin-top: 10px;
  font-size: 13px;
  color: var(--n-text-color-2);
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.slot-task-card__actions {
  display: flex;
  flex-direction: column;
  gap: 10px;
  justify-self: start;
  width: max-content;
  max-width: 100%;
}

.slot-task-card__date-picker {
  width: 100%;
}

.slot-task-card__save-button {
  width: 100%;
}

@media (max-width: 768px) {
  .schedule-overview__hero,
  .schedule-card__header {
    flex-direction: column;
    align-items: flex-start;
  }

  .schedule-overview__actions {
    width: 100%;
    justify-content: flex-start;
  }

  .schedule-overview__title {
    font-size: 24px;
  }

  .hourly-chart {
    gap: 6px;
    overflow-x: auto;
    padding-bottom: 4px;
  }

  .window-insights {
    grid-template-columns: 1fr;
  }

  .heatmap {
    grid-template-columns: 54px repeat(7, minmax(44px, 1fr));
    gap: 6px;
    overflow-x: auto;
  }

  .heatmap__cell {
    min-height: 28px;
    font-size: 11px;
  }

  .slot-task-card {
    grid-template-columns: 1fr;
  }
}
</style>
