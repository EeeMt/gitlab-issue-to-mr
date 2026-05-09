<template>
  <div class="schedule-overview">
    <n-spin :show="initialLoading" :description="t('scheduleOverview.loading')">
      <div class="page-hero">
        <PageHeader
          :title="t('scheduleOverview.title')"
          :subtitle="t('scheduleOverview.subtitle')"
        >
          <template #actions>
            <n-space align="center">
              <div class="schedule-toggle" role="tablist">
                <button
                  type="button"
                  class="schedule-toggle__button"
                  :class="{ 'schedule-toggle__button--active': !myTasksOnly }"
                  @click="myTasksOnly = false"
                >{{ t('common.all') }}</button>
                <button
                  type="button"
                  class="schedule-toggle__button"
                  :class="{ 'schedule-toggle__button--active': myTasksOnly }"
                  @click="myTasksOnly = true"
                >{{ t('scheduleOverview.myTasksOnly') }}</button>
              </div>
              <n-button @click="refresh" :loading="loading">
                {{ t('common.refresh') }}
              </n-button>
            </n-space>
          </template>
        </PageHeader>

        <n-grid :cols="isMobile ? 2 : 3" :x-gap="16" :y-gap="16">
          <n-gi v-for="item in summaryItems" :key="item.label">
            <SummaryCard
              :label="item.label"
              :value="item.value"
              :note="item.note"
              :icon="item.icon"
              :accent="item.accent"
            />
          </n-gi>
        </n-grid>
      </div>
      <n-space vertical :size="20">

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

            </div>
          </template>

          <HeatmapChart
            :tasks="scheduledTasks"
            :selected-ms="selectedWindow?.startMs ?? null"
            :max-per-slot="slotMaxTasks"
            :enforce-capacity="slotEnforce"
            :allow-full-selection="true"
            @cell-click="handleHeatmapCellClick"
          />
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
              <div class="slot-detail__meta-row">
                <div class="slot-detail__meta">
                  {{ t('scheduleOverview.slotTaskCount', { count: selectedWindowTasks.length }) }}
                </div>
                <span v-if="selectedWindowLoadLabel" class="schedule-chip schedule-chip--soft">
                  {{ selectedWindowLoadLabel }}
                </span>
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
                    {{ t('common.branch') }}: {{ task.issue?.branch_name || '-' }}
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
                      @update:value="() => onDraftChange(task.id)"
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
      </n-space>
    </n-spin>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import {
  NButton,
  NCard,
  NDatePicker,
  NGrid,
  NGi,
  NSpace,
  NSpin,
  NTag,
  useMessage,
} from 'naive-ui'
import { useWindowSize } from '@vueuse/core'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { authState, isAdmin, initializeAuth } from '../auth'
import { getScheduledTasks, getScheduledStats, rescheduleTask, getConfig, type Task, type ScheduledStatsResponse } from '../api'
import { formatDateTimeUtc8Compact, formatMonthDayTimeUtc8, formatTimeUtc8, parseUtcDate } from '../utils/datetime'
import { formatPriority, getProjectLabel as _getProjectLabel, isSameLocalDay } from '../utils/format'
import { extractSlotErrorMessage } from '../utils/slotError'
import PageHeader from '../components/PageHeader.vue'
import SummaryCard from '../components/SummaryCard.vue'
import HeatmapChart from '../components/HeatmapChart.vue'
import { CalendarOutline, TimeOutline, CheckmarkCircleOutline, BarChartOutline, FlameOutline } from '@vicons/ionicons5'

type HourBucket = {
  key: string
  label: string
  shortLabel: string
  count: number
  heightPercent: number
  startMs: number
}


type SelectedWindow = {
  key: string
  label: string
  startMs: number
  endMs: number
}

const message = useMessage()
const router = useRouter()
const { t } = useI18n()
const { width } = useWindowSize()
const isMobile = computed(() => width.value < 768)

const scheduledTasks = ref<Task[]>([])
const scheduledStats = ref<ScheduledStatsResponse | null>(null)
const loading = ref(false)
const hasLoadedOnce = ref(false)
const slotMaxTasks = ref(0)
const slotEnforce = ref(false)
const selectedWindow = ref<SelectedWindow | null>(null)
const scheduleDrafts = ref<Record<number, number | null>>({})
const dirtyDraftIds = ref<Set<number>>(new Set())
const savingTaskId = ref<number | null>(null)
let pollTimer: number | null = null

