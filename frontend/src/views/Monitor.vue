<template>
  <div class="monitor-page">
    <n-spin :show="initialLoading">
      <template #description>{{ t('monitor.loading') }}</template>

      <div class="page-hero">
        <PageHeader
          :title="t('monitor.title')"
          :subtitle="t('monitor.subtitle')"
          root-class="monitor-page__hero"
        >
          <template #actions>
            <n-button secondary :loading="loading && hasLoadedOnce" @click="fetchData()">
              {{ t('common.refresh') }}
            </n-button>
          </template>
        </PageHeader>

        <n-grid :x-gap="16" :y-gap="16" cols="2 s:2 l:4" responsive="screen">
          <n-gi v-for="item in overviewCards" :key="item.key" class="monitor-grid-cell">
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
      </div>
      <n-space vertical :size="16">
        <n-alert type="info" :show-icon="false" :style="{ borderRadius: '12px' }">
          {{ t('monitor.dataSourceInfo') }}
        </n-alert>

        <n-tabs v-model:value="activeTab" type="line" animated class="monitor-tabs">
          <n-tab-pane name="runtime" :tab="t('monitor.runtimeTab')">
            <n-space vertical :size="16">
              <n-grid :x-gap="16" :y-gap="16" cols="2 s:2 l:4" responsive="screen">
                <n-gi v-for="item in runtimeCards" :key="item.key" class="monitor-grid-cell">
                  <SummaryCard
                    :label="item.label"
                    :value="item.value"
                    :note="item.help"
                    card-class="monitor-summary-card"
                    label-class="summary-label"
                    value-class="summary-value"
                    note-class="summary-help"
                  />
                </n-gi>
              </n-grid>

              <n-card class="monitor-card">
                <template #header>
                  <div class="monitor-card__header">
                    <div>
                      <div class="monitor-card__title">{{ t('monitor.activeTasksTitle') }}</div>
                      <div class="monitor-card__subtitle">{{ t('monitor.activeTasksSubtitle') }}</div>
                    </div>
                    <n-button-group size="small">
                      <n-button
                        v-for="opt in queueViewOptions"
                        :key="opt.value"
                        :type="queueViewMode === opt.value ? 'primary' : 'default'"
                        :ghost="queueViewMode === opt.value"
                        @click="queueViewMode = opt.value"
                      >{{ opt.label }}</n-button>
                    </n-button-group>
                  </div>
                </template>

                <div v-if="!tableLoading && activeTasks.length === 0" class="queue-empty"><n-empty :description="t('monitor.noActiveTasks')" /></div>

                <!-- Kanban View -->
                <div v-else-if="queueViewMode === 'kanban'" class="queue-kanban">
                  <!-- Running Column -->
                  <div class="queue-kanban__column queue-kanban__column--running">
                    <div class="queue-kanban__column-header">
                      <span>{{ t('monitor.kanbanRunning') }}</span>
                      <n-tag size="tiny" round :bordered="false">{{ runningTasks.length }}</n-tag>
                    </div>
                    <n-scrollbar class="queue-kanban__column-cards" trigger="hover">
                    <div
                      v-for="task in runningTasks"
                      :key="task.id"
                      class="queue-kanban__card"
                      role="button"
                      tabindex="0"
                      @click="goToTask(task.id)"
                      @keydown.enter="goToTask(task.id)"
                      @keydown.space.prevent="goToTask(task.id)"
                    >
                      <div class="queue-kanban__card-top">
                        <span
                          :class="['queue-kanban__priority-badge', priorityClass(task.priority)]"
                        >
                          <span class="queue-kanban__priority-dot"></span>
                          {{ formatPriority(task.priority) }}
                        </span>
                        <span class="queue-kanban__task-id">#{{ task.id }}</span>
                      </div>
                      <div class="queue-kanban__card-project">{{ kanbanProjectLabel(task) }} {{ kanbanIssueLabel(task) }}</div>
                      <div class="queue-kanban__card-meta">
                        ⏱ {{ t('monitor.kanbanElapsed', { duration: task.started_at ? formatElapsedCompact(task.started_at) : '—' }) }}
                      </div>
                    </div>
                    <n-empty
                      v-if="runningTasks.length === 0"
                      :description="'—'"
                      :show-icon="false"
                      size="small"
                      style="padding: 16px 0"
                    />
                    </n-scrollbar>
                  </div>

                  <!-- Ready Column -->
                  <div class="queue-kanban__column queue-kanban__column--ready">
                    <div class="queue-kanban__column-header">
                      <span>{{ t('monitor.kanbanReady') }}</span>
                      <n-tag size="tiny" round :bordered="false">{{ readyTasks.length }}</n-tag>
                    </div>
                    <n-scrollbar class="queue-kanban__column-cards" trigger="hover">
                    <div
                      v-for="task in readyTasks"
                      :key="task.id"
                      class="queue-kanban__card"
                      role="button"
                      tabindex="0"
                      @click="goToTask(task.id)"
                      @keydown.enter="goToTask(task.id)"
                      @keydown.space.prevent="goToTask(task.id)"
                    >
                      <div class="queue-kanban__card-top">
                        <span
                          :class="['queue-kanban__priority-badge', priorityClass(task.priority)]"
                        >
                          <span class="queue-kanban__priority-dot"></span>
                          {{ formatPriority(task.priority) }}
                        </span>
                        <span class="queue-kanban__task-id">#{{ task.id }}</span>
                      </div>
                      <div class="queue-kanban__card-project">{{ kanbanProjectLabel(task) }} {{ kanbanIssueLabel(task) }}</div>
                      <div class="queue-kanban__card-meta">
                        <template v-if="task.scheduled_at">
                          🕐 {{ t('monitor.kanbanDue', { time: formatTimeUtc8(task.scheduled_at) }) }}
                        </template>
                        <template v-else>
                          {{ t('monitor.kanbanImmediate') }}
                        </template>
                      </div>
                    </div>
                    <n-empty
                      v-if="readyTasks.length === 0"
                      :description="'—'"
                      :show-icon="false"
                      size="small"
                      style="padding: 16px 0"
                    />
                    </n-scrollbar>
                  </div>

                  <!-- Waiting Column -->
                  <div class="queue-kanban__column queue-kanban__column--waiting">
                    <div class="queue-kanban__column-header">
                      <span>{{ t('monitor.kanbanWaiting') }}</span>
                      <n-tag size="tiny" round :bordered="false">{{ waitingTasks.length }}</n-tag>
                    </div>
                    <n-scrollbar class="queue-kanban__column-cards" trigger="hover">
                    <div
                      v-for="task in waitingTasks"
                      :key="task.id"
                      class="queue-kanban__card"
                      role="button"
                      tabindex="0"
                      @click="goToTask(task.id)"
                      @keydown.enter="goToTask(task.id)"
                      @keydown.space.prevent="goToTask(task.id)"
                    >
                      <div class="queue-kanban__card-top">
                        <span
                          :class="['queue-kanban__priority-badge', priorityClass(task.priority)]"
                        >
                          <span class="queue-kanban__priority-dot"></span>
                          {{ formatPriority(task.priority) }}
                        </span>
                        <span class="queue-kanban__task-id">#{{ task.id }}</span>
                      </div>
                      <div class="queue-kanban__card-project">{{ kanbanProjectLabel(task) }}</div>
                      <div class="queue-kanban__card-meta">
                        🕐 {{ formatTimeUtc8(task.scheduled_at!) }}
                        <span class="queue-kanban__relative-time">({{ t('monitor.kanbanIn', { duration: formatRelativeFuture(task.scheduled_at!) }) }})</span>
                      </div>
                    </div>
                    <n-empty
                      v-if="waitingTasks.length === 0"
                      :description="'—'"
                      :show-icon="false"
                      size="small"
                      style="padding: 16px 0"
                    />
                    </n-scrollbar>
                  </div>
                </div>

                <!-- Timeline View -->
                <div v-else-if="queueViewMode === 'timeline'" class="queue-timeline">
                  <!-- Legend + Zoom -->
                  <div class="queue-timeline__toolbar">
                    <div class="queue-timeline__legend">
                      <span class="queue-timeline__legend-item">
                        <span class="queue-timeline__legend-swatch queue-timeline__legend-swatch--running"></span>
                        {{ t('monitor.kanbanRunning') }}
                      </span>
                      <span class="queue-timeline__legend-item">
                        <span class="queue-timeline__legend-swatch queue-timeline__legend-swatch--ready"></span>
                        {{ t('monitor.kanbanReady') }}
                      </span>
                      <span class="queue-timeline__legend-item">
                        <span class="queue-timeline__legend-swatch queue-timeline__legend-swatch--waiting"></span>
                        {{ t('monitor.kanbanWaiting') }}
                      </span>
                    </div>
                    <n-button-group size="tiny">
                      <n-button
                        v-for="opt in timelineZoomOptions"
                        :key="opt.value"
                        :type="timelineZoom === opt.value ? 'primary' : 'default'"
                        :ghost="timelineZoom === opt.value"
                        @click="timelineZoom = opt.value"
                      >{{ opt.label }}</n-button>
                    </n-button-group>
                  </div>

                  <!-- Scrollable area -->
                  <n-scrollbar ref="timelineScrollRef" class="queue-timeline__scroll" x-scrollable trigger="hover">
                    <div class="queue-timeline__container" :style="{ minWidth: timelineContainerMinWidth }">
                      <!-- Time axis -->
                      <div class="queue-timeline__axis">
                        <span
                          v-for="tick in timelineTicks"
                          :key="tick.time"
                          class="queue-timeline__tick"
                          :style="{ left: tick.pct + '%' }"
                        >{{ tick.label }}</span>
                      </div>

                      <!-- Content area (gridlines + now marker + groups) -->
                      <div class="queue-timeline__content">
                        <!-- Vertical gridlines -->
                        <div
                          v-for="tick in timelineTicks"
                          :key="'grid-' + tick.time"
                          class="queue-timeline__gridline"
                          :style="{ left: tick.pct + '%' }"
                        ></div>

                        <!-- Now marker -->
                        <div
                          class="queue-timeline__now-marker"
                          :style="{ left: timelinePct(nowMs) + '%' }"
                        >
                          <span class="queue-timeline__now-label">{{ t('monitor.timelineNow') }}</span>
                        </div>

                        <!-- Empty state -->
                        <div
                          v-if="!runningTasks.length && !readyTasks.length && !waitingTasks.length"
                          class="queue-timeline__empty"
                        >
                          <n-empty size="small" :description="t('monitor.noActiveTasks')" />
                        </div>

                        <!-- Running group -->
                        <div v-if="runningTasks.length" class="queue-timeline__group">
                          <div class="queue-timeline__group-header">
                            <span class="queue-timeline__group-badge queue-timeline__group-badge--running">
                              {{ t('monitor.kanbanRunning') }} · {{ runningTasks.length }}
                            </span>
                          </div>
                          <div
                            class="queue-timeline__group-tracks"
                            :style="{ height: runningTasks.length * 36 + 'px' }"
                          >
                            <div
                              v-for="(task, idx) in runningTasks"
                              :key="'run-' + task.id"
                              class="queue-timeline__task-bar queue-timeline__task-bar--running queue-timeline__has-tooltip"
                              role="button"
                              tabindex="0"
                              :style="{
                                left: timelinePct(task.started_at ? parseUtcDate(task.started_at).getTime() : nowMs) + '%',
                                top: idx * 36 + 'px',
                              }"
                              @mouseenter="showTimelineTooltip($event, `#${task.id} · ${formatPriority(task.priority)} · ${kanbanProjectLabel(task)}\n${t('monitor.kanbanElapsed', { duration: task.started_at ? formatElapsedCompact(task.started_at) : '—' })}${task.initiator_username ? '\n@' + task.initiator_username : ''}`)"
                              @mouseleave="hideTimelineTooltip"
                              @click="goToTask(task.id)"
                              @keydown.enter="goToTask(task.id)"
                              @keydown.space.prevent="goToTask(task.id)"
                            >
                              <span class="queue-timeline__bar-label">#{{ task.id }} {{ formatPriority(task.priority) }}</span>
                            </div>
                          </div>
                        </div>

                        <!-- Ready group -->
                        <div v-if="readyTasks.length" class="queue-timeline__group">
                          <div class="queue-timeline__group-header">
                            <span class="queue-timeline__group-badge queue-timeline__group-badge--ready">
                              {{ t('monitor.kanbanReady') }} · {{ readyTasks.length }}
                            </span>
                          </div>
                          <div
                            class="queue-timeline__group-tracks"
                            :style="{ height: readyTasks.length * 36 + 'px' }"
                          >
                            <div
                              v-for="(task, idx) in readyTasks"
                              :key="'rdy-' + task.id"
                              class="queue-timeline__task-bar queue-timeline__task-bar--ready queue-timeline__has-tooltip"
                              role="button"
                              tabindex="0"
                              :style="{
                                left: timelinePct(task.scheduled_at ? Math.min(parseUtcDate(task.scheduled_at).getTime(), nowMs) : nowMs) + '%',
                                top: idx * 36 + 'px',
                              }"
                              @mouseenter="showTimelineTooltip($event, `#${task.id} · ${formatPriority(task.priority)} · ${kanbanProjectLabel(task)}\n${t('monitor.timelineReady')}${task.scheduled_at ? ' · ' + formatTimeUtc8(task.scheduled_at) : ''}${task.initiator_username ? '\n@' + task.initiator_username : ''}`)"
                              @mouseleave="hideTimelineTooltip"
                              @click="goToTask(task.id)"
                              @keydown.enter="goToTask(task.id)"
                              @keydown.space.prevent="goToTask(task.id)"
                            >
                              <span class="queue-timeline__bar-label">#{{ task.id }} {{ formatPriority(task.priority) }} {{ t('monitor.timelineReady') }}</span>
                            </div>
                          </div>
                        </div>

                        <!-- Waiting group -->
                        <div v-if="waitingTasks.length" class="queue-timeline__group">
                          <div class="queue-timeline__group-header">
                            <span class="queue-timeline__group-badge queue-timeline__group-badge--waiting">
                              {{ t('monitor.kanbanWaiting') }} · {{ waitingTasks.length }}
                            </span>
                          </div>
                          <div
                            class="queue-timeline__group-tracks"
                            :style="{ height: waitingTasks.length * 36 + 'px' }"
                          >
                            <div
                              v-for="(task, idx) in waitingTasks"
                              :key="'wait-' + task.id"
                              class="queue-timeline__task-bar queue-timeline__task-bar--waiting queue-timeline__has-tooltip"
                              role="button"
                              tabindex="0"
                              :style="{
                                left: timelinePct(parseUtcDate(task.scheduled_at!).getTime()) + '%',
                                top: idx * 36 + 'px',
                              }"
                              @mouseenter="showTimelineTooltip($event, `#${task.id} · ${formatPriority(task.priority)} · ${kanbanProjectLabel(task)}\n${t('monitor.timelineWaiting')}: ${formatTimeUtc8(task.scheduled_at!)} (${t('monitor.kanbanIn', { duration: formatRelativeFuture(task.scheduled_at!) })})${task.initiator_username ? '\n@' + task.initiator_username : ''}`)"
                              @mouseleave="hideTimelineTooltip"
                              @click="goToTask(task.id)"
                              @keydown.enter="goToTask(task.id)"
                              @keydown.space.prevent="goToTask(task.id)"
                            >
                              <span class="queue-timeline__bar-label">#{{ task.id }} {{ formatPriority(task.priority) }} {{ formatTimeUtc8(task.scheduled_at!) }}</span>
                            </div>
                          </div>
                        </div>
                      </div>
                    </div>
                  </n-scrollbar>

                  <!-- Dynamic tooltip element -->
                  <div
                    v-show="tooltipVisible"
                    class="queue-timeline__tooltip"
                    :style="tooltipStyle"
                  >{{ tooltipText }}</div>
                </div>

                <!-- Table View -->
                <div v-else class="queue-table-wrapper">
                  <n-data-table
                    :columns="activeTaskColumns"
                    :data="activeTasks"
                    :loading="tableLoading"
                    :pagination="false"
                    :row-props="activeTaskRowProps"
                    size="small"
                    scroll-x="1040"
                    :max-height="340"
                  />
                </div>
              </n-card>

              <n-card class="monitor-card">
                <template #header>
                  <div class="monitor-card__header">
                    <div>
                      <div class="monitor-card__title">{{ t('monitor.recentActivityTitle') }}</div>
                      <div class="monitor-card__subtitle">{{ t('monitor.recentActivitySubtitle') }}</div>
                    </div>
                  </div>
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
                  scroll-x="1080"
                />
              </n-card>
            </n-space>
          </n-tab-pane>

          <n-tab-pane name="debug" :tab="t('monitor.debugTab')">
            <n-space vertical :size="16">
              <n-grid :x-gap="16" :y-gap="16" cols="2 s:2 l:4" responsive="screen">
                <n-gi v-for="item in debugCards" :key="item.key" class="monitor-grid-cell">
                  <SummaryCard
                    :label="item.label"
                    :value="item.value"
                    :note="item.help"
                    card-class="monitor-summary-card"
                    label-class="summary-label"
                    value-class="summary-value"
                    note-class="summary-help"
                  />
                </n-gi>
              </n-grid>

              <n-grid :x-gap="16" :y-gap="16" cols="1 l:2" responsive="screen">
                <n-gi class="monitor-grid-cell">
                  <n-card class="monitor-card monitor-card--stretch" :title="t('monitor.runningTasksWithoutContainerTitle')">
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

                <n-gi class="monitor-grid-cell">
                  <n-card class="monitor-card monitor-card--stretch" :title="t('monitor.orphanContainersTitle')">
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

              <n-card class="monitor-card">
                <template #header>
                  <div class="monitor-card__header">
                    <div>
                      <div class="monitor-card__title">{{ t('monitor.containersTitle') }}</div>
                      <div class="monitor-card__subtitle">{{ t('monitor.containersSubtitle') }}</div>
                    </div>
                  </div>
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
                <n-gi class="monitor-grid-cell">
                  <n-card class="monitor-card monitor-card--stretch" :title="t('monitor.healthChecksTitle')">
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

                <n-gi class="monitor-grid-cell">
                  <n-card class="monitor-card monitor-card--stretch" :title="t('monitor.statusBreakdownTitle')">
                    <div class="status-breakdown">
                      <div v-for="item in statusBreakdown" :key="item.key" class="status-breakdown__row">
                        <div class="status-breakdown__label">
                          <span>{{ item.label }}</span>
                          <span>{{ item.value }}</span>
                        </div>
                        <div class="status-breakdown__track">
                          <div class="status-breakdown__fill" :class="`status-breakdown__fill--${item.key}`" :style="{ width: `${item.percent}%` }"></div>
                        </div>
                      </div>
                    </div>
                  </n-card>
                </n-gi>
              </n-grid>

              <n-card class="monitor-card">
                <template #header>
                  <div class="monitor-card__header">
                    <div>
                      <div class="monitor-card__title">{{ t('monitor.recentFailuresTitle') }}</div>
                      <div class="monitor-card__subtitle">{{ t('monitor.recentFailuresSubtitle') }}</div>
                    </div>
                  </div>
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
import { computed, h, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import {
  NAlert,
  NButton,
  NButtonGroup,
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
  NScrollbar,
  NTooltip,
  type DataTableColumns,
  useMessage
} from 'naive-ui'
import { useI18n } from 'vue-i18n'
import { getContainers, getStats, getTasks, getTasksPaginated, type Container, type Stats, type Task } from '../api'
import PageHeader from '../components/PageHeader.vue'
import SummaryCard from '../components/SummaryCard.vue'
import { formatDateTimeUtc8Compact, formatTimeUtc8, parseUtcDate } from '../utils/datetime'
import { formatPriority, formatDurationMs, getProjectLabel as _getProjectLabel } from '../utils/format'

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
  cancelled: 0,
  completed_24h: 0,
  failed_cancelled_24h: 0,
  running_long_30min: 0,
})
const containers = ref<Container[]>([])
const tasks = ref<Task[]>([])
const recentFinishedList = ref<Task[]>([])
const recentFailureList = ref<Task[]>([])
let pendingSilentRefresh = false
let pendingVisibleRefresh = false
let refreshTimer: number | null = null
let elapsedTimer: ReturnType<typeof setInterval> | null = null

