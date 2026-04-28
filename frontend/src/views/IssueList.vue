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
          @add-filter="filterState.addFilter"
          @remove-filter="filterState.removeFilter"
          @clear-all-filters="filterState.clearAllFilters"
          @set-sort="filterState.setSort"
          @reset-sort="filterState.resetSort"
          @toggle-column="filterState.toggleColumn"
          @reset-columns="filterState.resetColumns"
          @search="onSearch"
        />

        <n-card class="issue-list__table-card" :bordered="false" data-testid="issue-list-table-card">
          <n-data-table
            data-testid="issue-list-table"
            :columns="columns"
            :data="issues"
            :loading="tableLoading"
            :row-key="(row: Issue) => row.id"
            :row-props="issueRowProps"
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
import { NButton, NSpace, NCard, NDataTable, NTag, NGrid, NGi, NSpin, useMessage, type DataTableColumns } from 'naive-ui'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { getIssues, getProjects, getStats, type Issue, type IssueStatus, type Project } from '../api'
import PageHeader from '../components/PageHeader.vue'
import SummaryCard from '../components/SummaryCard.vue'
import FilterToolbar from '../components/filter/FilterToolbar.vue'
import { useFilterSort, type FilterSortConfig } from '../composables/useFilterSort'
import { useBreakpoints } from '../composables/useBreakpoints'
import { formatDateTimeUtc8Compact } from '../utils/datetime'
import { EllipseOutline, FolderOpenOutline, CalendarOutline, PersonOutline, GitMergeOutline, DocumentTextOutline, AlertCircleOutline, SyncOutline, CheckmarkCircleOutline } from '@vicons/ionicons5'

const router = useRouter()
const message = useMessage()
const { t } = useI18n()
const { isMobile } = useBreakpoints()

const issues = ref<Issue[]>([])
const projects = ref<Project[]>([])
const knownCreators = ref<Set<string>>(new Set())
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

const creatorOptions = computed(() => {
  const values = Array.from(knownCreators.value).sort((a, b) => a.localeCompare(b))
  return values.map((username) => ({ label: username, value: username }))
})

const filterConfig: FilterSortConfig = {
  storageKey: 'codify:filters:issues',
  filterFields: [
    {
      key: 'status',
      label: 'filter.status',
      icon: EllipseOutline,
      type: 'multi-select',
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
      options: () => projects.value.map((p) => ({ label: p.path_with_namespace, value: p.id })),
    },
    {
      key: 'initiator_username',
      label: 'filter.creator',
      icon: PersonOutline,
      type: 'multi-select',
      options: () => creatorOptions.value,
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
  ],
  sortFields: [
    { key: 'created_at', label: 'filter.sortCreated' },
    { key: 'status', label: 'filter.sortStatus' },
    { key: 'total_changes', label: 'filter.sortChanges' },
    { key: 'total_input_tokens', label: 'filter.sortTokens' },
  ],
  columns: [
    { key: 'id', label: 'dashboard.id', defaultVisible: true, alwaysVisible: true },
    { key: 'title', label: 'issue.field.title', defaultVisible: true, alwaysVisible: true },
    { key: 'project_id', label: 'issue.field.project', defaultVisible: true },
    { key: 'status', label: 'common.status', defaultVisible: true },
    { key: 'task_count', label: 'issue.field.tasks', defaultVisible: true },
    { key: 'merge_request', label: 'filter.hasMr', defaultVisible: true },
    { key: 'total_changes', label: 'common.changes', defaultVisible: true },
    { key: 'total_tokens', label: 'analytics.tokens', defaultVisible: true },
    { key: 'initiator_username', label: 'issue.field.creator', defaultVisible: false },
    { key: 'created_at', label: 'issue.field.createdAt', defaultVisible: true },
  ],
  defaultSort: { field: 'created_at', order: 'desc' },
}

const filterState = useFilterSort(filterConfig)
const searchTerm = ref('')

function onSearch(term: string) {
  searchTerm.value = term
  currentPage.value = 1
  fetchIssues()
}

watch([() => filterState.filters.value, () => filterState.sort.value], () => {
  currentPage.value = 1
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
    fetchIssues()
  },
  'onUpdate:pageSize': (size: number) => {
    pageSize.value = size
    currentPage.value = 1
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

const initialLoading = computed(() => loading.value && !hasLoadedOnce.value)
const tableLoading = computed(() => loading.value && hasLoadedOnce.value)

async function fetchIssues() {
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
    const result = await getIssues(params as Parameters<typeof getIssues>[0])
    issues.value = result.items
    totalIssues.value = result.total
    // Accumulate known creators for filter options (don't shrink on filter)
    for (const issue of result.items) {
      const username = issue.initiator_username?.trim()
      if (username) knownCreators.value.add(username)
    }
  } catch {
    message.error(t('issue.loadFailed'))
  } finally {
    hasLoadedOnce.value = true
    loading.value = false
  }
}

async function fetchProjects() {
  try {
    projects.value = await getProjects()
  } catch {
    // Keep the issue list usable even if the optional filter options fail to load.
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
  fetchProjects()
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
