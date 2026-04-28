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
          @add-filter="filterState.addFilter"
          @remove-filter="filterState.removeFilter"
          @clear-all-filters="filterState.clearAllFilters"
          @set-sort="filterState.setSort"
          @reset-sort="filterState.resetSort"
          @toggle-column="filterState.toggleColumn"
          @reset-columns="filterState.resetColumns"
          @search="onSearch"
        />

        <n-card class="dashboard-table-card" :bordered="false" data-testid="tasks-table-card">
          <n-data-table
            data-testid="tasks-table"
            :columns="columns"
            :data="tasks"
            :loading="tableLoading"
            :row-key="(row: Task) => row.id"
            :row-props="getRowProps"
            :pagination="pagination"
            remote
            :bordered="false"
          />
        </n-card>
      </n-space>
    </n-spin>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, h, watch, computed } from 'vue'
import { NButton, NSpace, NCard, NDataTable, NTag, NGrid, NGi, NSpin, useMessage, DataTableColumns } from 'naive-ui'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { getProjects, getTasksPaginated, getStats, type Project, type Task } from '../api'
import PageHeader from '../components/PageHeader.vue'
import SummaryCard from '../components/SummaryCard.vue'
import FilterToolbar from '../components/filter/FilterToolbar.vue'
import { useFilterSort, type FilterSortConfig } from '../composables/useFilterSort'
import { useBreakpoints } from '../composables/useBreakpoints'
import { usePolling } from '../composables/usePolling'
import { formatDateTimeUtc8Compact } from '../utils/datetime'
import { formatPriority, getProjectLabel as _getProjectLabel } from '../utils/format'
import { EllipseOutline, FolderOpenOutline, FlagOutline, PersonOutline, CalendarOutline, GitMergeOutline, TimeOutline, GridOutline, CheckmarkCircleOutline, PlayCircleOutline } from '@vicons/ionicons5'

const router = useRouter()
const message = useMessage()
const { t } = useI18n()
const { isMobile } = useBreakpoints()

const tasks = ref<Task[]>([])
const projects = ref<Project[]>([])
const knownInitiators = ref<Set<string>>(new Set())
const loading = ref(false)
const hasLoadedOnce = ref(false)

const currentPage = ref(1)
const pageSize = ref(20)
const totalTasks = ref(0)

const statsTotal = ref(0)
const statsRunning = ref(0)
const statsCompleted = ref(0)
const statsPending = ref(0)

const initiatorOptions = computed(() => {
  const values = Array.from(knownInitiators.value).sort((left, right) => left.localeCompare(right))
  return values.map((username) => ({
    label: username,
    value: username
  }))
})

const filterConfig: FilterSortConfig = {
  storageKey: 'codify:filters:tasks',
  filterFields: [
    {
      key: 'status',
      label: 'filter.status',
      icon: EllipseOutline,
      type: 'multi-select',
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
      options: () => projects.value.map((p) => ({ label: p.path_with_namespace, value: p.id })),
    },
    {
      key: 'priority',
      label: 'filter.priority',
      icon: FlagOutline,
      type: 'multi-select',
      options: () => [
        { label: 'P0', value: '0', color: '#d03050' },
        { label: 'P1', value: '1', color: '#f0a020' },
        { label: 'P2', value: '2', color: '#18a058' },
      ],
    },
    {
      key: 'initiator_username',
      label: 'filter.initiator',
      icon: PersonOutline,
      type: 'multi-select',
      options: () => initiatorOptions.value.map((o) => ({ label: o.label, value: o.value })),
    },
    {
      key: 'has_mr',
      label: 'filter.hasMr',
      icon: GitMergeOutline,
      type: 'single-select',
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
  ],
  columns: [
    { key: 'id', label: 'dashboard.id', defaultVisible: true, alwaysVisible: true },
    { key: 'user_prompt', label: 'dashboard.task', defaultVisible: true, alwaysVisible: true },
    { key: 'project', label: 'dashboard.project', defaultVisible: true },
    { key: 'initiator_username', label: 'dashboard.initiator', defaultVisible: true },
    { key: 'issue', label: 'dashboard.issue', defaultVisible: false },
    { key: 'status', label: 'dashboard.status', defaultVisible: true },
    { key: 'priority', label: 'dashboard.priority', defaultVisible: true },
    { key: 'branch_name', label: 'dashboard.branch', defaultVisible: false },
    { key: 'merge_request_url', label: 'dashboard.mergeRequest', defaultVisible: false },
    { key: 'changes', label: 'common.changes', defaultVisible: true },
    { key: 'tokens', label: 'analytics.tokens', defaultVisible: false },
    { key: 'created_at', label: 'common.created', defaultVisible: true },
    { key: 'scheduled_at', label: 'dashboard.scheduled', defaultVisible: false },
  ],
  defaultSort: { field: 'created_at', order: 'desc' },
}

const filterState = useFilterSort(filterConfig)
const searchTerm = ref('')

function onSearch(term: string) {
  searchTerm.value = term
  currentPage.value = 1
  fetchTasks()
}

watch([() => filterState.filters.value, () => filterState.sort.value], () => {
  currentPage.value = 1
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
    fetchTasks()
  },
  'onUpdate:pageSize': (size: number) => {
    pageSize.value = size
    currentPage.value = 1
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
      title: t('createTask.prompt'),
      key: 'user_prompt',
      ellipsis: { tooltip: true },
      render: (row) => row.user_prompt || '-',
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
const initialLoading = computed(() => loading.value && !hasLoadedOnce.value)
const tableLoading = computed(() => loading.value && hasLoadedOnce.value)

const summaryItems = computed(() => [
  { label: t('dashboard.visibleTasks'), value: String(statsTotal.value), icon: GridOutline, accent: 'blue' as const },
  { label: t('dashboard.running'), value: String(statsRunning.value), icon: PlayCircleOutline, accent: 'green' as const },
  { label: t('dashboard.pendingQueued'), value: String(statsPending.value), icon: TimeOutline, accent: 'amber' as const },
  { label: t('dashboard.completed'), value: String(statsCompleted.value), icon: CheckmarkCircleOutline, accent: 'purple' as const },
])

async function fetchTasks() {
  if (loading.value) return
  loading.value = true
  try {
    const params: Record<string, any> = {
      page: currentPage.value,
      page_size: pageSize.value,
      ...filterState.apiParams.value,
    }
    if (searchTerm.value && searchTerm.value.length >= 2) {
      params.search = searchTerm.value
    }
    const result = await getTasksPaginated(params as Parameters<typeof getTasksPaginated>[0])
    tasks.value = result.items
    totalTasks.value = result.total
    // Accumulate known initiators for filter options (don't shrink on filter)
    for (const task of result.items) {
      const username = task.initiator_username?.trim()
      if (username) knownInitiators.value.add(username)
    }
  } catch (error) {
    message.error(t('dashboard.failedToFetchTasks'))
  } finally {
    hasLoadedOnce.value = true
    loading.value = false
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
  try {
    projects.value = await getProjects()
  } catch (error) {
    // Keep the task list usable even if the optional filter options fail to load.
  }
}

function refreshTasks() {
  fetchTasks()
  fetchStats()
}

const { start: startPolling } = usePolling(
  () => { fetchTasks(); fetchStats() },
  { interval: 15_000, immediate: false }
)

onMounted(() => {
  fetchProjects()
  fetchStats()
  fetchTasks()
  startPolling()
})
</script>

<style scoped>
.dashboard {
  max-width: var(--app-page-max-width);
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
