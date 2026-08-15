<template>
  <div class="dashboard" data-testid="tasks-page">
    <n-spin :show="initialLoading" :description="t('common.loadingTasks')">
      <div class="page-hero">
        <PageHeader
          data-testid="tasks-header"
          root-class="dashboard__hero"
          title-class="dashboard__title"
          subtitle-class="dashboard__subtitle"
          actions-class="dashboard__filters"
          :title="t('dashboard.title')"
          :subtitle="t('dashboard.subtitle')"
        >
          <template #actions>
            <n-button @click="refreshTasks" :loading="loading" size="small" class="dashboard__refresh">
              {{ t('common.refresh') }}
            </n-button>
          </template>
        </PageHeader>

        <n-grid
          v-if="hasLoadedOnce"
          data-testid="tasks-summary"
          :cols="isMobile ? 2 : 4"
          :x-gap="16"
          :y-gap="16"
        >
          <n-gi v-for="item in summaryItems" :key="item.label">
            <SummaryCard
              :label="item.label"
              :value="item.value"
              :icon="item.icon"
              :accent="item.accent"
              data-testid="tasks-summary-card"
              card-class="dashboard-summary-card"
              label-class="dashboard-summary-card__label"
              value-class="dashboard-summary-card__value"
            />
          </n-gi>
        </n-grid>
      </div>
      <n-space vertical :size="16">
        <FilterToolbar
          :config="filterConfig"
          :filters="filterState.filters.value"
          :sort="filterState.sort.value"
          :visible-columns="filterState.visibleColumns.value"
          :active-filter-count="filterState.activeFilterCount.value"
          :has-active-filters="filterState.hasActiveFilters.value"
          :result-count="totalTasks"
          :search-placeholder="t('filter.search')"
          :search-value="searchTerm"
          :search-min-length="2"
          @add-filter="filterState.addFilter"
          @remove-filter="filterState.removeFilter"
          @clear-all-filters="filterState.clearAllFilters"
          @set-sort="filterState.setSort"
          @reset-sort="filterState.resetSort"
          @toggle-column="filterState.toggleColumn"
          @reset-columns="filterState.resetColumns"
          @search="onSearch"
        >
          <template v-if="currentInitiatorValue" #quick-filters>
            <n-button
              size="small"
              :type="isMyFilterActive ? 'primary' : 'default'"
              :secondary="!isMyFilterActive"
              @click="toggleMyFilter"
            >
              <template #icon>
                <n-icon size="14"><PersonOutline /></n-icon>
              </template>
              {{ t('filter.mine') }}
            </n-button>
          </template>
        </FilterToolbar>

        <n-card class="dashboard-table-card" :bordered="false" data-testid="tasks-table-card">
          <div class="dashboard-table-shell">
            <n-data-table
              data-testid="tasks-table"
              :columns="columns"
              :data="tasks"
              :loading="tableLoading"
              :row-key="(row: Task) => row.id"
              :row-props="getRowProps"
              :pagination="pagination"
              :scroll-x="tableScrollX"
              remote
              :bordered="false"
            />
          </div>
        </n-card>
      </n-space>
    </n-spin>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, h, watch, computed, nextTick } from 'vue'