const queueViewMode = ref<'kanban' | 'timeline' | 'table'>('kanban')
const nowMs = ref(Date.now())
const timelineZoom = ref<'auto' | '1h' | '2h' | '4h' | '8h' | '24h'>('auto')

const timelineZoomOptions = [
  { label: 'Auto', value: 'auto' as const },
  { label: '1h', value: '1h' as const },
  { label: '2h', value: '2h' as const },
  { label: '4h', value: '4h' as const },
  { label: '8h', value: '8h' as const },
  { label: '24h', value: '24h' as const },
]

const timelineScrollRef = ref<InstanceType<typeof NScrollbar> | null>(null)

function scrollTimelineToNow() {
  const el = timelineScrollRef.value?.$el as HTMLElement | undefined
  if (!el) return
  const scrollEl = (el.querySelector('.n-scrollbar-container') as HTMLElement) || el
  const containerWidth = scrollEl.scrollWidth
  const viewportWidth = scrollEl.clientWidth
  const nowPct = timelinePct(nowMs.value) / 100
  const nowPx = nowPct * containerWidth
  scrollEl.scrollLeft = nowPx - viewportWidth / 2
}

watch(timelineZoom, () => {
  nextTick(() => scrollTimelineToNow())
})

const queueViewOptions = computed(() => [
  { label: t('monitor.viewKanban'), value: 'kanban' as const },
  { label: t('monitor.viewTimeline'), value: 'timeline' as const },
  { label: t('monitor.viewTable'), value: 'table' as const },
])

