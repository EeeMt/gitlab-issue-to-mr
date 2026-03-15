<template>
  <div class="monitor-page">
    <n-spin :show="initialLoading">
      <template #description>{{ t('monitor.loading') }}</template>

      <n-space vertical :size="16">
        <section class="monitor-page__hero">
          <div>
            <h1>{{ t('monitor.title') }}</h1>
            <p>{{ t('monitor.subtitle') }}</p>
          </div>

          <n-button secondary :loading="loading && hasLoadedOnce" @click="fetchData()">
            {{ t('common.refresh') }}
          </n-button>
        </section>

        <n-alert type="info" :show-icon="false">
          {{ t('monitor.dataSourceInfo') }}
        </n-alert>

        <n-grid :x-gap="16" :y-gap="16" cols="1 s:2 l:4" responsive="screen">
          <n-gi v-for="item in overviewCards" :key="item.key">
            <n-card size="small" class="monitor-summary-card">
              <div class="summary-label">{{ item.label }}</div>
              <div class="summary-value-row">
                <div class="summary-value">{{ item.value }}</div>
                <n-tag size="small" :type="item.tagType" round>{{ item.tag }}</n-tag>
              </div>
              <p class="summary-help">{{ item.help }}</p>
            </n-card>
          </n-gi>
        </n-grid>

        <n-tabs v-model:value="activeTab" type="line" animated class="monitor-tabs">
          <n-tab-pane name="runtime" :tab="t('monitor.runtimeTab')">
            <n-space vertical :size="16">
              <n-grid :x-gap="16" :y-gap="16" cols="1 s:2 l:4" responsive="screen">
                <n-gi v-for="item in runtimeCards" :key="item.key">
                  <n-card size="small" class="monitor-summary-card">
                    <div class="summary-label">{{ item.label }}</div>
                    <div class="summary-value">{{ item.value }}</div>
                    <p class="summary-help">{{ item.help }}</p>
                  </n-card>
                </n-gi>
              </n-grid>

              <n-card class="monitor-card" :title="t('monitor.activeTasksTitle')">
                <template #header-extra>
                  <span class="card-caption">{{ t('monitor.activeTasksSubtitle') }}</span>
                </template>

                <n-empty v-if="!tableLoading && activeTasks.length === 0" :description="t('monitor.noActiveTasks')" />
                <n-data-table
                  v-else
                  :columns="activeTaskColumns"
                  :data="activeTasks"
                  :loading="tableLoading"
                  :pagination="false"
                  :row-props="activeTaskRowProps"
                  size="small"
                  scroll-x="960"
                />
              </n-card>

              <n-card class="monitor-card" :title="t('monitor.recentActivityTitle')">
                <template #header-extra>
                  <span class="card-caption">{{ t('monitor.recentActivitySubtitle') }}</span>
                </template>

                <n-empty v-if="!tableLoading && recentFinishedTasks.length === 0" :description="t('monitor.noRecentActivity')" />
                <n-data-table
                  v-else
                  :columns="recentActivityColumns"
                  :data="recentFinishedTasks"
                  :loading="tableLoading"
                  :pagination="false"
                  :row-props="recentActivityRowProps"
                  size="small"
                  scroll-x="980"
                />
              </n-card>
            </n-space>
          </n-tab-pane>

          <n-tab-pane name="debug" :tab="t('monitor.debugTab')">
            <n-space vertical :size="16">
              <n-grid :x-gap="16" :y-gap="16" cols="1 s:2 l:4" responsive="screen">
                <n-gi v-for="item in debugCards" :key="item.key">
                  <n-card size="small" class="monitor-summary-card">
                    <div class="summary-label">{{ item.label }}</div>
                    <div class="summary-value">{{ item.value }}</div>
                    <p class="summary-help">{{ item.help }}</p>
                  </n-card>
                </n-gi>
              </n-grid>

              <n-grid :x-gap="16" :y-gap="16" cols="1 l:2" responsive="screen">
                <n-gi>
                  <n-card class="monitor-card" :title="t('monitor.runningTasksWithoutContainerTitle')">
                    <div v-if="runningTasksWithoutContainer.length > 0" class="issue-list">
                      <button
                        v-for="task in runningTasksWithoutContainer"
                        :key="task.id"
                        class="issue-item issue-item--button"
                        type="button"
                        @click="goToTask(task.id)"
                      >
                        <div class="issue-title">#{{ task.id }} · {{ getProjectLabel(task) }}</div>
                        <div class="issue-meta">
                          {{ formatPromptPreview(task.user_prompt) }}
                        </div>
                      </button>
                    </div>
                    <n-empty v-else :description="t('monitor.noRunningTaskGaps')" />
                  </n-card>
                </n-gi>

                <n-gi>
                  <n-card class="monitor-card" :title="t('monitor.orphanContainersTitle')">
                    <div v-if="orphanContainers.length > 0" class="issue-list">
                      <div v-for="container in orphanContainers" :key="container.id" class="issue-item">
                        <div class="issue-title">{{ container.name }}</div>
                        <div class="issue-meta">
                          {{ t('monitor.containerRelation') }}: {{ getContainerRelation(container).label }}
                        </div>
                      </div>
                    </div>
                    <n-empty v-else :description="t('monitor.noOrphanContainers')" />
                  </n-card>
                </n-gi>
              </n-grid>

              <n-card class="monitor-card" :title="t('monitor.containersTitle')">
                <template #header-extra>
                  <span class="card-caption">{{ t('monitor.containersSubtitle') }}</span>
                </template>

                <n-empty v-if="!tableLoading && sortedContainers.length === 0" :description="t('monitor.noContainers')" />
                <n-data-table
                  v-else
                  :columns="containerColumns"
                  :data="sortedContainers"
                  :loading="tableLoading"
                  :pagination="false"
                  :row-props="containerRowProps"
                  size="small"
                  scroll-x="1080"
                />
              </n-card>
            </n-space>
          </n-tab-pane>

          <n-tab-pane name="health" :tab="t('monitor.healthTab')">
            <n-space vertical :size="16">
              <n-grid :x-gap="16" :y-gap="16" cols="1 l:2" responsive="screen">
                <n-gi>
                  <n-card class="monitor-card" :title="t('monitor.healthChecksTitle')">
                    <div class="health-checks">
                      <div v-for="check in healthChecks" :key="check.key" class="health-check">
                        <div>
                          <div class="health-check__title">{{ check.label }}</div>
                          <div class="health-check__detail">{{ check.detail }}</div>
                        </div>
                        <n-tag :type="check.type" round>{{ check.badge }}</n-tag>
                      </div>
                    </div>
                  </n-card>
                </n-gi>

                <n-gi>
                  <n-card class="monitor-card" :title="t('monitor.statusBreakdownTitle')">
                    <div class="status-breakdown">
                      <div v-for="item in statusBreakdown" :key="item.key" class="status-breakdown__row">
                        <div class="status-breakdown__label">
                          <span>{{ item.label }}</span>
                          <span>{{ item.value }}</span>
                        </div>
                        <div class="status-breakdown__track">
                          <div class="status-breakdown__fill" :style="{ width: `${item.percent}%` }"></div>
                        </div>
                      </div>
                    </div>
                  </n-card>
                </n-gi>
              </n-grid>

              <n-card class="monitor-card" :title="t('monitor.recentFailuresTitle')">
                <template #header-extra>
                  <span class="card-caption">{{ t('monitor.recentFailuresSubtitle') }}</span>
                </template>

                <n-empty v-if="!tableLoading && recentFailures.length === 0" :description="t('monitor.noRecentFailures')" />
                <n-data-table
                  v-else
                  :columns="recentFailureColumns"
                  :data="recentFailures"
                  :loading="tableLoading"
                  :pagination="false"
                  :row-props="recentFailureRowProps"
                  size="small"
                  scroll-x="980"
                />
              </n-card>
            </n-space>
          </n-tab-pane>
        </n-tabs>
      </n-space>
    </n-spin>
  </div>