import { NButton, NSpace, NCard, NDataTable, NTag, NGrid, NGi, NSpin, NIcon, useMessage, DataTableColumns } from 'naive-ui'
import { useRouter, useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'
import {
  getProjects,
  getStats,
  getTaskFilterOptions,
  getTasksPaginated,
  snapshotInitiatorValue,
  type InitiatorFilterOption,
  type SimpleFilterOption,
  type Project,
  type Task,
} from '../api'
import { authState } from '../auth'
import PageHeader from '../components/PageHeader.vue'
import SummaryCard from '../components/SummaryCard.vue'
import FilterToolbar from '../components/filter/FilterToolbar.vue'
import { useFilterSort, type FilterSortConfig } from '../composables/useFilterSort'
import {
  buildListRouteQuery,
  parseAllowedQueryValue,
  parsePositiveIntegerQueryValue,
  readListQueryState,
  routeQueriesEqual,
} from '../composables/listQueryState'
import { useBreakpoints } from '../composables/useBreakpoints'
import { usePolling } from '../composables/usePolling'
import { formatDateTimeUtc8Compact, parseUtcDate } from '../utils/datetime'
import { formatDurationMs, formatPriority, getProjectLabel as _getProjectLabel } from '../utils/format'
import { EllipseOutline, FolderOpenOutline, FlagOutline, PersonOutline, CalendarOutline, GitMergeOutline, TimeOutline, GridOutline, CheckmarkCircleOutline, PlayCircleOutline, GitNetworkOutline } from '@vicons/ionicons5'

const router = useRouter()
const route = useRoute()
const message = useMessage()
const { t } = useI18n()
const { isMobile } = useBreakpoints()

const tasks = ref<Task[]>([])
const projects = ref<Project[]>([])
const projectOptionsLoading = ref(false)
const projectOptionsError = ref(false)
const initiatorFilterOptions = ref<InitiatorFilterOption[]>([])
const initiatorOptionsLoading = ref(false)
const initiatorOptionsError = ref(false)
const harnessFilterOptions = ref<SimpleFilterOption[]>([])
const harnessOptionsLoading = ref(false)
const harnessOptionsError = ref(false)
const loading = ref(false)
const hasLoadedOnce = ref(false)

const currentPage = ref(1)
const pageSize = ref(20)
const totalTasks = ref(0)

const statsTotal = ref(0)
const statsRunning = ref(0)
const statsCompleted = ref(0)
const statsPending = ref(0)

const TASK_STATUS_VALUES = [
  'pending',
  'queued',
  'running',
  'completed',
  'failed',
  'cancelled',
] as const
const PRIORITY_VALUES = ['0', '1', '2'] as const
const BOOLEAN_FILTER_VALUES = ['true', 'false'] as const

function initiatorOptionLabel(option: InitiatorFilterOption): string {
  if (option.kind === 'unknown') return t('filter.unknownInitiator')
  return option.username || t('filter.unknownInitiator')
}

function initiatorOptions() {
  const options: { label: string; value: string; truncateLabel?: boolean }[] = initiatorFilterOptions.value.map((option) => ({
    label: initiatorOptionLabel(option),
    value: option.value,
    truncateLabel: true,
  }))
  const selected = filterState.filters.value.initiator
  if (Array.isArray(selected)) {
    for (const value of selected) {
      if (!options.some((option) => option.value === value)) {
        options.push({
          label: String(value).replace(/^(?:username|snapshot):/, ''),
          value,
          truncateLabel: true,
        })
      }
    }
  }
  return options
}

const filterConfig: FilterSortConfig = {
  storageKey: 'codify:filters:tasks',
  filterFields: [
    {
      key: 'status',
      label: 'filter.status',
      icon: EllipseOutline,
      type: 'multi-select',
      parseValue: (value) => parseAllowedQueryValue(value, TASK_STATUS_VALUES),
      options: () => [
        { label: t('status.pending'), value: 'pending', color: '#888' },
        { label: t('status.queued'), value: 'queued', color: '#4080ff' },
        { label: t('status.running'), value: 'running', color: '#f0a020' },
        { label: t('status.completed'), value: 'completed', color: '#18a058' },
        { label: t('status.failed'), value: 'failed', color: '#d03050' },
        { label: t('status.cancelled'), value: 'cancelled', color: '#888' },
      ],
    },
    {
      key: 'project_id',
      label: 'filter.project',
      icon: FolderOpenOutline,
      type: 'multi-select',
      parseValue: parsePositiveIntegerQueryValue,
      searchable: true,
      options: () => projects.value.map((p) => ({ label: p.path_with_namespace, value: p.id })),
      optionsLoading: () => projectOptionsLoading.value,
      optionsError: () => projectOptionsError.value,
      optionsRetry: fetchProjects,
    },
    {
      key: 'priority',
      label: 'filter.priority',
      icon: FlagOutline,
      type: 'multi-select',
      parseValue: (value) => parseAllowedQueryValue(value, PRIORITY_VALUES),
      options: () => [
        { label: 'P0', value: '0', color: '#d03050' },
        { label: 'P1', value: '1', color: '#f0a020' },
        { label: 'P2', value: '2', color: '#18a058' },
      ],
    },
    {
      key: 'harness',
      label: 'filter.harness',
      icon: GitNetworkOutline,
      type: 'multi-select',
      options: () => harnessFilterOptions.value.map((o) => ({
        label: o.label,
        value: o.value,
        count: o.count,
      })),
      optionsLoading: () => harnessOptionsLoading.value,
      optionsError: () => harnessOptionsError.value,
      optionsRetry: fetchFilterOptions,
    },
    {
      key: 'initiator',
      label: 'filter.initiator',
      icon: PersonOutline,
      type: 'multi-select',
      searchable: true,
      options: initiatorOptions,
      optionsLoading: () => initiatorOptionsLoading.value,
      optionsError: () => initiatorOptionsError.value,
      optionsRetry: fetchFilterOptions,
    },
    {
      key: 'has_mr',
      label: 'filter.hasMr',
      icon: GitMergeOutline,
      type: 'single-select',
      parseValue: (value) => parseAllowedQueryValue(value, BOOLEAN_FILTER_VALUES),
      options: () => [
        { label: t('filter.hasMrYes'), value: 'true' },
        { label: t('filter.hasMrNo'), value: 'false' },
      ],
    },
    {
      key: 'created',
      label: 'filter.created',
      icon: CalendarOutline,
      type: 'date-range',
      apiParam: 'created_after,created_before',
    },
    {
      key: 'scheduled',
      label: 'filter.scheduled',
      icon: TimeOutline,
      type: 'date-range',
      apiParam: 'scheduled_after,scheduled_before',
    },
  ],
  sortFields: [
    { key: 'created_at', label: 'filter.sortCreated' },
    { key: 'priority', label: 'filter.sortPriority' },
    { key: 'status', label: 'filter.sortStatus' },
    { key: 'total_changes', label: 'filter.sortChanges' },
    { key: 'input_tokens', label: 'filter.sortTokens' },
    { key: 'duration', label: 'filter.sortDuration' },
  ],
  columns: [
    { key: 'id', label: 'dashboard.id', defaultVisible: true, alwaysVisible: true },
    { key: 'user_prompt', label: 'dashboard.prompt', defaultVisible: true },
    { key: 'project', label: 'dashboard.project', defaultVisible: true },
    { key: 'initiator_username', label: 'dashboard.initiator', defaultVisible: true },
    { key: 'issue', label: 'dashboard.issue', defaultVisible: false },
    { key: 'status', label: 'dashboard.status', defaultVisible: true },
    { key: 'priority', label: 'dashboard.priority', defaultVisible: true },
    { key: 'branch_name', label: 'dashboard.branch', defaultVisible: false },
    { key: 'merge_request_url', label: 'dashboard.mergeRequest', defaultVisible: false },
    { key: 'changes', label: 'common.changes', defaultVisible: true },
    { key: 'duration', label: 'dashboard.duration', defaultVisible: true },
    { key: 'tokens', label: 'analytics.tokens', defaultVisible: false },
    { key: 'created_at', label: 'common.created', defaultVisible: true },
    { key: 'scheduled_at', label: 'dashboard.scheduled', defaultVisible: false },
  ],
  defaultSort: { field: 'created_at', order: 'desc' },
  persistence: { filters: false, sort: false, columns: true },
}

function getTaskQueryState() {
  const state = readListQueryState(filterConfig, route.query, { pageSize: 20, searchMinLength: 2 })
  if (!state.filters.initiator && route.query.initiator_username) {
    state.filters.initiator = String(route.query.initiator_username)
      .split(',')
      .map((username) => username.trim())
      .filter(Boolean)
      .map(snapshotInitiatorValue)
  }
  return state
}

const initialQueryState = getTaskQueryState()
currentPage.value = initialQueryState.page
pageSize.value = initialQueryState.pageSize
const filterState = useFilterSort(
  filterConfig,
  initialQueryState.filters,
  initialQueryState.sort,
)
const searchTerm = ref(initialQueryState.search)

const currentInitiatorValue = computed(() => {
  if (authState.user?.id) return `user:${authState.user.id}`
  return authState.user?.username ? snapshotInitiatorValue(authState.user.username) : null
})

const isMyFilterActive = computed(() => {
  const val = filterState.filters.value.initiator
  return Array.isArray(val) && val.length === 1 && val[0] === currentInitiatorValue.value
})

function toggleMyFilter() {
  if (isMyFilterActive.value) {
    filterState.removeFilter('initiator')
  } else if (currentInitiatorValue.value) {
    filterState.addFilter('initiator', [currentInitiatorValue.value])
  }
}

let applyingRouteQuery = false

function currentRouteQuery() {
  return buildListRouteQuery(
    filterState.apiParams.value,
    searchTerm.value,
    currentPage.value,
    pageSize.value,
  )
}

function syncRouteQuery() {
  const query = currentRouteQuery()
  if (!routeQueriesEqual(route.query, query)) {
    void router.replace({ query })
  }
}

function onSearch(term: string) {
  searchTerm.value = term
  currentPage.value = 1
  syncRouteQuery()
  fetchTasks()
}

watch([() => filterState.filters.value, () => filterState.sort.value], () => {
  if (applyingRouteQuery) return
  currentPage.value = 1
  syncRouteQuery()
  fetchTasks()
}, { deep: true })

watch(() => route.query, async () => {
  if (routeQueriesEqual(route.query, currentRouteQuery())) return
  applyingRouteQuery = true
  const state = getTaskQueryState()
  filterState.filters.value = state.filters
  filterState.sort.value = state.sort
  searchTerm.value = state.search
  currentPage.value = state.page
  pageSize.value = state.pageSize
  await nextTick()
  applyingRouteQuery = false
  syncRouteQuery()
  fetchTasks()
}, { deep: true })

const pagination = computed(() => ({
  page: currentPage.value,
  pageSize: pageSize.value,
  itemCount: totalTasks.value,
  showSizePicker: true,
  pageSizes: [20, 50, 100],
  'onUpdate:page': (page: number) => {
    currentPage.value = page
    syncRouteQuery()
    fetchTasks()
  },
  'onUpdate:pageSize': (size: number) => {
    pageSize.value = size
    currentPage.value = 1
    syncRouteQuery()
    fetchTasks()
  },
}))

const statusColors: Record<string, 'default' | 'info' | 'warning' | 'success' | 'error'> = {
  pending: 'default',
  queued: 'info',
  running: 'warning',
  completed: 'success',
  failed: 'error',
  cancelled: 'default'
}

function getProjectLabel(task: Task): string {
  return _getProjectLabel(task, t('dashboard.projectFallback', { id: task.project_id }))
}

function renderExternalLink(label: string, href?: string | null) {
  if (!href) {
    return label
  }
  return h('a', { href, target: '_blank', rel: 'noopener noreferrer', class: 'app-link' }, label)
}

function getProjectSecondaryLabel(task: Task): string {
  const issueLabel = task.issue ? `#${task.issue.id}` : '-'
  return `${getProjectLabel(task)} · ${issueLabel}`
}

function getInitiatorLabel(task: Task): string {
  return task.initiator_username?.trim() || '-'
}

function formatPrompt(value?: string | null): string {
  return value?.trim() || '-'
}

const secondaryTextStyle = { fontSize: '11px', color: 'rgba(15,23,42,0.45)', marginTop: '2px', lineHeight: '1.4' }

function formatNumber(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) return '—'
  return Math.round(value).toLocaleString()
}