const initialLoading = computed(() => loading.value && !hasLoadedOnce.value)
const tableLoading = computed(() => loading.value && hasLoadedOnce.value)

const tasksById = computed(() => new Map(tasks.value.map((task) => [task.id, task])))

const activeTasks = computed(() => {
  const now = nowMs.value
  return tasks.value
    .filter((task) => ACTIVE_STATUSES.includes(task.status))
    .sort((a, b) => {
      // 1. Running tasks always first
      const aRunning = a.status === 'running' ? 0 : 1
      const bRunning = b.status === 'running' ? 0 : 1
      if (aRunning !== bRunning) return aRunning - bRunning

      // 2. Ready (due now or immediate) before Waiting (future scheduled)
      const aReady = !a.scheduled_at || parseUtcDate(a.scheduled_at).getTime() <= now ? 0 : 1
      const bReady = !b.scheduled_at || parseUtcDate(b.scheduled_at).getTime() <= now ? 0 : 1
      if (aReady !== bReady) return aReady - bReady

      // Within Ready group: scheduler ordering
      if (aReady === 0 && bReady === 0) {
        if (a.priority !== b.priority) return a.priority - b.priority
        // Due scheduled > immediate
        const aDue = a.scheduled_at ? 0 : 1
        const bDue = b.scheduled_at ? 0 : 1
        if (aDue !== bDue) return aDue - bDue
        if (a.scheduled_at && b.scheduled_at) {
          const diff = parseUtcDate(a.scheduled_at).getTime() - parseUtcDate(b.scheduled_at).getTime()
          if (diff !== 0) return diff
        }
        return parseUtcDate(a.created_at).getTime() - parseUtcDate(b.created_at).getTime()
      }

      // Within Waiting group: earliest scheduled_at first
      if (a.scheduled_at && b.scheduled_at) {
        return parseUtcDate(a.scheduled_at).getTime() - parseUtcDate(b.scheduled_at).getTime()
      }
      return 0
    })
})