const canEditScheduleOverview = computed(() => !authState.oidcEnabled || isAdmin.value)
const myTasksOnly = ref(false)

function getProjectLabel(task: Task): string {
  return _getProjectLabel(task, t('dashboard.projectFallback', { id: task.project_id }))
}

function formatShortDateTime(value?: string | null): string {
  if (!value) return '-'
  return formatDateTimeUtc8Compact(value)
}

function getScheduledTimestamp(value?: string | null): number | null {
  if (!value) return null
  return parseUtcDate(value).getTime()
}

const initialLoading = computed(() => loading.value && !hasLoadedOnce.value)

const fullSlotCount = computed(() => {
  if (slotMaxTasks.value <= 0) return 0
  // Count full slots across 7-day range (matching the heatmap scope)
  const now = new Date()
  const utc8Offset = 8 * 60 * 60 * 1000
  const nowUtc8 = new Date(now.getTime() + utc8Offset)
  const startHour = new Date(Date.UTC(nowUtc8.getUTCFullYear(), nowUtc8.getUTCMonth(), nowUtc8.getUTCDate()) - utc8Offset)
  const endMs = startHour.getTime() + 7 * 24 * 60 * 60 * 1000

  const bucketCounts = new Map<number, number>()
  for (const task of scheduledTasks.value) {
    if (!task.scheduled_at) continue
    const ts = parseUtcDate(task.scheduled_at).getTime()
    if (ts < startHour.getTime() || ts >= endMs) continue
    const hourKey = Math.floor(ts / (60 * 60 * 1000))
    bucketCounts.set(hourKey, (bucketCounts.get(hourKey) ?? 0) + 1)
  }
  let count = 0
  for (const c of bucketCounts.values()) {
    if (c >= slotMaxTasks.value) count++
  }
  return count
})

const summaryItems = computed(() => {
  const s = scheduledStats.value?.summary
  if (!s) return []

  const baseItems = [
    { label: t('scheduleOverview.scheduledQueue'), value: String(s.total), note: t('scheduleOverview.activeScheduledTasks'), icon: CalendarOutline, accent: 'blue' as const },
    { label: t('scheduleOverview.readyNow'), value: String(s.ready_now), note: t('scheduleOverview.alreadyDue'), icon: CheckmarkCircleOutline, accent: 'green' as const },
    { label: t('scheduleOverview.upcoming24h'), value: String(s.next_24h), note: t('scheduleOverview.upcomingScheduledWork'), icon: TimeOutline, accent: 'amber' as const },
    { label: t('scheduleOverview.after24h'), value: String(s.later), note: t('scheduleOverview.laterBacklog'), icon: BarChartOutline, accent: 'purple' as const },
    {
      label: t('scheduleOverview.busiestHour'),
      value: s.busiest_hour_count > 0 ? String(s.busiest_hour_count) : '0',
      note: s.busiest_hour_count > 0 ? formatMonthDayTimeUtc8(parseUtcDate(s.busiest_hour_label)) : t('scheduleOverview.noScheduledWork'),
      icon: FlameOutline,
      accent: 'red' as const,
    },
  ]

  if (slotMaxTasks.value > 0) {
    baseItems.push({
      label: t('scheduleOverview.fullSlots'),
      value: String(fullSlotCount.value),
      note: fullSlotCount.value > 0
        ? t('scheduleOverview.fullSlotsNote', { capacity: slotMaxTasks.value })
        : t('scheduleOverview.noSlotsAtCapacity', { capacity: slotMaxTasks.value }),
      icon: CalendarOutline,
      accent: 'amber' as const,
    })
  }

  return baseItems
})