function formatCompactDateTime(value?: string | null): string {
  if (!value) {
    return '-'
  }

  return formatDateTimeUtc8Compact(value)
}

function goToTask(task: Task) {
  router.push({ name: 'TaskView', params: { id: task.id } })
}

function isInteractiveTarget(target: EventTarget | null): boolean {
  if (!(target instanceof Element)) {
    return false
  }

  return Boolean(
    target.closest('a, button, input, textarea, select, summary, [role="button"], .n-button, .n-base-selection')
  )
}

function getRowProps(row: Task) {
  return {
    style: 'cursor: pointer;',
    onClick: (event: MouseEvent) => {
      if (isInteractiveTarget(event.target)) {
        return
      }
      goToTask(row)
    }
  }
}

const allDesktopColumns = computed<DataTableColumns<Task>>(() => {
  const renderStatus = (row: Task) =>
    h(NTag, { type: statusColors[row.status], size: 'small' }, () => t(`status.${row.status}`))

  return [
    {
      title: t('dashboard.id'),
      key: 'id',
      width: 52
    },
    {
      title: t('dashboard.prompt'),
      key: 'user_prompt',
      width: 180,
      ellipsis: {
        tooltip: {
          style: { maxWidth: '420px', whiteSpace: 'pre-wrap', wordBreak: 'break-word' }
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        } as any
      },
      render: (row) => formatPrompt(row.user_prompt)
    },
    {
      title: t('dashboard.project'),
      key: 'project',
      width: 156,
      ellipsis: { tooltip: true },
      render: (row) =>
        h('div', { style: 'line-height: 1.4' }, [
          h('div', renderExternalLink(getProjectLabel(row), row.project_url)),
          h(
            'div',
            { style: 'font-size: 12px; color: #888; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;' },
            `ID: ${row.project_id}`
          )
        ])
    },
    {
      title: t('dashboard.initiator'),
      key: 'initiator_username',
      width: 112,
      ellipsis: { tooltip: true },
      render: (row) => getInitiatorLabel(row)
    },
    {
      title: t('dashboard.issue'),
      key: 'issue',
      width: 100,
      ellipsis: { tooltip: true },
      render: (row) => {
        if (!row.issue) return '-'
        return h(
          'a',
          {
            style: 'cursor: pointer; color: var(--n-text-color);',
            onClick: (e: MouseEvent) => {
              e.stopPropagation()
              router.push(`/issues/${row.issue!.id}`)
            }
          },
          `#${row.issue.id} ${row.issue.title}`
        )
      }
    },
    {
      title: t('dashboard.status'),
      key: 'status',
      width: 84,
      render: renderStatus
    },
    {
      title: t('dashboard.priority'),
      key: 'priority',
      width: 84,
      render: (row) => formatPriority(row.priority)
    },
    {
      title: t('dashboard.branch'),
      key: 'branch_name',
      width: 120,
      ellipsis: { tooltip: true },
      render: (row) => (row.issue?.branch_name ? row.issue.branch_name : '-')
    },
    {
      title: t('dashboard.mergeRequest'),
      key: 'merge_request_url',
      width: 72,
      render: (row) => {
        const mrUrl = row.issue?.merge_request_url
        const mrIid = row.issue?.merge_request_iid
        if (!mrUrl) return '-'
        const label = mrIid ? `!${mrIid}` : 'MR'
        return h(
          'a',
          { href: mrUrl, target: '_blank', rel: 'noopener noreferrer', class: 'app-link' },
          label
        )
      }
    },
    {
      title: t('common.changes'),
      key: 'changes',
      width: 110,
      render: (row) => {
        const total = (row.additions || 0) + (row.deletions || 0)
        if (!total) return '—'
        return h('div', [
          h('div', String(total)),
          h('div', { style: secondaryTextStyle }, t('analytics.changeBreakdown', { additions: row.additions || 0, deletions: row.deletions || 0 })),
        ])
      }
    },
    {
      title: t('dashboard.duration'),
      key: 'duration',
      width: 80,
      render: (row) => {
        if (!row.started_at) return '—'
        const started = parseUtcDate(row.started_at).getTime()
        const ended = row.completed_at ? parseUtcDate(row.completed_at).getTime() : Date.now()
        if (!started || !ended || ended < started) return '—'
        return formatDurationMs(ended - started)
      }
    },
    {
      title: t('analytics.tokens'),
      key: 'tokens',
      width: 140,
      render: (row) => {
        const input = row.input_tokens || 0
        const output = row.output_tokens || 0
        if (!input && !output) return '—'
        const total = input + output
        return h('div', [
          h('div', formatNumber(total)),
          h('div', { style: secondaryTextStyle }, t('analytics.tokenInputLine', { value: formatNumber(input) })),
          h('div', { style: secondaryTextStyle }, t('analytics.tokenOutputLine', { value: formatNumber(output) })),
        ])
      }
    },
    {
      title: t('common.created'),
      key: 'created_at',
      width: 118,
      render: (row) => formatCompactDateTime(row.created_at)
    },
    {
      title: t('dashboard.scheduled'),
      key: 'scheduled_at',
      width: 118,
      render: (row) => formatCompactDateTime(row.scheduled_at)
    }
  ]
})