const runningTasks = computed(() =>
  activeTasks.value.filter((task) => task.status === 'running')
)

const pendingQueuedTasks = computed(() =>
  activeTasks.value.filter((task) => task.status === 'pending' || task.status === 'queued')
)

const readyTasks = computed(() => {
  const now = nowMs.value
  return pendingQueuedTasks.value.filter(
    (t) => !t.scheduled_at || parseUtcDate(t.scheduled_at).getTime() <= now
  )
})

const waitingTasks = computed(() => {
  const now = nowMs.value
  return pendingQueuedTasks.value.filter(
    (t) => t.scheduled_at != null && parseUtcDate(t.scheduled_at).getTime() > now
  )
})

/* --- Smart timeline tooltip --- */
const tooltipVisible = ref(false)
const tooltipText = ref('')
const tooltipStyle = ref<Record<string, string>>({})

function showTimelineTooltip(e: MouseEvent, text: string) {
  const el = e.currentTarget as HTMLElement
  if (!el) return
  const rect = el.getBoundingClientRect()
  const spaceBelow = window.innerHeight - rect.bottom
  tooltipText.value = text
  const left = Math.min(rect.left, window.innerWidth - 270)
  if (spaceBelow > 120) {
    tooltipStyle.value = {
      left: Math.max(4, left) + 'px',
      top: rect.bottom + 6 + 'px',
    }
  } else {
    tooltipStyle.value = {
      left: Math.max(4, left) + 'px',
      top: rect.top - 6 + 'px',
      transform: 'translateY(-100%)',
    }
  }
  tooltipVisible.value = true
}