const hourlyBuckets = computed<HourBucket[]>(() => {
  const dist = scheduledStats.value?.hourly_distribution
  if (!dist || dist.length === 0) {
    // Fallback: generate empty 24 buckets
    const start = new Date()
    start.setMinutes(0, 0, 0)
    return Array.from({ length: 24 }, (_, index) => {
      const bucketStartMs = start.getTime() + index * 60 * 60 * 1000
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
  }

  const maxCount = scheduledStats.value?.max_count ?? 0
  return dist.map((bucket) => {
    const bucketDate = parseUtcDate(bucket.hour_start)
    const bucketStartMs = bucketDate.getTime()
    return {
      key: `${bucketStartMs}`,
      label: formatMonthDayTimeUtc8(bucketDate),
      shortLabel: formatTimeUtc8(bucketDate),
      count: bucket.count,
      heightPercent: maxCount > 0 ? (bucket.count > 0 ? Math.max((bucket.count / maxCount) * 100, 2) : 0) : 0,
      startMs: bucketStartMs,
    }
  })
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
  dirtyDraftIds.value.clear()
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

function handleHeatmapCellClick(startMs: number) {
  const endMs = startMs + 60 * 60 * 1000
  const label = formatMonthDayTimeUtc8(new Date(startMs))
  setSelectedWindow({
    key: `heatmap-${startMs}`,
    label,
    startMs,
    endMs,
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

  return scheduledTasks.value
    .filter((task) => isTaskInSelectedWindow(task, selectedWindow.value!))
    .sort((left, right) => {
      const leftMs = getScheduledTimestamp(left.scheduled_at) ?? 0
      const rightMs = getScheduledTimestamp(right.scheduled_at) ?? 0
      return leftMs - rightMs || right.priority - left.priority || left.id - right.id
    })
})

const selectedWindowLoadLabel = computed(() => {
  if (!selectedWindow.value || slotMaxTasks.value <= 0) {
    return null
  }

  return t('scheduleOverview.capacityLabel', {
    count: selectedWindowTasks.value.length,
    max: slotMaxTasks.value,
  })
})

function syncScheduleDrafts() {
  if (!selectedWindow.value) {
    scheduleDrafts.value = {}
    dirtyDraftIds.value.clear()
    return
  }

  const newDrafts: Record<number, number | null> = {}
  for (const task of selectedWindowTasks.value) {
    if (dirtyDraftIds.value.has(task.id)) {
      // Preserve user's unsaved change during auto-refresh
      newDrafts[task.id] = scheduleDrafts.value[task.id] ?? null
    } else {
      newDrafts[task.id] = task.scheduled_at ? parseUtcDate(task.scheduled_at).getTime() : null
    }
  }
  scheduleDrafts.value = newDrafts
}

function onDraftChange(taskId: number) {
  dirtyDraftIds.value.add(taskId)
}

function goToTask(task: Task) {
  router.push({ name: 'TaskView', params: { id: task.id } })
}

async function fetchData() {
  if (loading.value) return
  loading.value = true
  try {
    const my = myTasksOnly.value || undefined
    const [statsData, scheduledTaskData, config] = await Promise.all([
      getScheduledStats(my ? { my } : undefined),
      getScheduledTasks(my ? { my } : undefined),
      getConfig().catch(() => null),
    ])
    scheduledStats.value = statsData
    scheduledTasks.value = scheduledTaskData
    if (config) {
      slotMaxTasks.value = config.runtime?.slot_max_tasks ?? 0
      slotEnforce.value = config.runtime?.slot_max_tasks_enforce ?? false
    }
    if (selectedWindow.value) {
      syncScheduleDrafts()
    }
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
    await rescheduleTask(task.id, {
      scheduled_datetime: new Date(draft).toISOString()
    })
    clearSelectedWindow()
    await fetchData()
    message.success(t('scheduleOverview.taskRescheduled'))
  } catch (error: any) {
    message.error(extractSlotErrorMessage(error, t, 'scheduleOverview.failedToRescheduleTask'))
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

watch(myTasksOnly, () => {
  fetchData()
})

onBeforeUnmount(() => {
  if (pollTimer !== null) {
    clearInterval(pollTimer)
    pollTimer = null
  }
})
</script>

<style scoped>
.schedule-toggle {
  position: relative;
  display: inline-flex;
  align-items: center;
  padding: 4px;
  border-radius: 999px;
  background: rgba(148, 163, 184, 0.12);
  border: 1px solid rgba(148, 163, 184, 0.18);
}

.schedule-toggle__button {
  position: relative;
  z-index: 1;
  border: none;
  background: transparent;
  color: rgba(15, 23, 42, 0.62);
  padding: 5px 12px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  transition: background-color 0.22s ease, color 0.22s ease, box-shadow 0.22s ease, transform 0.22s ease;
}

.schedule-toggle__button:hover {
  color: rgba(15, 23, 42, 0.88);
}

.schedule-toggle__button--active {
  background: rgba(255, 255, 255, 0.92);
  color: rgba(15, 23, 42, 0.92);
  box-shadow: 0 1px 3px rgba(15, 23, 42, 0.12);
  transform: translateY(-1px);
}

.schedule-toggle__button:focus-visible {
  outline: none;
  box-shadow: 0 0 0 2px rgba(59, 130, 246, 0.18), 0 1px 3px rgba(15, 23, 42, 0.12);
}
.schedule-overview {
  max-width: 1240px;
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
  background: linear-gradient(180deg, rgba(24, 160, 88, 0.92), rgba(24, 160, 88, 0.82));
  color: rgba(255, 255, 255, 0.96);
  box-shadow:
    inset 0 0 0 1px rgba(255, 255, 255, 0.16),
    0 8px 18px -16px rgba(24, 160, 88, 0.56);
}

.schedule-chip--readonly {
  background: rgba(240, 160, 32, 0.12);
  color: rgba(163, 94, 12, 0.92);
}

.schedule-chip--soft {
  background: rgba(148, 163, 184, 0.14);
  color: rgba(15, 23, 42, 0.68);
}

.schedule-section-tip {
  margin-top: 12px;
  font-size: 12px;
  color: rgba(15, 23, 42, 0.58);
}

.hourly-chart {
  display: grid;
  grid-template-columns: repeat(24, minmax(0, 1fr));
  gap: 10px;
  align-items: stretch;
  min-height: 240px;
}

.hourly-chart__item {
  display: grid;
  grid-template-rows: 20px 148px 48px;
  justify-items: center;
  gap: 6px;
  min-width: 0;
}

.hourly-chart__item--clickable {
  cursor: pointer;
}

.hourly-chart__item--clickable:hover .hourly-chart__bar-wrap {
  background: rgba(148, 163, 184, 0.18);
  box-shadow: inset 0 0 0 1px rgba(148, 163, 184, 0.18);
}

.hourly-chart__item--active .hourly-chart__bar-wrap {
  background: rgba(148, 163, 184, 0.18);
  box-shadow:
    inset 0 0 0 1px rgba(32, 128, 240, 0.18),
    0 0 0 2px rgba(32, 128, 240, 0.12);
}

.hourly-chart__count {
  min-height: 20px;
  line-height: 20px;
  font-size: 12px;
  font-variant-numeric: tabular-nums;
  text-align: center;
  color: rgba(15, 23, 42, 0.64);
}

.hourly-chart__bar-wrap {
  width: min(100%, 26px);
  height: 148px;
  display: flex;
  align-items: end;
  justify-content: center;
  background: rgba(148, 163, 184, 0.12);
  border-radius: 10px;
  overflow: hidden;
  box-shadow: inset 0 0 0 1px rgba(148, 163, 184, 0.12);
  transition: background 0.18s ease, box-shadow 0.18s ease;
}

.hourly-chart__bar {
  width: 100%;
  min-height: 6px;
  border-radius: 10px 10px 0 0;
  background: linear-gradient(180deg, rgba(32, 128, 240, 0.92), rgba(32, 128, 240, 0.55));
}

.hourly-chart__label {
  display: flex;
  align-items: center;
  justify-content: center;
  inline-size: 100%;
  font-size: 11px;
  color: rgba(15, 23, 42, 0.58);
  font-family: 'SF Mono', 'Monaco', 'Consolas', monospace;
  font-variant-numeric: tabular-nums;
  writing-mode: vertical-rl;
  transform: rotate(180deg);
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

.slot-detail {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.slot-detail__summary {
  display: flex;
  flex-wrap: wrap;
  justify-content: space-between;
  align-items: flex-start;
  gap: 8px 16px;
}

.slot-detail__window {
  font-size: 16px;
  font-weight: 600;
}

.slot-detail__meta-row {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 8px;
  flex-wrap: wrap;
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
  .schedule-card__header {
    flex-direction: column;
    align-items: flex-start;
  }

  .hourly-chart {
    gap: 6px;
    overflow-x: auto;
    padding-bottom: 4px;
  }

  .window-insights {
    grid-template-columns: 1fr;
  }

  .slot-task-card {
    grid-template-columns: 1fr;
  }
}
</style>