const columns = computed<DataTableColumns<Task>>(() => {
  if (isMobile.value) {
    const renderStatus = (row: Task) =>
      h(NTag, { type: statusColors[row.status], size: 'small' }, () => t(`status.${row.status}`))

    return [
      {
        title: t('dashboard.id'),
        key: 'id',
        width: 45
      },
      {
        title: t('dashboard.task'),
        key: 'task_info',
        render: (row) =>
          h('div', { style: 'line-height: 1.4' }, [
            h(
              'div',
              {
                style:
                  'font-size: 12px; color: #888; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 140px'
              },
              getProjectSecondaryLabel(row)
            ),
            h(
              'div',
              {
                style:
                  'font-size: 12px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 120px'
              },
              row.issue?.branch_name ? renderExternalLink(row.issue.branch_name) : '-'
            )
          ])
      },
      {
        title: t('dashboard.status'),
        key: 'status',
        width: 85,
        render: renderStatus
      }
    ]
  }

  const visible = filterState.visibleColumns.value
  return allDesktopColumns.value.filter((col) => 'key' in col && visible.includes(col.key as string))
})

const tableScrollX = computed(() => {
  const width = columns.value.reduce((total, col) => {
    const columnWidth = 'width' in col && typeof col.width === 'number' ? col.width : 160
    return total + columnWidth
  }, 0)
  return Math.max(width, isMobile.value ? 360 : 960)
})