function hideTimelineTooltip() {
  tooltipVisible.value = false
}

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

const recentFinishedTasks = computed(() => recentFinishedList.value)

const recentFailures = computed(() => recentFailureList.value)

const recentFinishedCount24h = computed(() => stats.value.completed_24h)

const recentFailureCount24h = computed(() => stats.value.failed_cancelled_24h)

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
    tag: pendingQueuedTasks.value.length > 0 ? t('monitor.waiting') : t('monitor.clear'),
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
    minWidth: 170,
    render: (task) => getProjectLabel(task)
  },
  {
    title: t('common.initiator'),
    key: 'initiator_username',
    width: 100,
    render: (task) => task.initiator_username || '—'
  },
  {
    title: t('monitor.task'),
    key: 'task',
    minWidth: 220,
    render: (task) => {
      const preview = formatPromptPreview(task.user_prompt)
      const full = (task.user_prompt || '').replace(/\s+/g, ' ').trim()
      if (!full) return '—'
      return h(NTooltip, { trigger: 'hover', placement: 'top-start' }, {
        trigger: () => h('span', { style: 'cursor: default' }, preview),
        default: () => h('div', { style: 'max-width: 420px; white-space: pre-wrap; word-break: break-word' }, full)
      })
    }
  },
  {
    title: t('monitor.status'),
    key: 'status',
    width: 130,
    render: (task) =>
      h('div', { style: 'display: flex; align-items: center; gap: 6px' }, [
        renderStatusTag(task.status),
        h('span', { style: 'font-size: 12px; font-weight: 600; white-space: nowrap' }, formatPriority(task.priority))
      ])
  },
  {
    title: t('common.scheduledAt'),
    key: 'scheduled_at',
    width: 170,
    render: (task) => {
      const scheduled = task.scheduled_at ? formatTimestamp(task.scheduled_at) : t('monitor.immediateTask')
      const elapsed = getTaskElapsedLabel(task)
      return h('div', {}, [
        h('div', { style: 'line-height: 1.4' }, scheduled),
        h('div', { style: 'font-size: 12px; color: var(--n-text-color-3); line-height: 1.4' }, elapsed)
      ])
    }
  },
  {
    title: t('common.createdAt'),
    key: 'created_at',
    width: 140,
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
    title: t('common.initiator'),
    key: 'initiator_username',
    width: 100,
    render: (task) => task.initiator_username || '—'
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

function priorityClass(priority?: string | number | null): string {
  const normalized = String(priority ?? '').toLowerCase().trim()
  if (normalized === '0' || normalized === 'p0') return 'priority-tone--p0'
  if (normalized === '1' || normalized === 'p1') return 'priority-tone--p1'
  if (normalized === '2' || normalized === 'p2') return 'priority-tone--p2'
  return 'priority-tone--default'
}

function formatAge(value?: string | null): string {
  if (!value) return '-'
  return formatDurationMs(Date.now() - parseTimestamp(value))
}

function getExecutionDuration(task: Task): string {
  if (!task.started_at || !task.completed_at) return '-'
  return formatDurationMs(parseTimestamp(task.completed_at) - parseTimestamp(task.started_at))
}

function getTaskElapsedLabel(task: Task): string {
  if (task.started_at && task.status === 'running') {
    return `${t('monitor.runningForPrefix')} ${formatAge(task.started_at)}`
  }
  return `${t('monitor.waitingForPrefix')} ${formatAge(task.created_at)}`
}

function getProjectLabel(task: Task): string {
  return _getProjectLabel(task, t('dashboard.projectFallback', { id: task.project_id }))
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

function formatElapsedCompact(startedAt: string): string {
  const ms = Math.max(0, nowMs.value - parseUtcDate(startedAt).getTime())
  const totalSec = Math.floor(ms / 1000)
  const h = Math.floor(totalSec / 3600)
  const m = Math.floor((totalSec % 3600) / 60)
  const s = totalSec % 60
  if (h > 0) return `${h}h ${m}m`
  return `${m}m ${s}s`
}

function formatRelativeFuture(scheduledAt: string): string {
  const ms = Math.max(0, parseUtcDate(scheduledAt).getTime() - nowMs.value)
  const totalMin = Math.floor(ms / 60000)
  const h = Math.floor(totalMin / 60)
  const m = totalMin % 60
  if (h > 0 && m > 0) return `${h}h ${m}m`
  if (h > 0) return `${h}h`
  if (m > 0) return `${m}m`
  return '<1m'
}

function kanbanProjectLabel(task: Task): string {
  return task.project_name || task.project_path_with_namespace || '—'
}

function kanbanIssueLabel(task: Task): string {
  if (task.issue) return `#${task.issue.id} ${task.issue.title}`
  return '—'
}

/* ----- Timeline computed helpers ----- */

const timelineRange = computed(() => {
  const now = nowMs.value
  let minTime = now - 60 * 60 * 1000
  let maxTime = now + 4 * 60 * 60 * 1000

  for (const task of activeTasks.value) {
    if (task.started_at) {
      minTime = Math.min(minTime, parseUtcDate(task.started_at).getTime())
    }
    if (task.scheduled_at) {
      const st = parseUtcDate(task.scheduled_at).getTime()
      minTime = Math.min(minTime, st)
      maxTime = Math.max(maxTime, st + 30 * 60 * 1000)
    }
  }

  // In zoom mode, extend range to at least cover the zoom window
  if (timelineZoom.value !== 'auto') {
    const hours = parseInt(timelineZoom.value)
    const windowMs = hours * 60 * 60 * 1000
    minTime = Math.min(minTime, now - windowMs * 0.3)
    maxTime = Math.max(maxTime, now + windowMs * 0.7)
  }

  const span = maxTime - minTime
  const pad = span * 0.05
  return { start: minTime - pad, end: maxTime + pad }
})

function timelinePct(timeMs: number): number {
  const { start, end } = timelineRange.value
  const span = end - start
  if (span <= 0) return 0
  return Math.max(0, Math.min(100, ((timeMs - start) / span) * 100))
}

const timelineTicks = computed(() => {
  const { start, end } = timelineRange.value
  const span = end - start
  const intervals = [15, 30, 60, 120, 240]
  let intervalMin = 60

  if (timelineZoom.value !== 'auto') {
    // Tick density based on zoom level
    const zoomMs = parseInt(timelineZoom.value) * 60 * 60 * 1000
    for (const iv of intervals) {
      if (zoomMs / (iv * 60 * 1000) <= 8) {
        intervalMin = iv
        break
      }
    }
  } else {
    for (const iv of intervals) {
      if (span / (iv * 60 * 1000) <= 8) {
        intervalMin = iv
        break
      }
    }
  }
  const intervalMs = intervalMin * 60 * 1000

  const firstTick = Math.ceil(start / intervalMs) * intervalMs
  const ticks: { time: number; pct: number; label: string }[] = []
  for (let t = firstTick; t <= end; t += intervalMs) {
    ticks.push({
      time: t,
      pct: timelinePct(t),
      label: formatTimeUtc8(new Date(t)),
    })
  }
  return ticks
})

const timelineContainerMinWidth = computed(() => {
  return Math.max(600, timelineTicks.value.length * 90) + 'px'
})

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
    const [statsData, containersData, tasksData, finishedResult, failedResult] = await Promise.all([
      getStats(),
      getContainers(),
      getTasks({ status: 'running,pending,queued' }),
      getTasksPaginated({ status: 'completed,failed,cancelled', page: 1, page_size: 10 }),
      getTasksPaginated({ status: 'failed,cancelled', page: 1, page_size: 10 }),
    ])

    stats.value = statsData
    containers.value = containersData
    tasks.value = tasksData
    recentFinishedList.value = finishedResult.items
    recentFailureList.value = failedResult.items
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
  elapsedTimer = setInterval(() => { nowMs.value = Date.now() }, 1000)
})

