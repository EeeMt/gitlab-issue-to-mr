<template>
  <div class="config-layout__main">
    <n-card class="config-form-card" :bordered="false">
      <template #header>
        <div class="config-card-header config-card-header--stacked">
          <div>
            <div class="config-card-header__title">{{ t('config.webhookEventsTitle') }}</div>
            <div class="config-card-header__subtitle">{{ t('config.webhookEventsSubtitle') }}</div>
          </div>
          <n-button @click="fetchEvents" :loading="loading">
            {{ t('config.webhookEventsRefresh') }}
          </n-button>
        </div>
      </template>

      <n-space vertical :size="16">
        <n-grid :cols="isMobile ? 1 : 3" :x-gap="12" :y-gap="8">
          <n-gi>
            <n-select
              v-model:value="filterResult"
              :options="resultOptions"
              clearable
              :placeholder="t('config.webhookEventsFilterResult')"
              @update:value="fetchEvents"
            />
          </n-gi>
          <n-gi>
            <n-input-number
              v-model:value="filterProjectId"
              clearable
              :placeholder="t('config.webhookEventsFilterProjectId')"
              :show-button="false"
              @update:value="fetchEvents"
            />
          </n-gi>
        </n-grid>

        <n-data-table
          :columns="columns"
          :data="events"
          :loading="loading"
          :bordered="false"
          :scroll-x="1000"
          :row-key="(row: WebhookEvent) => row.id"
        >
          <template #empty>
            <span>{{ t('config.webhookEventsEmpty') }}</span>
          </template>
        </n-data-table>

        <n-space justify="end">
          <n-pagination
            v-model:page="currentPage"
            :page-size="pageSize"
            :item-count="total"
            :page-sizes="[10, 20, 50]"
            show-size-picker
            @update:page="fetchEvents"
            @update:page-size="handlePageSizeChange"
          />
        </n-space>
      </n-space>
    </n-card>
  </div>
</template>

<script setup lang="ts">
import { computed, h, onMounted, ref } from 'vue'
import {
  NButton,
  NCard,
  NDataTable,
  NGi,
  NGrid,
  NInputNumber,
  NPagination,
  NSelect,
  NSpace,
  NTag,
  type DataTableColumns,
} from 'naive-ui'
import { useI18n } from 'vue-i18n'
import { RouterLink } from 'vue-router'
import { getWebhookEvents, type WebhookEvent } from '../../api'

defineProps<{
  isMobile?: boolean
}>()

const { t } = useI18n()

const loading = ref(false)
const events = ref<WebhookEvent[]>([])
const total = ref(0)
const currentPage = ref(1)
const pageSize = ref(20)
const filterResult = ref<string | null>(null)
const filterProjectId = ref<number | null>(null)

const resultOptions = computed(() => [
  { label: t('config.webhookEventsResultIssueClosed'), value: 'issue_closed' },
  { label: t('config.webhookEventsResultIgnoredAlreadyClosed'), value: 'ignored_already_closed' },
  { label: t('config.webhookEventsResultNoMatch'), value: 'no_match' },
  { label: t('config.webhookEventsResultUnsupported'), value: 'unsupported_event' },
  { label: t('config.webhookEventsResultIgnoredAction'), value: 'ignored_action' },
  { label: t('config.webhookEventsResultAuthFailed'), value: 'auth_failed' },
])

function getResultTagType(result: string): 'success' | 'warning' | 'error' | 'default' {
  if (result === 'issue_closed') return 'success'
  if (result === 'no_match') return 'warning'
  if (result === 'auth_failed') return 'error'
  return 'default'
}

function getResultLabel(result: string): string {
  const map: Record<string, string> = {
    issue_closed: t('config.webhookEventsResultIssueClosed'),
    ignored_already_closed: t('config.webhookEventsResultIgnoredAlreadyClosed'),
    no_match: t('config.webhookEventsResultNoMatch'),
    unsupported_event: t('config.webhookEventsResultUnsupported'),
    ignored_action: t('config.webhookEventsResultIgnoredAction'),
    auth_failed: t('config.webhookEventsResultAuthFailed'),
  }
  return map[result] || result
}

const columns = computed<DataTableColumns<WebhookEvent>>(() => [
  {
    title: t('config.webhookEventsColTime'),
    key: 'created_at',
    width: 170,
    render: (row) => {
      const d = new Date(row.created_at)
      return d.toLocaleString()
    },
  },
  {
    title: t('config.webhookEventsColProjectId'),
    key: 'project_id',
    width: 100,
  },
  {
    title: t('config.webhookEventsColEventType'),
    key: 'event_type',
    width: 120,
  },
  {
    title: t('config.webhookEventsColAction'),
    key: 'event_action',
    width: 100,
    render: (row) => row.event_action || '-',
  },
  {
    title: t('config.webhookEventsColMrIid'),
    key: 'merge_request_iid',
    width: 80,
    render: (row) => (row.merge_request_iid != null ? `!${row.merge_request_iid}` : '-'),
  },
  {
    title: t('config.webhookEventsColIssue'),
    key: 'issue_id',
    width: 80,
    render: (row) => {
      if (row.issue_id == null) return '-'
      return h(RouterLink, { to: `/issues/${row.issue_id}` }, { default: () => `#${row.issue_id}` })
    },
  },
  {
    title: t('config.webhookEventsColResult'),
    key: 'result',
    width: 150,
    render: (row) =>
      h(NTag, { type: getResultTagType(row.result), size: 'small', round: true }, { default: () => getResultLabel(row.result) }),
  },
  {
    title: t('config.webhookEventsColDetail'),
    key: 'result_detail',
    minWidth: 200,
    render: (row) => row.result_detail || '-',
  },
])

async function fetchEvents() {
  loading.value = true
  try {
    const resp = await getWebhookEvents({
      page: currentPage.value,
      page_size: pageSize.value,
      result: filterResult.value || undefined,
      project_id: filterProjectId.value || undefined,
    })
    events.value = resp.items
    total.value = resp.total
  } catch (err) {
    console.error('Failed to load webhook events:', err)
    events.value = []
    total.value = 0
  } finally {
    loading.value = false
  }
}

function handlePageSizeChange(size: number) {
  pageSize.value = size
  currentPage.value = 1
  fetchEvents()
}

onMounted(() => {
  fetchEvents()
})
</script>
