<template>
  <div class="schedule-overview">
    <n-spin :show="initialLoading" description="Loading schedule overview...">
      <n-space vertical :size="20">
        <div class="schedule-overview__hero">
          <div>
            <h2 class="schedule-overview__title">Schedule Overview</h2>
            <p class="schedule-overview__subtitle">
              Review active scheduled tasks, understand hourly load, and spot busy versus idle time windows.
            </p>
          </div>
          <n-space align="center" wrap>
            <n-select
              v-model:value="statusFilter"
              :options="statusOptions"
              placeholder="Status"
              clearable
              style="width: 140px"
            />
            <n-input
              v-model:value="searchTerm"
              placeholder="Search project, branch, prompt"
              clearable
              style="width: min(280px, 60vw)"
            />
            <n-button @click="refresh" :loading="loading">
              Refresh
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

        <n-grid :cols="isMobile ? 1 : 2" :x-gap="16" :y-gap="16">
          <n-gi>
            <n-card class="schedule-card" :bordered="false">
              <template #header>
                <div class="schedule-card__header">
                  <div>
                    <div class="schedule-card__title">Next 24 Hours</div>
                    <div class="schedule-card__subtitle">Scheduled task count per hour in UTC+8</div>
                  </div>
                </div>
              </template>

              <div v-if="hourlyBuckets.length" class="hourly-chart">
                <div
                  v-for="bucket in hourlyBuckets"
                  :key="bucket.key"
                  class="hourly-chart__item"
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
            </n-card>
          </n-gi>

          <n-gi>
            <n-card class="schedule-card" :bordered="false">
              <template #header>
                <div class="schedule-card__header">
                  <div>
                    <div class="schedule-card__title">Busy & Idle Windows</div>
                    <div class="schedule-card__subtitle">Quick read of the next 24 hours</div>
                  </div>
                </div>
              </template>

              <div class="window-insights">
                <div class="window-insights__group">
                  <div class="window-insights__heading">Busiest slots</div>
                  <div v-if="busyWindows.length" class="window-insights__list">
                    <div v-for="bucket in busyWindows" :key="bucket.key" class="window-insights__item">
                      <span>{{ bucket.label }}</span>
                      <n-tag size="small" type="warning">{{ bucket.count }}</n-tag>
                    </div>
                  </div>
                  <div v-else class="window-insights__empty">No scheduled work in the next 24 hours.</div>
                </div>

                <div class="window-insights__group">
                  <div class="window-insights__heading">Idle slots</div>
                  <div v-if="idleWindows.length" class="window-insights__list">
                    <div v-for="bucket in idleWindows" :key="bucket.key" class="window-insights__item">
                      <span>{{ bucket.label }}</span>
                      <n-tag size="small">Idle</n-tag>
                    </div>
                  </div>
                  <div v-else class="window-insights__empty">Every upcoming hour already has scheduled work.</div>
                </div>
              </div>
            </n-card>
          </n-gi>
        </n-grid>

        <n-card class="schedule-card" :bordered="false">
          <template #header>
            <div class="schedule-card__header">
              <div>
                <div class="schedule-card__title">7-Day Heatmap</div>
                <div class="schedule-card__subtitle">Darker cells indicate heavier scheduled load (UTC+8)</div>
              </div>
              <div class="heatmap-legend">
                <span class="heatmap-legend__label">Light</span>
                <div class="heatmap-legend__scale">
                  <span class="heatmap-legend__swatch heatmap-legend__swatch--1"></span>
                  <span class="heatmap-legend__swatch heatmap-legend__swatch--2"></span>
                  <span class="heatmap-legend__swatch heatmap-legend__swatch--3"></span>
                  <span class="heatmap-legend__swatch heatmap-legend__swatch--4"></span>
                </div>
                <span class="heatmap-legend__label">Busy</span>
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
                :style="heatmapCellStyle(cell.count, heatmapMax)"
                :title="`${cell.label}: ${cell.count} task(s)`"
              >
                {{ cell.count > 0 ? cell.count : '' }}
              </div>
            </template>
          </div>
        </n-card>

        <n-card class="schedule-card" :bordered="false">
          <template #header>
            <div class="schedule-card__header">
              <div>
                <div class="schedule-card__title">Scheduled Tasks</div>
                <div class="schedule-card__subtitle">Active scheduled tasks only: pending, queued, and running</div>
              </div>
            </div>
          </template>

          <n-data-table
            :columns="columns"
            :data="filteredTasks"
            :loading="loading"
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
  NGrid,
  NGi,
  NInput,
  NSelect,
  NSpace,
  NSpin,
  NTag,
  useMessage,
  type DataTableColumns,
} from 'naive-ui'
import { useWindowSize } from '@vueuse/core'
import { useRouter } from 'vue-router'
import { getScheduledTasks, type Task } from '../api'
import { formatDateTimeUtc8, parseUtcDate } from '../utils/datetime'

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
}

type HeatmapRow = {
  hour: number
  label: string
  cells: HeatmapCell[]
}

const message = useMessage()
const router = useRouter()
const { width } = useWindowSize()
const isMobile = computed(() => width.value < 768)

const tasks = ref<Task[]>([])
const loading = ref(false)
const hasLoadedOnce = ref(false)
const statusFilter = ref<string | null>(null)
const searchTerm = ref('')
let pollTimer: number | null = null

const pagination = {
  pageSize: 20,
  responsive: true,
}

const statusOptions = [
  { label: 'Pending', value: 'pending' },
  { label: 'Queued', value: 'queued' },
  { label: 'Running', value: 'running' },
]

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

const shanghaiDayLabelFormatter = new Intl.DateTimeFormat('zh-CN', {
  timeZone: 'Asia/Shanghai',
  month: '2-digit',
  day: '2-digit',
  weekday: 'short',
})