</template>

<script setup lang="ts">
import { computed, h, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import {
  NAlert,
  NButton,
  NCard,
  NDataTable,
  NEmpty,
  NGi,
  NGrid,
  NSpace,
  NSpin,
  NTabPane,
  NTabs,
  NTag,
  type DataTableColumns,
  useMessage
} from 'naive-ui'
import { useI18n } from 'vue-i18n'
import { getContainers, getStats, getTasks, type Container, type Stats, type Task } from '../api'
import { formatDateTimeUtc8Compact, parseUtcDate } from '../utils/datetime'

type CardTagType = 'default' | 'info' | 'success' | 'warning' | 'error'
type CheckType = 'default' | 'info' | 'success' | 'warning' | 'error'

type MonitorCard = {
  key: string
  label: string
  value: string
  help: string
  tag?: string
  tagType?: CardTagType
}

type HealthCheck = {
  key: string
  label: string
  detail: string
  badge: string
  type: CheckType
}

const ACTIVE_STATUSES = ['pending', 'queued', 'running']
const FINISHED_STATUSES = ['completed', 'failed', 'cancelled']

const router = useRouter()
const message = useMessage()
const { t } = useI18n()

const loading = ref(false)
const hasLoadedOnce = ref(false)
const activeTab = ref('runtime')
const refreshRequestInFlight = ref(false)
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
const tasks = ref<Task[]>([])
let pendingSilentRefresh = false
let pendingVisibleRefresh = false
let refreshTimer: number | null = null

const initialLoading = computed(() => loading.value && !hasLoadedOnce.value)
const tableLoading = computed(() => loading.value && hasLoadedOnce.value)

const tasksById = computed(() => new Map(tasks.value.map((task) => [task.id, task])))

const activeTasks = computed(() =>
  tasks.value.filter((task) => ACTIVE_STATUSES.includes(task.status))
)

const runningTasks = computed(() =>
  activeTasks.value.filter((task) => task.status === 'running')
)

const pendingQueuedTasks = computed(() =>
  activeTasks.value.filter((task) => task.status === 'pending' || task.status === 'queued')
)

const runningContainers = computed(() =>
  containers.value.filter((container) => container.status === 'running')
)

const linkedRunningContainers = computed(() =>
  runningContainers.value.filter((container) => {
    const task = container.task_id ? tasksById.value.get(container.task_id) : undefined
    return task?.status === 'running'
  })
)

const runningTasksWithoutContainer = computed(() =>
  runningTasks.value.filter((task) => {
    return !runningContainers.value.some(
      (container) => container.task_id === task.id || container.id === task.container_id
    )
  })
)

const orphanContainers = computed(() =>
  runningContainers.value.filter((container) => {
    if (!container.task_id) {
      return true
    }

    const task = tasksById.value.get(container.task_id)
    return !task || task.status !== 'running'
  })
)

const recentFinishedTasks = computed(() =>
  tasks.value
    .filter((task) => FINISHED_STATUSES.includes(task.status))
    .slice(0, 10)
)

const recentFailures = computed(() =>
  tasks.value
    .filter((task) => task.status === 'failed' || task.status === 'cancelled')
    .slice(0, 10)
)

const recentFinishedCount24h = computed(() =>
  recentTasksInHours(24).filter((task) => task.status === 'completed').length
)

const recentFailureCount24h = computed(() =>
  recentTasksInHours(24).filter((task) => task.status === 'failed' || task.status === 'cancelled').length
)

const longRunningTasks = computed(() =>
  runningTasks.value.filter((task) => {
    if (!task.started_at) return false
    return Date.now() - parseUtcDate(task.started_at).getTime() > 30 * 60 * 1000
  })
)

const sortedContainers = computed(() =>
  [...containers.value].sort((left, right) => {
    if (left.status === 'running' && right.status !== 'running') return -1
    if (left.status !== 'running' && right.status === 'running') return 1
    return parseTimestamp(right.created_at) - parseTimestamp(left.created_at)
  })
)

const statusBreakdown = computed(() => {
  const total = Math.max(stats.value.total, 1)

  return [
    { key: 'pending', label: t('monitor.pending'), value: stats.value.pending, percent: (stats.value.pending / total) * 100 },
    { key: 'queued', label: t('monitor.queued'), value: stats.value.queued, percent: (stats.value.queued / total) * 100 },
    { key: 'running', label: t('monitor.running'), value: stats.value.running, percent: (stats.value.running / total) * 100 },
    { key: 'completed', label: t('monitor.completed'), value: stats.value.completed, percent: (stats.value.completed / total) * 100 },
    { key: 'failed', label: t('monitor.failed'), value: stats.value.failed, percent: (stats.value.failed / total) * 100 },
    { key: 'cancelled', label: t('monitor.cancelled'), value: stats.value.cancelled, percent: (stats.value.cancelled / total) * 100 }
  ]
})

const healthChecks = computed<HealthCheck[]>(() => {
  const backlog = pendingQueuedTasks.value.length
  const running = runningTasks.value.length
  const missingContainers = runningTasksWithoutContainer.value.length
  const orphaned = orphanContainers.value.length
  const failures24h = recentFailureCount24h.value

  return [
    {
      key: 'queue',
      label: t('monitor.queueHealthLabel'),
      detail:
        backlog > Math.max(6, running * 2)
          ? t('monitor.queueHealthHighDetail', { backlog })
          : t('monitor.queueHealthNormalDetail', { backlog }),
      badge: backlog > Math.max(6, running * 2) ? t('monitor.attention') : t('monitor.healthy'),
      type: backlog > Math.max(6, running * 2) ? 'warning' : 'success'
    },
    {
      key: 'workers',
      label: t('monitor.workerHealthLabel'),
      detail:
        missingContainers > 0 || orphaned > 0
          ? t('monitor.workerHealthMismatchDetail', { missing: missingContainers, orphaned })
          : t('monitor.workerHealthAlignedDetail'),
      badge: missingContainers > 0 || orphaned > 0 ? t('monitor.needsReview') : t('monitor.aligned'),
      type: missingContainers > 0 || orphaned > 0 ? 'warning' : 'success'
    },
    {
      key: 'failures',
      label: t('monitor.failureHealthLabel'),
      detail:
        failures24h > 0
          ? t('monitor.failureHealthDetail', { count: failures24h })
          : t('monitor.failureHealthCleanDetail'),
      badge: failures24h > 2 ? t('monitor.risky') : failures24h > 0 ? t('monitor.watch') : t('monitor.stable'),
      type: failures24h > 2 ? 'error' : failures24h > 0 ? 'warning' : 'success'
    },
    {
      key: 'runtime',
      label: t('monitor.runtimeHealthLabel'),
      detail:
        longRunningTasks.value.length > 0
          ? t('monitor.runtimeHealthSlowDetail', { count: longRunningTasks.value.length })
          : t('monitor.runtimeHealthNormalDetail'),
      badge: longRunningTasks.value.length > 0 ? t('monitor.slow') : t('monitor.normal'),
      type: longRunningTasks.value.length > 0 ? 'warning' : 'success'
    }
  ]
})

const healthSummary = computed(() => {
  const types = healthChecks.value.map((check) => check.type)
  if (types.includes('error')) {
    return {
      label: t('monitor.healthNeedsAttention'),
      tag: t('monitor.risky'),
      tagType: 'error' as CardTagType
    }
  }
  if (types.includes('warning')) {
    return {
      label: t('monitor.healthWatch'),
      tag: t('monitor.watch'),
      tagType: 'warning' as CardTagType
    }
  }
  return {
    label: t('monitor.healthHealthy'),
    tag: t('monitor.healthy'),
    tagType: 'success' as CardTagType
  }
})

const overviewCards = computed<MonitorCard[]>(() => [
  {
    key: 'running',
    label: t('monitor.runningNowLabel'),
    value: String(runningTasks.value.length),
    help: t('monitor.runningNowHelp', { containers: runningContainers.value.length }),
    tag: t('monitor.live'),
    tagType: runningTasks.value.length > 0 ? 'warning' : 'default'
  },
  {
    key: 'backlog',
    label: t('monitor.backlogLabel'),
    value: String(pendingQueuedTasks.value.length),
    help: t('monitor.backlogHelp', { pending: stats.value.pending, queued: stats.value.queued }),
    tag: pendingQueuedTasks.value.length > 0 ? t('monitor.queued') : t('monitor.clear'),
    tagType: pendingQueuedTasks.value.length > 6 ? 'warning' : 'info'
  },
  {
    key: 'containers',
    label: t('monitor.activeContainersLabel'),
    value: String(runningContainers.value.length),
    help: t('monitor.activeContainersHelp', { linked: linkedRunningContainers.value.length }),
    tag: runningTasksWithoutContainer.value.length > 0 ? t('monitor.gaps') : t('monitor.aligned'),
    tagType: runningTasksWithoutContainer.value.length > 0 ? 'warning' : 'success'
  },
  {
    key: 'health',
    label: t('monitor.healthSummaryLabel'),
    value: healthSummary.value.label,
    help: t('monitor.healthSummaryHelp'),
    tag: healthSummary.value.tag,
    tagType: healthSummary.value.tagType
  }
])

const runtimeCards = computed<MonitorCard[]>(() => [
  {
    key: 'active',
    label: t('monitor.activeTasksMetric'),
    value: String(activeTasks.value.length),
    help: t('monitor.activeTasksMetricHelp')
  },
  {
    key: 'completed24h',
    label: t('monitor.completed24hMetric'),
    value: String(recentFinishedCount24h.value),
    help: t('monitor.completed24hMetricHelp')
  },
  {
    key: 'failures24h',
    label: t('monitor.failures24hMetric'),
    value: String(recentFailureCount24h.value),
    help: t('monitor.failures24hMetricHelp')
  },
  {
    key: 'longRunning',
    label: t('monitor.longRunningMetric'),
    value: String(longRunningTasks.value.length),
    help: t('monitor.longRunningMetricHelp')
  }
])

const debugCards = computed<MonitorCard[]>(() => [
  {
    key: 'visible',
    label: t('monitor.visibleContainersMetric'),
    value: String(containers.value.length),
    help: t('monitor.visibleContainersMetricHelp')
  },
  {
    key: 'linked',
    label: t('monitor.linkedContainersMetric'),
    value: String(linkedRunningContainers.value.length),
    help: t('monitor.linkedContainersMetricHelp')
  },
  {
    key: 'missing',
    label: t('monitor.missingContainersMetric'),
    value: String(runningTasksWithoutContainer.value.length),
    help: t('monitor.missingContainersMetricHelp')
  },
  {
    key: 'orphaned',
    label: t('monitor.orphanContainersMetric'),
    value: String(orphanContainers.value.length),
    help: t('monitor.orphanContainersMetricHelp')
  }
])

const activeTaskColumns = computed<DataTableColumns<Task>>(() => [
  {
    title: t('monitor.taskId'),
    key: 'id',
    width: 84,
    render: (task) => renderTaskLink(task)
  },
  {
    title: t('common.project'),
    key: 'project',
    minWidth: 180,
    render: (task) => getProjectLabel(task)
  },
  {
    title: t('monitor.task'),
    key: 'task',
    minWidth: 240,
    render: (task) => formatPromptPreview(task.user_prompt)
  },
  {
    title: t('monitor.status'),
    key: 'status',
    width: 110,
    render: (task) => renderStatusTag(task.status)
  },
  {
    title: t('common.priority'),
    key: 'priority',
    width: 90,
    render: (task) => formatPriority(task.priority)
  },
  {
    title: t('monitor.waitingOrRunning'),
    key: 'elapsed',
    width: 140,
    render: (task) => getTaskElapsedLabel(task)
  },
  {
    title: t('common.createdAt'),
    key: 'created_at',
    width: 160,
    render: (task) => formatTimestamp(task.created_at)
  }
])

const recentActivityColumns = computed<DataTableColumns<Task>>(() => [
  {
    title: t('monitor.taskId'),
    key: 'id',
    width: 84,
    render: (task) => renderTaskLink(task)
  },
  {
    title: t('common.project'),
    key: 'project',
    minWidth: 180,
    render: (task) => getProjectLabel(task)
  },
  {
    title: t('monitor.status'),
    key: 'status',
    width: 110,
    render: (task) => renderStatusTag(task.status)
  },
  {
    title: t('monitor.duration'),
    key: 'duration',
    width: 132,
    render: (task) => getExecutionDuration(task)
  },
  {
    title: t('monitor.finishedAt'),
    key: 'completed_at',
    width: 160,
    render: (task) => formatTimestamp(task.completed_at || task.updated_at)
  },
  {
    title: t('monitor.summary'),
    key: 'summary',
    minWidth: 260,
    render: (task) => task.status === 'completed' ? formatPromptPreview(task.user_prompt) : summarizeError(task.error_message)
  }
])

const recentFailureColumns = computed<DataTableColumns<Task>>(() => [
  {
    title: t('monitor.taskId'),
    key: 'id',
    width: 84,
    render: (task) => renderTaskLink(task)
  },
  {
    title: t('common.project'),
    key: 'project',
    minWidth: 180,
    render: (task) => getProjectLabel(task)
  },
  {
    title: t('monitor.status'),
    key: 'status',
    width: 110,
    render: (task) => renderStatusTag(task.status)
  },
  {
    title: t('monitor.finishedAt'),
    key: 'completed_at',
    width: 160,
    render: (task) => formatTimestamp(task.completed_at || task.updated_at)
  },
  {
    title: t('monitor.failureReason'),
    key: 'error_message',
    minWidth: 340,
    render: (task) => summarizeError(task.error_message)
  }
])

const containerColumns = computed<DataTableColumns<Container>>(() => [
  {
    title: t('monitor.containerId'),
    key: 'id',
    width: 138,
    render: (container) => container.id.slice(0, 12)
  },
  {
    title: t('monitor.name'),
    key: 'name',
    minWidth: 180
  },
  {
    title: t('monitor.status'),
    key: 'status',
    width: 110,
    render: (container) => renderContainerStatusTag(container.status)
  },
  {
    title: t('monitor.task'),
    key: 'task_id',
    minWidth: 200,
    render: (container) => {
      if (!container.task_id) {
        return t('monitor.unmappedContainer')
      }

      const task = tasksById.value.get(container.task_id)
      if (!task) {
        return `#${container.task_id} · ${t('monitor.taskNotInSample')}`
      }

      return h(
        NButton,
        {
          text: true,
          type: 'primary',
          onClick: (event: MouseEvent) => {
            event.stopPropagation()
            goToTask(task.id)
          }
        },
        { default: () => `#${task.id} · ${getProjectLabel(task)}` }
      )
    }
  },
  {
    title: t('monitor.containerRelation'),
    key: 'relation',
    minWidth: 180,
    render: (container) => {
      const relation = getContainerRelation(container)
      return h(NTag, { type: relation.type, round: true }, { default: () => relation.label })
    }
  },
  {
    title: t('monitor.age'),
    key: 'created_at',
    width: 150,
    render: (container) => formatAge(container.created_at)
  },
  {
    title: t('common.createdAt'),
    key: 'created_at_display',
    width: 160,
    render: (container) => formatTimestamp(container.created_at)
  }
])

function recentTasksInHours(hours: number): Task[] {
  const cutoff = Date.now() - hours * 60 * 60 * 1000
  return tasks.value.filter((task) => parseTimestamp(task.created_at) >= cutoff)
}

function parseTimestamp(value?: string | null): number {
  if (!value) return 0
  const parsed = parseUtcDate(value).getTime()
  return Number.isNaN(parsed) ? 0 : parsed
}

function formatTimestamp(value?: string | null): string {
  return value ? formatDateTimeUtc8Compact(value) : '-'
}

function formatPromptPreview(prompt?: string | null): string {
  if (!prompt) return '-'
  return prompt.replace(/\s+/g, ' ').trim().slice(0, 96)
}

function summarizeError(error?: string | null): string {
  if (!error) return t('monitor.noErrorMessage')
  const firstLine = error.split('\n').find((line) => line.trim())
  return (firstLine || error).trim().slice(0, 140)
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

function formatDuration(milliseconds: number): string {
  if (milliseconds <= 0) return '-'

  const totalMinutes = Math.floor(milliseconds / 60000)
  const hours = Math.floor(totalMinutes / 60)
  const minutes = totalMinutes % 60

  if (hours > 0) {
    return `${hours}h ${minutes}m`
  }
  if (minutes > 0) {
    return `${minutes}m`
  }
  return '<1m'
}

function formatAge(value?: string | null): string {
  if (!value) return '-'
  return formatDuration(Date.now() - parseTimestamp(value))
}

function getExecutionDuration(task: Task): string {
  if (!task.started_at || !task.completed_at) return '-'
  return formatDuration(parseTimestamp(task.completed_at) - parseTimestamp(task.started_at))
}

function getTaskElapsedLabel(task: Task): string {
  if (task.started_at && task.status === 'running') {
    return `${t('monitor.runningForPrefix')} ${formatAge(task.started_at)}`
  }
  return `${t('monitor.waitingForPrefix')} ${formatAge(task.created_at)}`
}

function getProjectLabel(task: Task): string {
  return task.project_path_with_namespace || task.project_name || t('dashboard.projectFallback', { id: task.project_id })
}

function getContainerRelation(container: Container): { label: string; type: CardTagType } {
  if (!container.task_id) {
    return { label: t('monitor.unmapped'), type: 'default' }
  }

  const task = tasksById.value.get(container.task_id)
  if (!task) {
    return { label: t('monitor.taskMissing'), type: 'warning' }
  }

  if (container.status === 'running' && task.status === 'running') {
    return { label: t('monitor.linked'), type: 'success' }
  }

  if (container.status === 'running' && task.status !== 'running') {
    return { label: t('monitor.outlivedTask'), type: 'warning' }
  }

  if (container.status !== 'running' && task.status === 'running') {
    return { label: t('monitor.taskStillMarkedRunning'), type: 'warning' }
  }

  return { label: t('monitor.historical'), type: 'info' }
}

function renderStatusTag(status?: string | null) {
  const type: CardTagType =
    status === 'completed'
      ? 'success'
      : status === 'failed'
        ? 'error'
        : status === 'running'
          ? 'warning'
          : status === 'queued'
            ? 'info'
            : 'default'

  return h(
    NTag,
    { type, round: true },
    { default: () => status ? t(`monitor.${status}`) : '-' }
  )
}

function renderContainerStatusTag(status?: string | null) {
  const normalized = status?.toLowerCase()
  const type: CardTagType = normalized === 'running' ? 'success' : normalized === 'exited' ? 'default' : 'info'
  return h(NTag, { type, round: true }, { default: () => status || '-' })
}

function renderTaskLink(task: Task) {
  return h(
    NButton,
    {
      text: true,
      type: 'primary',
      onClick: (event: MouseEvent) => {
        event.stopPropagation()
        goToTask(task.id)
      }
    },
    { default: () => `#${task.id}` }
  )
}

function activeTaskRowProps(task: Task) {
  return {
    style: 'cursor: pointer;',
    onClick: () => goToTask(task.id)
  }
}

function recentActivityRowProps(task: Task) {
  return {
    style: 'cursor: pointer;',
    onClick: () => goToTask(task.id)
  }
}

function recentFailureRowProps(task: Task) {
  return {
    style: 'cursor: pointer;',
    onClick: () => goToTask(task.id)
  }
}

function containerRowProps(container: Container) {
  if (!container.task_id || !tasksById.value.has(container.task_id)) {
    return {}
  }

  return {
    style: 'cursor: pointer;',
    onClick: () => goToTask(container.task_id!)
  }
}

function goToTask(taskId: number) {
  router.push(`/tasks/${taskId}`)
}

async function fetchData(options: { silent?: boolean } = {}) {
  const silent = options.silent ?? false

  if (refreshRequestInFlight.value) {
    if (silent) {
      pendingSilentRefresh = true
    } else {
      pendingVisibleRefresh = true
    }
    return
  }

  refreshRequestInFlight.value = true
  if (!silent) {
    loading.value = true
  }

  try {
    const [statsData, containersData, tasksData] = await Promise.all([
      getStats(),
      getContainers(),
      getTasks()
    ])

    stats.value = statsData
    containers.value = containersData
    tasks.value = tasksData
    hasLoadedOnce.value = true
  } catch (error) {
    console.error(error)
    message.error(t('monitor.failedToFetchData'))
  } finally {
    if (!silent) {
      loading.value = false
    }
    refreshRequestInFlight.value = false

    if (pendingVisibleRefresh || pendingSilentRefresh) {
      const nextSilent = !pendingVisibleRefresh
      pendingVisibleRefresh = false
      pendingSilentRefresh = false
      await fetchData({ silent: nextSilent })
    }
  }
}

function startAutoRefresh() {
  stopAutoRefresh()
  refreshTimer = window.setInterval(() => {
    void fetchData({ silent: true })
  }, 15000)
}

function stopAutoRefresh() {
  if (refreshTimer !== null) {
    window.clearInterval(refreshTimer)
    refreshTimer = null
  }
}

onMounted(async () => {
  await fetchData()
  startAutoRefresh()
})

onBeforeUnmount(() => {
  stopAutoRefresh()
})
</script>

<style scoped>
.monitor-page__hero {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 16px;
}

.monitor-page__hero h1 {
  margin: 0;
  font-size: 28px;
  font-weight: 700;
}

.monitor-page__hero p {
  margin: 8px 0 0;
  color: rgba(15, 23, 42, 0.68);
  max-width: 760px;
  line-height: 1.6;
}

.monitor-summary-card :deep(.n-card__content),
.monitor-card :deep(.n-card__content) {
  padding-top: 16px;
  padding-bottom: 16px;
}

.summary-label {
  font-size: 12px;
  font-weight: 600;
  color: rgba(15, 23, 42, 0.56);
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

.summary-value-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  margin-top: 10px;
}

.summary-value {
  margin-top: 10px;
  font-size: 28px;
  font-weight: 700;
  color: #0f172a;
  line-height: 1.15;
}

.summary-help {
  margin: 10px 0 0;
  color: rgba(15, 23, 42, 0.68);
  line-height: 1.5;
  min-height: 42px;
}

.card-caption {
  color: rgba(15, 23, 42, 0.56);
  font-size: 13px;
}

.issue-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.issue-item {
  padding: 12px 14px;
  border: 1px solid rgba(15, 23, 42, 0.08);
  border-radius: 14px;
  background: rgba(248, 250, 252, 0.92);
}

.issue-item--button {
  width: 100%;
  text-align: left;
  cursor: pointer;
}

.issue-title {
  font-weight: 600;
  color: #0f172a;
}

.issue-meta {
  margin-top: 6px;
  color: rgba(15, 23, 42, 0.68);
  line-height: 1.5;
}

.health-checks {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.health-check {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 16px;
  padding: 14px 0;
  border-bottom: 1px solid rgba(15, 23, 42, 0.08);
}

.health-check:first-child {
  padding-top: 0;
}

.health-check:last-child {
  border-bottom: none;
  padding-bottom: 0;
}

.health-check__title {
  font-weight: 600;
  color: #0f172a;
}

.health-check__detail {
  margin-top: 6px;
  color: rgba(15, 23, 42, 0.68);
  line-height: 1.5;
}

.status-breakdown {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.status-breakdown__row {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.status-breakdown__label {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  color: rgba(15, 23, 42, 0.82);
  font-weight: 500;
}

.status-breakdown__track {
  width: 100%;
  height: 8px;
  border-radius: 999px;
  background: rgba(148, 163, 184, 0.18);
  overflow: hidden;
}

.status-breakdown__fill {
  height: 100%;
  border-radius: inherit;
  background: linear-gradient(90deg, #2563eb, #60a5fa);
}

@media (max-width: 768px) {
  .monitor-page__hero {
    flex-direction: column;
    align-items: stretch;
  }

  .summary-value-row {
    align-items: flex-start;
    flex-direction: column;
  }

  .health-check {
    flex-direction: column;
    align-items: flex-start;
  }
}
</style>