onBeforeUnmount(() => {
  stopAutoRefresh()
  if (elapsedTimer) {
    clearInterval(elapsedTimer)
    elapsedTimer = null
  }
})
</script>

<style scoped>
.monitor-page {
  max-width: var(--app-page-max-width);
}

.monitor-page__hero {
  --app-page-header-gap: 20px;
}

.monitor-summary-card :deep(.n-card__content),
.monitor-card :deep(.n-card__content) {
  padding-top: 16px;
  padding-bottom: 16px;
}

.monitor-grid-cell {
  display: flex;
}

.monitor-grid-cell > * {
  flex: 1;
}

.monitor-summary-card,
.monitor-card--stretch {
  height: 100%;
}

.monitor-card {
  border-radius: var(--app-card-radius);
}

.monitor-summary-card {
  background: rgba(255, 255, 255, 0.82);
  backdrop-filter: blur(12px);
  border: 1px solid rgba(15, 23, 42, 0.06);
  border-radius: 14px;
  box-shadow: 0 1px 3px rgba(15, 23, 42, 0.04);
  transition: transform 0.25s cubic-bezier(0.22, 0.61, 0.36, 1), box-shadow 0.25s ease, border-color 0.25s ease;
}

.monitor-summary-card:hover {
  transform: translateY(-2px);
  box-shadow: 0 4px 16px rgba(15, 23, 42, 0.08);
  border-color: rgba(15, 23, 42, 0.1);
}

.monitor-summary-card :deep(.n-card__content) {
  display: flex;
  flex-direction: column;
  height: 100%;
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
  margin: auto 0 0;
  padding-top: 10px;
  color: rgba(15, 23, 42, 0.68);
  line-height: 1.5;
  min-height: 42px;
}

.monitor-card__header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 12px;
  flex-wrap: wrap;
}

.monitor-card__title {
  font-size: 18px;
  font-weight: 600;
}