function getProjectLabel(task: Task): string {
  return task.project_path_with_namespace || task.project_name || `Project #${task.project_id}`
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
  return formatDateTimeUtc8(value).slice(0, 16)
}

function getScheduledTimestamp(value?: string | null): number | null {
  if (!value) return null
  return parseUtcDate(value).getTime()
}

function getSearchHaystack(task: Task): string {
  return [
    task.id,
    task.status,
    getProjectLabel(task),
    task.branch_name,
    task.user_prompt,
  ]
    .filter(Boolean)
    .join(' ')
    .toLowerCase()
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
      label: shanghaiDayLabelFormatter.format(date),
    }
  })
}

const filteredTasks = computed(() => {
  const query = searchTerm.value.trim().toLowerCase()

  return tasks.value.filter((task) => {
    if (statusFilter.value && task.status !== statusFilter.value) {
      return false
    }

    if (!query) {
      return true
    }

    return getSearchHaystack(task).includes(query)
  })
})

const initialLoading = computed(() => loading.value && !hasLoadedOnce.value)

const summaryItems = computed(() => {
  const now = Date.now()
  const next24Hours = now + 24 * 60 * 60 * 1000
  const readyNow = filteredTasks.value.filter((task) => {
    const scheduledMs = getScheduledTimestamp(task.scheduled_at)
    if (scheduledMs === null) return false
    return scheduledMs <= now
  }).length
  const next24HoursCount = filteredTasks.value.filter((task) => {
    const scheduledMs = getScheduledTimestamp(task.scheduled_at)
    if (scheduledMs === null) return false
    return scheduledMs > now && scheduledMs <= next24Hours
  }).length
  const laterCount = filteredTasks.value.filter((task) => {
    const scheduledMs = getScheduledTimestamp(task.scheduled_at)
    if (scheduledMs === null) return false
    return scheduledMs > next24Hours
  }).length
  const queuedCount = filteredTasks.value.filter((task) => task.status === 'queued').length
  const runningCount = filteredTasks.value.filter((task) => task.status === 'running').length
  const busiest = [...hourlyBuckets.value].sort((left, right) => right.count - left.count)[0]

  return [
    { label: 'Scheduled Queue', value: String(filteredTasks.value.length), note: 'Active scheduled tasks' },
    { label: 'Ready Now', value: String(readyNow), note: 'Already due to run' },
    { label: 'Next 24 Hours', value: String(next24HoursCount), note: 'Upcoming scheduled work' },
    { label: 'After 24 Hours', value: String(laterCount), note: 'Later backlog' },
    { label: 'Queued / Running', value: `${queuedCount} / ${runningCount}`, note: 'Execution state split' },
    {
      label: 'Busiest Hour',
      value: busiest && busiest.count > 0 ? String(busiest.count) : '0',
      note: busiest && busiest.count > 0 ? busiest.label : 'No scheduled work',
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
      label: formatDateTimeUtc8(bucketDate).slice(5, 16),
      shortLabel: formatDateTimeUtc8(bucketDate).slice(11, 16),
      count: 0,
      heightPercent: 0,
      startMs: bucketStartMs,
    }
  })

  filteredTasks.value.forEach((task) => {
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

  filteredTasks.value.forEach((task) => {
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
      return {
        key,
        label: `${day.label} ${String(hour).padStart(2, '0')}:00`,
        count: counts.get(key) || 0,
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

const mobileColumns: DataTableColumns<Task> = [
  {
    title: 'Task',
    key: 'task',
    render: (row) =>
      h('div', { style: 'line-height: 1.45' }, [
        h('div', { style: 'font-weight: 600;' }, `#${row.id} · ${getProjectLabel(row)}`),
        h('div', { style: 'font-size: 12px; color: rgba(15, 23, 42, 0.58);' }, formatShortDateTime(row.scheduled_at)),
      ]),
  },
  {
    title: 'Status',
    key: 'status',
    width: 92,
    render: (row) => h(NTag, { size: 'small', type: getStatusTagType(row.status) }, () => row.status),
  },
]

const desktopColumns: DataTableColumns<Task> = [
  {
    title: 'ID',
    key: 'id',
    width: 64,
  },
  {
    title: 'Project',
    key: 'project',
    width: 180,
    ellipsis: { tooltip: true },
    render: (row) => getProjectLabel(row),
  },
  {
    title: 'Status',
    key: 'status',
    width: 96,
    render: (row) => h(NTag, { size: 'small', type: getStatusTagType(row.status) }, () => row.status),
  },
  {
    title: 'Priority',
    key: 'priority',
    width: 72,
    render: (row) => formatPriority(row.priority),
  },
  {
    title: 'Scheduled',
    key: 'scheduled_at',
    width: 150,
    render: (row) => formatShortDateTime(row.scheduled_at),
  },
  {
    title: 'Branch',
    key: 'branch_name',
    width: 150,
    ellipsis: { tooltip: true },
    render: (row) => row.branch_name || '-',
  },
  {
    title: 'Prompt',
    key: 'user_prompt',
    width: 320,
    render: (row) => h('div', { class: 'schedule-table__ellipsis', title: row.user_prompt }, row.user_prompt),
  },
]

const columns = computed(() => (isMobile.value ? mobileColumns : desktopColumns))

async function fetchData() {
  if (loading.value) return
  loading.value = true
  try {
    tasks.value = await getScheduledTasks()
    hasLoadedOnce.value = true
  } catch (error) {
    message.error('Failed to fetch scheduled tasks')
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
  gap: 8px;
  min-width: 0;
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

@media (max-width: 768px) {
  .schedule-overview__hero,
  .schedule-card__header {
    flex-direction: column;
    align-items: flex-start;
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
}
</style>
