<template>
  <div class="issue-list" data-testid="issue-list-page">
    <n-spin :show="initialLoading" :description="t('common.loadingTasks')">
      <div class="page-hero">
        <PageHeader
          data-testid="issue-list-header"
          root-class="issue-list__hero"
          actions-class="issue-list__actions"
          :title="t('issue.list')"
          :subtitle="t('issue.subtitle')"
        >
          <template #actions>
            <n-button
              type="primary"
              data-testid="issue-list-create-button"
              @click="router.push('/issues/create')"
            >
              {{ t('issue.create') }}
            </n-button>
          </template>
        </PageHeader>

        <n-grid
          v-if="hasLoadedOnce"
          data-testid="issue-summary"
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
              data-testid="issue-summary-card"
              card-class="issue-summary-card"
              label-class="issue-summary-card__label"
              value-class="issue-summary-card__value"
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
          :result-count="totalIssues"
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

        <n-card class="issue-list__table-card" :bordered="false" data-testid="issue-list-table-card">
          <div class="issue-list__table-shell">
            <n-data-table
              data-testid="issue-list-table"
              :columns="columns"
              :data="issues"
              :loading="tableLoading"
              :row-key="(row: Issue) => row.id"
              :row-props="issueRowProps"
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
import { NButton, NSpace, NCard, NDataTable, NTag, NGrid, NGi, NSpin, NIcon, useMessage, type DataTableColumns } from 'naive-ui'
import { useRouter, useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'
import {
  getIssueFilterOptions,
  getIssues,
  getProjects,
  getStats,
  snapshotInitiatorValue,
  type InitiatorFilterOption,
  type Issue,
  type IssueStatus,
  type Project,
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
import { formatDateTimeUtc8Compact } from '../utils/datetime'
import { formatDurationSec } from '../utils/format'
import { EllipseOutline, FolderOpenOutline, CalendarOutline, PersonOutline, GitMergeOutline, DocumentTextOutline, AlertCircleOutline, SyncOutline, CheckmarkCircleOutline } from '@vicons/ionicons5'

const router = useRouter()
const route = useRoute()
const message = useMessage()
const { t } = useI18n()
const { isMobile } = useBreakpoints()

const issues = ref<Issue[]>([])
const projects = ref<Project[]>([])
const projectOptionsLoading = ref(false)
const projectOptionsError = ref(false)
const initiatorFilterOptions = ref<InitiatorFilterOption[]>([])
const initiatorOptionsLoading = ref(false)
const initiatorOptionsError = ref(false)
const loading = ref(false)
const hasLoadedOnce = ref(false)

const statsTotal = ref(0)
const statsOpen = ref(0)
const statsInProgress = ref(0)
const statsCompleted = ref(0)

const summaryItems = computed(() => [
  { label: t('issue.totalIssues'), value: String(statsTotal.value), icon: DocumentTextOutline, accent: 'blue' as const },
  { label: t('issue.openCount'), value: String(statsOpen.value), icon: AlertCircleOutline, accent: 'red' as const },
  { label: t('issue.inProgressCount'), value: String(statsInProgress.value), icon: SyncOutline, accent: 'amber' as const },
  { label: t('issue.completedCount'), value: String(statsCompleted.value), icon: CheckmarkCircleOutline, accent: 'green' as const },
])

const currentPage = ref(1)
const pageSize = ref(20)
const totalIssues = ref(0)

const ISSUE_STATUS_VALUES = ['open', 'in_progress', 'in_review', 'closed'] as const
const BOOLEAN_FILTER_VALUES = ['true', 'false'] as const

function initiatorOptionLabel(option: InitiatorFilterOption): string {
  if (option.kind === 'unknown') return t('filter.unknownInitiator')
  if (option.display_name && option.username && option.display_name !== option.username) {
    return `${option.display_name} (@${option.username})`
  }
  return option.username || t('filter.unknownInitiator')
}

function creatorOptions() {
  const options: { label: string; value: string; count?: number }[] = initiatorFilterOptions.value.map((option) => ({
    label: initiatorOptionLabel(option),
    value: option.value,
    count: option.count,
  }))
  const selected = filterState.filters.value.initiator
  if (Array.isArray(selected)) {
    for (const value of selected) {
      if (!options.some((option) => option.value === value)) {
        options.push({ label: String(value).replace(/^(?:username|snapshot):/, ''), value })
      }
    }
  }
  return options
}

const filterConfig: FilterSortConfig = {
  storageKey: 'codify:filters:issues',
  filterFields: [
    {
      key: 'status',
      label: 'filter.status',
      icon: EllipseOutline,
      type: 'multi-select',
      parseValue: (value) => parseAllowedQueryValue(value, ISSUE_STATUS_VALUES),
      options: () => [
        { label: t('issue.status.open'), value: 'open', color: '#18a058' },
        { label: t('issue.status.in_progress'), value: 'in_progress', color: '#4080ff' },
        { label: t('issue.status.in_review'), value: 'in_review', color: '#f0a020' },
        { label: t('issue.status.closed'), value: 'closed', color: '#888' },
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
      key: 'initiator',
      label: 'filter.initiator',
      icon: PersonOutline,
      type: 'multi-select',
      searchable: true,
      options: creatorOptions,
      optionsLoading: () => initiatorOptionsLoading.value,
      optionsError: () => initiatorOptionsError.value,
      optionsRetry: fetchInitiatorOptions,
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
  ],
  sortFields: [
    { key: 'created_at', label: 'filter.sortCreated' },
    { key: 'status', label: 'filter.sortStatus' },
    { key: 'total_changes', label: 'filter.sortChanges' },
    { key: 'total_input_tokens', label: 'filter.sortTokens' },
    { key: 'duration', label: 'filter.sortDuration' },
  ],
  columns: [
    { key: 'id', label: 'dashboard.id', defaultVisible: true, alwaysVisible: true },
    { key: 'title', label: 'issue.field.title', defaultVisible: true, alwaysVisible: true },
    { key: 'project_id', label: 'issue.field.project', defaultVisible: true },
    { key: 'status', label: 'common.status', defaultVisible: true },
    { key: 'task_count', label: 'issue.field.tasks', defaultVisible: true },
    { key: 'branch_name', label: 'issue.field.branch', defaultVisible: true },
    { key: 'merge_request', label: 'filter.hasMr', defaultVisible: true },
    { key: 'total_changes', label: 'common.changes', defaultVisible: true },
    { key: 'duration', label: 'dashboard.duration', defaultVisible: true },
    { key: 'total_tokens', label: 'analytics.tokens', defaultVisible: true },
    { key: 'initiator_username', label: 'issue.field.creator', defaultVisible: false },
    { key: 'created_at', label: 'issue.field.createdAt', defaultVisible: true },
  ],
  defaultSort: { field: 'created_at', order: 'desc' },
  persistence: { filters: false, sort: false, columns: true },
}

function getIssueQueryState() {
  const state = readListQueryState(filterConfig, route.query, { pageSize: 20, searchMinLength: 2 })
  if (!state.filters.initiator) {
    if (route.query.initiator_user_id) {
      const userInitiators = String(route.query.initiator_user_id)
        .split(',')
        .map(parsePositiveIntegerQueryValue)
        .filter((userId): userId is number => userId !== undefined)
        .map((userId) => `user:${userId}`)
      if (userInitiators.length) state.filters.initiator = userInitiators
    } else if (route.query.initiator_username) {
      state.filters.initiator = String(route.query.initiator_username)
        .split(',')
        .map((username) => username.trim())
        .filter(Boolean)
        .map(snapshotInitiatorValue)
    }
  }
  return state
}

const initialQueryState = getIssueQueryState()
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
  fetchIssues()
}

watch([() => filterState.filters.value, () => filterState.sort.value], () => {
  if (applyingRouteQuery) return
  currentPage.value = 1
  syncRouteQuery()
  fetchIssues()
}, { deep: true })

watch(() => route.query, async () => {
  if (routeQueriesEqual(route.query, currentRouteQuery())) return
  applyingRouteQuery = true
  const state = getIssueQueryState()
  filterState.filters.value = state.filters
  filterState.sort.value = state.sort
  searchTerm.value = state.search
  currentPage.value = state.page
  pageSize.value = state.pageSize
  await nextTick()
  applyingRouteQuery = false
  syncRouteQuery()
  fetchIssues()
}, { deep: true })

const pagination = computed(() => ({
  page: currentPage.value,
  pageSize: pageSize.value,
  itemCount: totalIssues.value,
  showSizePicker: true,
  pageSizes: [20, 50, 100],
  'onUpdate:page': (page: number) => {
    currentPage.value = page
    syncRouteQuery()
    fetchIssues()
  },
  'onUpdate:pageSize': (size: number) => {
    pageSize.value = size
    currentPage.value = 1
    syncRouteQuery()
    fetchIssues()
  },
}))

function issueRowProps(row: Issue) {
  return {
    style: 'cursor: pointer',
    onClick: () => router.push(`/issues/${row.id}`)
  }
}

const statusColors: Record<IssueStatus, 'default' | 'info' | 'warning' | 'success'> = {
  open: 'default',
  in_progress: 'warning',
  in_review: 'info',
  closed: 'success',
}

function getProjectName(projectId: number): string {
  const project = projects.value.find((p) => p.id === projectId)
  return project ? project.path_with_namespace : `Project #${projectId}`
}

function getProjectWebUrl(projectId: number): string | null {
  const project = projects.value.find((p) => p.id === projectId)
  return project?.web_url ?? null
}

function issueBranchUrl(projectId: number, branchName: string | null | undefined): string | null {
  if (!branchName) return null
  const webUrl = getProjectWebUrl(projectId)
  if (!webUrl) return null
  return `${webUrl}/-/tree/${encodeURIComponent(branchName)}`
}

function formatCompactDateTime(value?: string | null): string {
  if (!value) return '-'
  return formatDateTimeUtc8Compact(value)
}

const secondaryTextStyle = { fontSize: '11px', color: 'rgba(15,23,42,0.45)', marginTop: '2px', lineHeight: '1.4' }

function formatNumber(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) return '—'
  return Math.round(value).toLocaleString()
}

const allColumns = computed<DataTableColumns<Issue>>(() => [
  {
    title: 'ID',
    key: 'id',
    width: 60,
  },
  {
    title: t('issue.field.title'),
    key: 'title',
    ellipsis: { tooltip: true },
    render: (row) =>
      h(
        NButton,
        {
          text: true,
          type: 'primary',
          onClick: (e: MouseEvent) => {
            e.stopPropagation()
            router.push(`/issues/${row.id}`)
          },
        },
        () => row.title
      ),
  },
  {
    title: t('issue.field.project'),
    key: 'project_id',
    width: 180,
    ellipsis: { tooltip: true },
    render: (row) => getProjectName(row.project_id),
  },
  {
    title: t('common.status'),
    key: 'status',
    width: 110,
    render: (row) =>
      h(
        NTag,
        { type: statusColors[row.status], size: 'small' },
        () => t(`issue.status.${row.status}`)
      ),
  },
  {
    title: t('issue.field.tasks'),
    key: 'task_count',
    width: 80,
    render: (row) => String(row.task_count ?? 0),
  },
  {
    title: t('issue.field.branch'),
    key: 'branch_name',
    width: 180,
    ellipsis: { tooltip: true },
    render: (row) => {
      if (!row.branch_name) return '—'
      const url = issueBranchUrl(row.project_id, row.branch_name)
      if (url) {
        return h('a', {
          href: url,
          target: '_blank',
          rel: 'noopener noreferrer',
          class: 'app-link',
          onClick: (e: MouseEvent) => e.stopPropagation(),
        }, row.branch_name)
      }
      return row.branch_name
    },
  },
  {
    title: t('filter.hasMr'),
    key: 'merge_request',
    width: 80,
    render: (row) => {
      if (!row.merge_request_iid) return '—'
      const label = `!${row.merge_request_iid}`
      if (row.merge_request_url) {
        return h('a', { href: row.merge_request_url, target: '_blank', rel: 'noopener noreferrer', class: 'app-link' }, label)
      }
      return label
    },
  },
  {
    title: t('common.changes'),
    key: 'total_changes',
    width: 110,
    render: (row) => {
      const totals = row.totals
      if (!totals || totals.total_changes === 0) return '—'
      return h('div', [
        h('div', String(totals.total_changes)),
        h('div', { style: secondaryTextStyle }, t('analytics.changeBreakdown', { additions: totals.additions, deletions: totals.deletions })),
      ])
    },
  },
  {
    title: t('dashboard.duration'),
    key: 'duration',
    width: 100,
    render: (row) => {
      const durationSeconds = row.totals?.duration_seconds ?? 0
      if (durationSeconds <= 0) return '—'
      return formatDurationSec(durationSeconds)
    },
  },
  {
    title: t('analytics.tokens'),
    key: 'total_tokens',
    width: 140,
    render: (row) => {
      const totals = row.totals
      if (!totals || (totals.input_tokens === 0 && totals.output_tokens === 0)) return '—'
      const total = totals.input_tokens + totals.output_tokens
      return h('div', [
        h('div', formatNumber(total)),
        h('div', { style: secondaryTextStyle }, t('analytics.tokenInputLine', { value: formatNumber(totals.input_tokens) })),
        h('div', { style: secondaryTextStyle }, t('analytics.tokenOutputLine', { value: formatNumber(totals.output_tokens) })),
      ])
    },
  },
  {
    title: t('issue.field.creator'),
    key: 'initiator_username',
    width: 120,
    ellipsis: { tooltip: true },
    render: (row) => row.initiator_username || '-',
  },
  {
    title: t('issue.field.createdAt'),
    key: 'created_at',
    width: 140,
    render: (row) => formatCompactDateTime(row.created_at),
  },
])

const columns = computed<DataTableColumns<Issue>>(() => {
  const visible = filterState.visibleColumns.value
  return allColumns.value.filter((col) => 'key' in col && visible.includes(col.key as string))
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

async function fetchIssues() {
  const requestId = ++latestIssueRequestId
  loading.value = true
  const params: Record<string, any> = {
    page: currentPage.value,
    page_size: pageSize.value,
    ...filterState.apiParams.value,
  }
  if (searchTerm.value && searchTerm.value.length >= 2) {
    params.search = searchTerm.value
  }
  try {
    const result = await getIssues(params)
    if (requestId !== latestIssueRequestId) return
    issues.value = result.items
    totalIssues.value = result.total
  } catch {
    if (requestId === latestIssueRequestId) {
      message.error(t('issue.loadFailed'))
    }
  } finally {
    if (requestId === latestIssueRequestId) {
      hasLoadedOnce.value = true
      loading.value = false
    }
  }
}

let latestIssueRequestId = 0

async function fetchInitiatorOptions() {
  initiatorOptionsLoading.value = true
  initiatorOptionsError.value = false
  try {
    const result = await getIssueFilterOptions()
    initiatorFilterOptions.value = result.initiators
  } catch {
    initiatorOptionsError.value = true
  } finally {
    initiatorOptionsLoading.value = false
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

async function fetchStats() {
  try {
    const stats = await getStats()
    const issueStats = stats.issues
    if (issueStats) {
      statsTotal.value = issueStats.total
      statsOpen.value = issueStats.by_status?.open ?? 0
      statsInProgress.value = issueStats.by_status?.in_progress ?? 0
      statsCompleted.value = issueStats.by_status?.in_review ?? 0
    }
  } catch {
    // Stats are supplementary; don't block UI
  }
}

onMounted(() => {
  syncRouteQuery()
  fetchProjects()
  fetchInitiatorOptions()
  fetchIssues()
  fetchStats()
})
</script>

<style scoped>
.issue-list {
  max-width: var(--app-page-max-width);
}

.issue-list__actions {
  display: inline-flex;
  align-items: center;
  justify-content: flex-end;
  gap: 8px;
  flex-wrap: wrap;
}

.issue-list__table-card {
  border-radius: var(--app-card-radius);
  min-width: 0;
  overflow: hidden;
}

.issue-list__table-card :deep(.n-card__content) {
  min-width: 0;
}

.issue-list__table-shell {
  width: 100%;
  min-width: 0;
  overflow-x: auto;
}

.issue-summary-card {
  min-height: 100%;
}

@media (max-width: 768px) {
  .issue-list__actions {
    width: 100%;
    justify-content: flex-start;
  }

  .issue-list__actions :deep(.n-button) {
    width: 100%;
  }
}
</style>
