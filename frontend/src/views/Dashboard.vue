<template>
  <div class="dashboard" data-testid="dashboard-page">
    <n-spin :show="initialLoading" :description="t('common.loadingTasks')">
      <n-space vertical :size="16">
        <PageHeader
          data-testid="dashboard-header"
          root-class="dashboard__hero"
          title-class="dashboard__title"
          subtitle-class="dashboard__subtitle"
          :title="t('dashboard.title')"
          :subtitle="t('dashboard.subtitle')"
        >
          <template #actions>
            <n-button
              type="primary"
              data-testid="dashboard-new-issue-button"
              @click="router.push('/issues/create')"
            >
              {{ t('dashboard.createIssue') }}
            </n-button>
          </template>
        </PageHeader>

        <n-grid
          v-if="hasLoadedOnce"
          data-testid="dashboard-summary"
          :cols="isMobile ? 2 : 4"
          :x-gap="16"
          :y-gap="16"
        >
          <n-gi v-for="item in summaryItems" :key="item.label">
            <SummaryCard
              :label="item.label"
              :value="item.value"
              data-testid="dashboard-summary-card"
              card-class="dashboard-summary-card"
              label-class="dashboard-summary-card__label"
              value-class="dashboard-summary-card__value"
            />
          </n-gi>
        </n-grid>

        <n-card
          :title="t('dashboard.recentIssues')"
          :bordered="false"
          class="dashboard-table-card"
          data-testid="dashboard-recent-issues"
        >
          <n-data-table
            :columns="issueColumns"
            :data="recentIssues"
            :loading="loading"
            :row-key="(row: Issue) => row.id"
            :bordered="false"
          />
        </n-card>

        <n-card
          :title="t('dashboard.running')"
          :bordered="false"
          class="dashboard-table-card"
          data-testid="dashboard-running-tasks"
        >
          <n-data-table
            :columns="taskColumns"
            :data="runningAndQueuedTasks"
            :loading="loading"
            :row-key="(row: Task) => row.id"
            :bordered="false"
          />
        </n-card>
      </n-space>
    </n-spin>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, h, computed } from 'vue'
import { NButton, NSpace, NCard, NDataTable, NTag, NGrid, NGi, NSpin, useMessage, type DataTableColumns } from 'naive-ui'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { getIssues, getTasksPaginated, getStats, type Issue, type Task } from '../api'
import PageHeader from '../components/PageHeader.vue'
import SummaryCard from '../components/SummaryCard.vue'
import { useBreakpoints } from '../composables/useBreakpoints'
import { usePolling } from '../composables/usePolling'
import { formatDateTimeUtc8Compact } from '../utils/datetime'
import { formatPriority } from '../utils/format'

const router = useRouter()
const message = useMessage()
const { t } = useI18n()
const { isMobile } = useBreakpoints()

const recentIssues = ref<Issue[]>([])
const runningTasks = ref<Task[]>([])
const queuedTasks = ref<Task[]>([])
const loading = ref(false)
const hasLoadedOnce = ref(false)

const statsIssueTotal = ref(0)
const statsTotal = ref(0)
const statsRunning = ref(0)
const statsCompleted = ref(0)

const runningAndQueuedTasks = computed(() => [...runningTasks.value, ...queuedTasks.value])

const initialLoading = computed(() => loading.value && !hasLoadedOnce.value)

const summaryItems = computed(() => [
  { label: t('dashboard.issueCount'), value: String(statsIssueTotal.value) },
  { label: t('dashboard.visibleTasks'), value: String(statsTotal.value) },
  { label: t('dashboard.running'), value: String(statsRunning.value) },
  { label: t('dashboard.completed'), value: String(statsCompleted.value) },
])

const issueStatusColors: Record<string, 'default' | 'info' | 'warning' | 'success' | 'error'> = {
  open: 'info',
  in_progress: 'warning',
  completed: 'success',
  closed: 'default',
}

const issueColumns = computed<DataTableColumns<Issue>>(() => [
  {
    title: t('dashboard.id'),
    key: 'id',
    width: 60,
  },
  {
    title: t('issue.field.title'),
    key: 'title',
    render: (row) =>
      h(
        NButton,
        {
          text: true,
          type: 'primary',
          onClick: () => router.push(`/issues/${row.id}`),
        },
        () => row.title,
      ),
  },
  {
    title: t('dashboard.status'),
    key: 'status',
    width: 100,
    render: (row) =>
      h(
        NTag,
        { type: issueStatusColors[row.status] || 'default', size: 'small' },
        () => t(`issue.status.${row.status}`),
      ),
  },
  {
    title: t('common.createTask'),
    key: 'task_count',
    width: 80,
    render: (row) => String(row.task_count ?? 0),
  },
  {
    title: t('common.created'),
    key: 'created_at',
    width: 140,
    render: (row) => (row.created_at ? formatDateTimeUtc8Compact(row.created_at) : '-'),
  },
])

const taskColumns = computed<DataTableColumns<Task>>(() => [
  {
    title: t('dashboard.id'),
    key: 'id',
    width: 60,
  },
  {
    title: t('dashboard.task'),
    key: 'user_prompt',
    render: (row) => {
      const label = row.user_prompt ? (row.user_prompt.length > 80 ? row.user_prompt.slice(0, 80) + '…' : row.user_prompt) : '-'
      return h(
        NButton,
        {
          text: true,
          type: 'primary',
          onClick: () => router.push(`/tasks/${row.id}`),
        },
        () => label,
      )
    },
  },
  {
    title: t('dashboard.priority'),
    key: 'priority',
    width: 80,
    render: (row) => formatPriority(row.priority),
  },
  {
    title: t('common.started'),
    key: 'started_at',
    width: 140,
    render: (row) => (row.started_at ? formatDateTimeUtc8Compact(row.started_at) : '-'),
  },
])

async function fetchData() {
  if (loading.value) return
  loading.value = true
  try {
    const [issuesRes, runningRes, queuedRes] = await Promise.all([
      getIssues({ page: 1, page_size: 5 }),
      getTasksPaginated({ status: 'running', page: 1, page_size: 10 }),
      getTasksPaginated({ status: 'queued', page: 1, page_size: 10 }),
    ])
    recentIssues.value = issuesRes.items
    runningTasks.value = runningRes.items
    queuedTasks.value = queuedRes.items
  } catch {
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
    statsIssueTotal.value = stats.issues?.total ?? 0
  } catch {
    // Stats are supplementary; don't block UI
  }
}

function refreshAll() {
  fetchData()
  fetchStats()
}

const { start: startPolling } = usePolling(
  () => refreshAll(),
  { interval: 15_000, immediate: false },
)

onMounted(() => {
  fetchStats()
  fetchData()
  startPolling()
})
</script>

<style scoped>
.dashboard {
  max-width: var(--app-page-max-width);
}

.dashboard-summary-card {
  min-height: 100%;
}

.dashboard-table-card {
  border-radius: var(--app-card-radius);
}
</style>
