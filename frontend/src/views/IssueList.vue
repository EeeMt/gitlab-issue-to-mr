<template>
  <div class="issue-list" data-testid="issue-list-page">
    <n-spin :show="initialLoading" :description="t('common.loadingTasks')">
      <n-space vertical :size="16">
        <PageHeader
          data-testid="issue-list-header"
          root-class="issue-list__hero"
          actions-class="issue-list__actions"
          :title="t('issue.list')"
          :subtitle="t('issue.subtitle')"
        >
          <template #actions>
            <n-select
              v-model:value="statusFilter"
              :options="statusOptions"
              :placeholder="t('common.status')"
              clearable
              class="issue-list__filter issue-list__filter--status"
              data-testid="issue-list-status-filter"
            />
            <n-select
              v-model:value="projectFilter"
              :options="projectOptions"
              :placeholder="t('issue.field.project')"
              clearable
              filterable
              class="issue-list__filter issue-list__filter--project"
            />
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
              data-testid="issue-summary-card"
              card-class="issue-summary-card"
              label-class="issue-summary-card__label"
              value-class="issue-summary-card__value"
            />
          </n-gi>
        </n-grid>

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
import { NButton, NSpace, NSelect, NCard, NDataTable, NTag, NGrid, NGi, NSpin, useMessage, type DataTableColumns } from 'naive-ui'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { getIssues, getProjects, getStats, type Issue, type IssueStatus, type Project } from '../api'
import PageHeader from '../components/PageHeader.vue'
import SummaryCard from '../components/SummaryCard.vue'
import { useBreakpoints } from '../composables/useBreakpoints'
import { formatDateTimeUtc8Compact } from '../utils/datetime'

const router = useRouter()
const message = useMessage()
const { t } = useI18n()
const { isMobile } = useBreakpoints()

const issues = ref<Issue[]>([])
const projects = ref<Project[]>([])
const loading = ref(false)
const hasLoadedOnce = ref(false)
const statusFilter = ref<string | null>(null)
const projectFilter = ref<number | null>(null)

const statsTotal = ref(0)
const statsOpen = ref(0)
const statsInProgress = ref(0)
const statsCompleted = ref(0)

const summaryItems = computed(() => [
  { label: t('issue.totalIssues'), value: String(statsTotal.value) },
  { label: t('issue.openCount'), value: String(statsOpen.value) },
  { label: t('issue.inProgressCount'), value: String(statsInProgress.value) },
  { label: t('issue.completedCount'), value: String(statsCompleted.value) },
])

const currentPage = ref(1)
const pageSize = ref(20)
const totalIssues = ref(0)

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

const statusOptions = computed(() => [
  { label: t('issue.status.open'), value: 'open' },
  { label: t('issue.status.in_progress'), value: 'in_progress' },
  { label: t('issue.status.in_review'), value: 'in_review' },
  { label: t('issue.status.closed'), value: 'closed' },
])

const projectOptions = computed(() =>
  projects.value.map((project) => ({
    label: project.path_with_namespace,
    value: project.id,
  }))
)

function issueRowProps(row: Issue) {
  return {
    style: 'cursor: pointer',
    onClick: () => router.push(`/issues/${row.id}`)
  }
}

const statusColors: Record<IssueStatus, 'default' | 'info' | 'warning' | 'success'> = {
  open: 'info',
  in_progress: 'warning',
  in_review: 'success',
  closed: 'default',
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

const columns = computed<DataTableColumns<Issue>>(() => [
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
    title: t('issue.taskCount', { count: '' }).trim(),
    key: 'task_count',
    width: 80,
    render: (row) => String(row.task_count ?? 0),
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

const initialLoading = computed(() => loading.value && !hasLoadedOnce.value)
const tableLoading = computed(() => loading.value && hasLoadedOnce.value)

async function fetchIssues() {
  if (loading.value) return
  loading.value = true
  try {
    const params: {
      page: number
      page_size: number
      status?: string
      project_id?: number
    } = {
      page: currentPage.value,
      page_size: pageSize.value,
    }
    if (statusFilter.value) {
      params.status = statusFilter.value
    }
    if (projectFilter.value !== null) {
      params.project_id = projectFilter.value
    }
    const result = await getIssues(params)
    issues.value = result.items
    totalIssues.value = result.total
  } catch {
    message.error('Failed to fetch issues')
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

watch([statusFilter, projectFilter], () => {
  currentPage.value = 1
  fetchIssues()
})

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

.issue-list__filter--status {
  width: 140px;
}

.issue-list__filter--project {
  width: min(280px, 70vw);
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

  .issue-list__actions :deep(.n-base-selection),
  .issue-list__actions :deep(.n-button) {
    width: 100%;
  }

  .issue-list__filter--project {
    width: min(280px, 100vw);
  }
}
</style>