const initialLoading = computed(() => loading.value && !hasLoadedOnce.value)
const tableLoading = computed(() => loading.value && hasLoadedOnce.value)

const summaryItems = computed(() => [
  { label: t('dashboard.visibleTasks'), value: String(statsTotal.value), icon: GridOutline, accent: 'blue' as const },
  { label: t('dashboard.running'), value: String(statsRunning.value), icon: PlayCircleOutline, accent: 'green' as const },
  { label: t('dashboard.pendingQueued'), value: String(statsPending.value), icon: TimeOutline, accent: 'amber' as const },
  { label: t('dashboard.completed'), value: String(statsCompleted.value), icon: CheckmarkCircleOutline, accent: 'purple' as const },
])

async function fetchTasks(options: { skipIfLoading?: boolean } = {}) {
  if (options.skipIfLoading && loading.value) return
  const requestId = ++latestTaskRequestId
  loading.value = true
  const params: Parameters<typeof getTasksPaginated>[0] = {
    page: currentPage.value,
    page_size: pageSize.value,
    ...filterState.apiParams.value,
  }
  if (searchTerm.value && searchTerm.value.length >= 2) {
    params.search = searchTerm.value
  }
  try {
    const result = await getTasksPaginated(params)
    if (requestId !== latestTaskRequestId) return
    tasks.value = result.items
    totalTasks.value = result.total
  } catch (error) {
    if (requestId === latestTaskRequestId) {
      message.error(t('dashboard.failedToFetchTasks'))
    }
  } finally {
    if (requestId === latestTaskRequestId) {
      hasLoadedOnce.value = true
      loading.value = false
    }
  }
}