.monitor-card__subtitle {
  margin-top: 4px;
  font-size: 13px;
  color: rgba(15, 23, 42, 0.56);
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
.status-breakdown__fill--pending { background: linear-gradient(90deg, #94a3b8, #b0bec5); }
.status-breakdown__fill--queued { background: linear-gradient(90deg, #2563eb, #60a5fa); }
.status-breakdown__fill--running { background: linear-gradient(90deg, #d97706, #fbbf24); }
.status-breakdown__fill--completed { background: linear-gradient(90deg, #16a34a, #4ade80); }
.status-breakdown__fill--failed { background: linear-gradient(90deg, #dc2626, #f87171); }
.status-breakdown__fill--cancelled { background: linear-gradient(90deg, #64748b, #94a3b8); }

/* ----- Kanban View ----- */
.queue-kanban {
  display: grid;
  grid-template-columns: 1fr 1fr 1fr;
  gap: 16px;
  height: 340px;
}

.queue-kanban__column {
  background: rgba(248, 250, 252, 0.72);
  border-radius: 8px;
  padding: 12px;
  min-height: 0;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

.queue-kanban__column-header {
  font-weight: 600;
  font-size: 14px;
  margin-bottom: 12px;
  display: flex;
  align-items: center;
  gap: 8px;
  color: #0f172a;
  flex-shrink: 0;
}

.queue-kanban__column-cards {
  flex: 1;
  min-height: 0;
}

.queue-kanban__column--running {
  border-left: 3px solid rgba(24, 160, 88, 0.5);
}

.queue-kanban__column--ready {
  border-left: 3px solid rgba(32, 128, 240, 0.5);
}

.queue-kanban__column--waiting {
  border-left: 3px solid rgba(148, 163, 184, 0.55);
}

.queue-kanban__card {
  background: var(--card-color, #fff);
  border-radius: 6px;
  padding: 10px 12px;
  margin-bottom: 8px;
  cursor: pointer;
  border: 1px solid rgba(15, 23, 42, 0.08);
  transition: box-shadow 0.2s, border-color 0.2s;
}

.queue-kanban__card:hover {
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.12);
  border-color: rgba(15, 23, 42, 0.16);
}

.queue-kanban__card:last-child {
  margin-bottom: 0;
}

.queue-kanban__card-top {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 4px;
}

.queue-kanban__priority-badge {
  --queue-priority-color: rgba(100, 116, 139, 0.9);
  --queue-priority-soft: rgba(148, 163, 184, 0.16);
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 3px 8px;
  border-radius: 999px;
  font-size: 11px;
  font-weight: 500;
  color: rgba(15, 23, 42, 0.72);
  line-height: 1;
  background: rgba(248, 250, 252, 0.92);
  border: 1px solid rgba(148, 163, 184, 0.18);
}

.queue-kanban__priority-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  flex-shrink: 0;
  background: var(--queue-priority-color);
  /* box-shadow: 0 0 0 3px var(--queue-priority-soft); */
}

.priority-tone--p0 {
  --queue-priority-color: #d03050;
  --queue-priority-soft: rgba(208, 48, 80, 0.12);
}

.priority-tone--p1 {
  --queue-priority-color: #f0a020;
  --queue-priority-soft: rgba(240, 160, 32, 0.14);
}

.priority-tone--p2 {
  --queue-priority-color: #18a058;
  --queue-priority-soft: rgba(24, 160, 88, 0.12);
}

.queue-kanban__task-id {
  font-weight: 600;
  font-size: 13px;
  color: #0f172a;
}

.queue-kanban__card-project {
  font-size: 12px;
  color: rgba(15, 23, 42, 0.68);
  margin-bottom: 4px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.queue-kanban__card-meta {
  font-size: 12px;
  color: rgba(15, 23, 42, 0.56);
}

.queue-kanban__relative-time {
  opacity: 0.8;
}

.queue-empty {
  height: 340px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.queue-table-wrapper {
  height: 340px;
}

/* ----- Timeline View ----- */
/* ===== Timeline — redesigned ===== */
.queue-timeline {
  position: relative;
  height: 340px;
  display: flex;
  flex-direction: column;
}

/* ─── Toolbar (legend + zoom) ─── */
.queue-timeline__toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 24px 10px;
  border-bottom: 1px solid rgba(148, 163, 184, 0.12);
}

.queue-timeline__legend {
  display: flex;
  gap: 16px;
}

.queue-timeline__legend-item {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  font-weight: 500;
  color: rgba(15, 23, 42, 0.6);
}

.queue-timeline__legend-swatch {
  width: 12px;
  height: 8px;
  border-radius: 3px;
}

.queue-timeline__legend-swatch--running { background: #2080f0; }
.queue-timeline__legend-swatch--ready   { background: #38bdf8; }
.queue-timeline__legend-swatch--waiting { background: #7dd3fc; }

/* ─── Scroll wrapper ─── */
.queue-timeline__scroll {
  padding: 0;
  flex: 1;
}

.queue-timeline__container {
  position: relative;
  padding: 0 24px;
  display: flex;
  flex-direction: column;
  min-height: 100%;
}

/* ─── Time axis ─── */
.queue-timeline__axis {
  position: relative;
  height: 36px;
  border-bottom: 1px solid rgba(148, 163, 184, 0.18);
}

.queue-timeline__tick {
  position: absolute;
  top: 0;
  transform: translateX(-50%);
  font-size: 11px;
  font-variant-numeric: tabular-nums;
  color: rgba(15, 23, 42, 0.48);
  white-space: nowrap;
  line-height: 1;
  padding-bottom: 8px;
}

.queue-timeline__tick::after {
  content: '';
  position: absolute;
  bottom: 0;
  left: 50%;
  width: 1px;
  height: 6px;
  background: rgba(15, 23, 42, 0.14);
  transform: translateX(-50%);
}

/* ─── Content area (positions gridlines + now marker) ─── */
.queue-timeline__content {
  position: relative;
  flex: 1;
  min-height: 80px;
  padding-bottom: 8px;
}

/* ─── Vertical gridlines ─── */
.queue-timeline__gridline {
  position: absolute;
  top: 0;
  bottom: 0;
  width: 1px;
  background: repeating-linear-gradient(
    to bottom,
    rgba(148, 163, 184, 0.1) 0px,
    rgba(148, 163, 184, 0.1) 4px,
    transparent 4px,
    transparent 8px
  );
  transform: translateX(-50%);
  pointer-events: none;
  z-index: 0;
}

/* ─── Now marker ─── */
.queue-timeline__now-marker {
  position: absolute;
  top: 0;
  bottom: 0;
  width: 2px;
  background: linear-gradient(to bottom, #f43f5e, rgba(244, 63, 94, 0.2));
  z-index: 2;
  transform: translateX(-50%);
  pointer-events: none;
}

.queue-timeline__now-label {
  position: absolute;
  top: 4px;
  left: 50%;
  transform: translateX(-50%);
  font-size: 10px;
  font-weight: 600;
  color: #f43f5e;
  white-space: nowrap;
  background: rgba(255, 241, 242, 0.95);
  padding: 2px 8px;
  border-radius: 999px;
  border: 1px solid rgba(244, 63, 94, 0.18);
  letter-spacing: 0.3px;
  text-transform: uppercase;
}

/* ─── Empty state ─── */
.queue-timeline__empty {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 120px;
  position: relative;
  z-index: 1;
}

/* ─── Group (Running / Ready / Waiting) ─── */
.queue-timeline__group {
  position: relative;
  z-index: 3;
}

.queue-timeline__group + .queue-timeline__group {
  border-top: 1px solid rgba(148, 163, 184, 0.1);
}

.queue-timeline__group-header {
  padding: 8px 0 4px;
}

.queue-timeline__group-badge {
  display: inline-flex;
  align-items: center;
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.2px;
  padding: 2px 10px;
  border-radius: 999px;
  line-height: 1.5;
}

.queue-timeline__group-badge--running {
  background: rgba(32, 128, 240, 0.08);
  color: #2080f0;
}

.queue-timeline__group-badge--ready {
  background: rgba(56, 189, 248, 0.08);
  color: #0ea5e9;
}

.queue-timeline__group-badge--waiting {
  background: rgba(125, 211, 252, 0.08);
  color: #38bdf8;
}

/* ─── Group track area (bar container) ─── */
.queue-timeline__group-tracks {
  position: relative;
  padding: 2px 0;
}

/* ─── Task bars ─── */
.queue-timeline__task-bar {
  --queue-timeline-bar-fill: linear-gradient(180deg, rgba(226, 232, 240, 0.92), rgba(203, 213, 225, 0.72));
  --arrow-depth: 10px;
  position: absolute;
  height: 28px;
  cursor: pointer;
  display: flex;
  align-items: center;
  padding: 0 10px;
  padding-right: calc(10px + var(--arrow-depth));
  font-size: 12px;
  white-space: nowrap;
  min-width: 56px;
  background: var(--queue-timeline-bar-fill);
  -webkit-mask-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 200 28' preserveAspectRatio='none'%3E%3Cpath d='M4,4 H182 L196,14 L182,24 H4Z' fill='white' stroke='white' stroke-width='8' stroke-linejoin='round'/%3E%3C/svg%3E");
  mask-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 200 28' preserveAspectRatio='none'%3E%3Cpath d='M4,4 H182 L196,14 L182,24 H4Z' fill='white' stroke='white' stroke-width='8' stroke-linejoin='round'/%3E%3C/svg%3E");
  -webkit-mask-size: 100% 100%;
  mask-size: 100% 100%;
  transition: filter 0.15s, background 0.15s;
}

.queue-timeline__task-bar--running {
  --queue-timeline-bar-fill: linear-gradient(180deg, rgba(32, 128, 240, 0.92), rgba(32, 128, 240, 0.6));
  color: #0c4a6e;
  min-width: 140px;
  width: 140px;
}

.queue-timeline__task-bar--running:hover {
  --queue-timeline-bar-fill: linear-gradient(180deg, rgba(21, 114, 214, 0.96), rgba(32, 128, 240, 0.68));
}

.queue-timeline__task-bar--ready {
  --queue-timeline-bar-fill: linear-gradient(180deg, rgba(56, 189, 248, 0.88), rgba(56, 189, 248, 0.55));
  color: #0c4a6e;
  min-width: 120px;
  width: 120px;
}

.queue-timeline__task-bar--ready:hover {
  --queue-timeline-bar-fill: linear-gradient(180deg, rgba(14, 165, 233, 0.92), rgba(56, 189, 248, 0.62));
}

.queue-timeline__task-bar--waiting {
  --queue-timeline-bar-fill: linear-gradient(180deg, rgba(125, 211, 252, 0.8), rgba(125, 211, 252, 0.48));
  color: #0c4a6e;
  min-width: 120px;
  width: 120px;
}

.queue-timeline__task-bar--waiting:hover {
  --queue-timeline-bar-fill: linear-gradient(180deg, rgba(56, 189, 248, 0.86), rgba(125, 211, 252, 0.55));
}

.queue-timeline__bar-label {
  position: relative;
  font-weight: 500;
  overflow: hidden;
  text-overflow: ellipsis;
  text-shadow: none;
}

/* ─── Timeline tooltip ─── */
.queue-timeline__has-tooltip {
  position: absolute;
}

.queue-timeline__has-tooltip:hover {
  z-index: 50;
}

.queue-timeline__tooltip {
  position: fixed;
  background: #1e293b;
  color: #f8fafc;
  font-size: 12px;
  padding: 8px 12px;
  border-radius: 8px;
  white-space: pre-line;
  pointer-events: none;
  z-index: 9999;
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.22);
  max-width: 280px;
  line-height: 1.5;
}

@media (max-width: 768px) {
  .queue-kanban {
    grid-template-columns: 1fr;
  }

  .monitor-card__header {
    flex-direction: column;
    align-items: flex-start;
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

@media (hover: none) {
  .monitor-summary-card:hover {
    transform: none;
    box-shadow: 0 1px 3px rgba(15, 23, 42, 0.04);
    border-color: rgba(15, 23, 42, 0.06);
  }
}
</style>