let latestTaskRequestId = 0

async function fetchFilterOptions() {
  initiatorOptionsLoading.value = true
  initiatorOptionsError.value = false
  harnessOptionsLoading.value = true
  harnessOptionsError.value = false
  try {
    const result = await getTaskFilterOptions()
    initiatorFilterOptions.value = result.initiators
    harnessFilterOptions.value = result.harnesses ?? []
  } catch {
    initiatorOptionsError.value = true
    harnessOptionsError.value = true
  } finally {
    initiatorOptionsLoading.value = false
    harnessOptionsLoading.value = false
  }
}

async function fetchStats() {
  try {
    const stats = await getStats()
    statsTotal.value = stats.total
    statsRunning.value = stats.running
    statsCompleted.value = stats.completed
    statsPending.value = stats.pending + stats.queued
  } catch {
    // Stats are supplementary; don't block UI
  }
}

async function fetchProjects() {
  if (projectOptionsLoading.value) return
  projectOptionsLoading.value = true
  projectOptionsError.value = false
  try {
    projects.value = await getProjects()
  } catch {
    projectOptionsError.value = true
  } finally {
    projectOptionsLoading.value = false
  }
}

function refreshTasks() {
  fetchTasks()
  fetchStats()
}

const { start: startPolling } = usePolling(
  () => {
    fetchTasks({ skipIfLoading: true })
    fetchStats()
  },
  { interval: 15_000, immediate: false }
)

onMounted(() => {
  syncRouteQuery()
  fetchProjects()
  fetchFilterOptions()
  fetchStats()
  fetchTasks()
  startPolling()
})
</script>

<style scoped>
.dashboard {
  max-width: var(--app-page-max-width);
  min-width: 0;
}

.dashboard__filters {
  display: inline-flex;
  align-items: center;
  justify-content: flex-end;
  gap: 8px;
  flex-wrap: wrap;
}

.dashboard-summary-card {
  min-height: 100%;
}

.dashboard-table-card {
  border-radius: var(--app-card-radius);
  min-width: 0;
  overflow: hidden;
}

.dashboard-table-card :deep(.n-card__content) {
  min-width: 0;
}

.dashboard-table-shell {
  width: 100%;
  min-width: 0;
  overflow-x: auto;
}

@media (max-width: 768px) {
  .dashboard__filters {
    width: 100%;
    justify-content: flex-start;
  }

  .dashboard__filters :deep(.n-button) {
    width: 100%;
  }
}
</style>
