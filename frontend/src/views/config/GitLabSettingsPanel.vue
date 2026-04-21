<template>
  <div class="config-layout__main">
    <n-card id="gitlab-settings" class="config-form-card" :bordered="false">
      <template #header>
        <div class="config-card-header">
          <div>
            <div class="config-card-header__title">{{ t('config.gitlabIntegration') }}</div>
            <div class="config-card-header__subtitle">{{ t('config.gitlabIntegrationSubtitle') }}</div>
          </div>
        </div>
      </template>

      <n-form ref="gitlabFormRef" :model="formValue" :rules="gitlabRules" label-placement="top" class="config-section-form">
        <div class="config-form__section">
          <div class="config-form__section-title">{{ t('config.gitlabConnection') }}</div>
          <n-grid :cols="isMobile ? 1 : 2" :x-gap="16" :y-gap="8">
            <n-gi>
              <n-form-item :label="t('config.gitlabUrl')" path="gitlab_url">
                <n-input
                  v-model:value="formValue.gitlab_url"
                  placeholder="https://gitlab.example.com"
                  class="config-form__input"
                />
                <template #feedback>
                  {{ t('config.gitlabUrlHint') }}
                </template>
              </n-form-item>
            </n-gi>
            <n-gi>
              <n-form-item :label="t('config.gitlabBotTokenStatus')">
                <n-tag :type="formValue.gitlab_bot_token_configured ? 'success' : 'warning'" round>
                  {{ formValue.gitlab_bot_token_configured ? t('config.configured') : t('config.missing') }}
                </n-tag>
                <template #feedback>
                  {{ t('config.gitlabBotTokenStatusHint') }}
                </template>
              </n-form-item>
            </n-gi>
            <n-gi :span="isMobile ? 1 : 2">
              <n-form-item :label="t('config.gitlabBotToken')">
                <n-input
                  v-model:value="formValue.gitlab_bot_token_input"
                  type="password"
                  show-password-on="click"
                  :placeholder="
                    formValue.gitlab_bot_token_configured
                      ? t('config.configuredEnterNew')
                      : t('config.enterGitlabBotToken')
                  "
                  class="config-form__input"
                />
                <template #feedback>
                  {{ t('config.gitlabBotTokenHint') }}
                </template>
              </n-form-item>
            </n-gi>
          </n-grid>
        </div>

        <div class="config-form__section">
          <div class="config-form__section-title">{{ t('config.webhookAutomation') }}</div>
          <n-grid :cols="isMobile ? 1 : 2" :x-gap="16" :y-gap="8">
            <n-gi>
              <n-form-item :label="t('config.gitlabAdminTokenStatus')">
                <n-tag :type="formValue.gitlab_admin_token_configured ? 'success' : 'warning'" round>
                  {{ formValue.gitlab_admin_token_configured ? t('config.configured') : t('config.missing') }}
                </n-tag>
                <template #feedback>
                  {{ t('config.gitlabAdminTokenStatusHint') }}
                </template>
              </n-form-item>
            </n-gi>
            <n-gi>
              <n-form-item :label="t('config.gitlabWebhookSecretStatus')">
                <n-tag :type="formValue.gitlab_webhook_secret_configured ? 'success' : 'warning'" round>
                  {{ formValue.gitlab_webhook_secret_configured ? t('config.configured') : t('config.missing') }}
                </n-tag>
                <template #feedback>
                  {{ t('config.gitlabWebhookSecretStatusHint') }}
                </template>
              </n-form-item>
            </n-gi>
            <n-gi :span="isMobile ? 1 : 2">
              <n-form-item :label="t('config.gitlabAdminToken')">
                <n-input
                  v-model:value="formValue.gitlab_admin_token_input"
                  type="password"
                  show-password-on="click"
                  :placeholder="
                    formValue.gitlab_admin_token_configured
                      ? t('config.configuredEnterNew')
                      : t('config.enterGitlabAdminToken')
                  "
                  class="config-form__input"
                />
                <template #feedback>
                  {{ t('config.gitlabAdminTokenHint') }}
                </template>
              </n-form-item>
            </n-gi>
            <n-gi :span="isMobile ? 1 : 2">
              <n-form-item :label="t('config.gitlabWebhookSecret')">
                <n-input
                  v-model:value="formValue.gitlab_webhook_secret_input"
                  type="password"
                  show-password-on="click"
                  :placeholder="
                    formValue.gitlab_webhook_secret_configured
                      ? t('config.configuredEnterNew')
                      : t('config.enterGitlabWebhookSecret')
                  "
                  class="config-form__input"
                />
                <template #feedback>
                  {{ t('config.gitlabWebhookSecretHint') }}
                </template>
              </n-form-item>
            </n-gi>
            <n-gi :span="isMobile ? 1 : 2">
              <n-form-item :label="t('config.webhookOverviewSearch')">
                <n-input
                  v-model:value="webhookSearch"
                  clearable
                  :placeholder="t('config.webhookOverviewSearchPlaceholder')"
                  class="config-form__input"
                />
                <template #feedback>
                  {{ t('config.webhookOverviewHint') }}
                </template>
              </n-form-item>
            </n-gi>
          </n-grid>
        </div>

        <div class="config-form__section">
          <div class="config-card-header config-card-header--stacked">
            <div>
              <div class="config-card-header__title">{{ t('config.webhookOverview') }}</div>
              <div class="config-card-header__subtitle">{{ t('config.webhookOverviewSubtitle') }}</div>
            </div>
            <n-button
              @click="fetchWebhookStatuses"
              :loading="webhookStatusLoading"
              :disabled="isGitLabBusy"
            >
              {{ t('config.refreshWebhookStatuses') }}
            </n-button>
          </div>

          <n-grid v-if="webhookSummaryItems.length" :cols="isMobile ? 2 : 4" :x-gap="16" :y-gap="16" class="config-webhook-summary">
            <n-gi v-for="item in webhookSummaryItems" :key="item.label">
              <n-card size="small" class="config-summary-card" :bordered="false">
                <div class="config-summary-card__label">{{ item.label }}</div>
                <div class="config-summary-card__value">{{ item.value }}</div>
              </n-card>
            </n-gi>
          </n-grid>

          <div v-if="!isMobile" class="config-table-wrapper">
            <n-data-table
              :columns="webhookColumns"
              :data="filteredWebhookStatuses"
              :loading="webhookStatusLoading"
              :bordered="false"
              :pagination="{ pageSize: 10 }"
              :scroll-x="1100"
              :row-key="(row: GitLabProjectWebhookStatusResult) => row.project_id"
            />
          </div>
          <n-spin v-else :show="webhookStatusLoading">
            <div v-if="!webhookStatusLoading && filteredWebhookStatuses.length === 0" class="config-webhook-mobile__empty">
              {{ t('config.noWebhookData') }}
            </div>
            <div
              v-for="row in filteredWebhookStatuses"
              :key="row.project_id"
              class="config-webhook-mobile__item"
            >
              <div class="config-webhook-mobile__item-top">
                <div class="config-webhook-project">
                  <div class="config-webhook-project__name">{{ row.project_path_with_namespace || row.project_name || `#${row.project_id}` }}</div>
                  <div class="config-webhook-project__meta">#{{ row.project_id }}</div>
                </div>
                <n-button
                  size="small"
                  :type="row.status === 'configured' ? 'default' : 'primary'"
                  :secondary="row.status !== 'configured'"
                  :loading="webhookActionProjectId === row.project_id"
                  :disabled="isGitLabBusy && webhookActionProjectId !== row.project_id"
                  @click="handleSetupProjectWebhook(row.project_id)"
                >
                  {{ t('config.setupProjectWebhook') }}
                </n-button>
              </div>
              <div class="config-webhook-mobile__item-tags">
                <n-tag :type="getWebhookStatusTagType(row.status)" size="small" round>{{ getWebhookStatusLabel(row.status) }}</n-tag>
                <n-tag size="small" round>{{ getWebhookSecretLabel(row.secret_mode) }}</n-tag>
              </div>
              <div v-if="row.status_detail || row.hook_url || row.target_webhook_url" class="config-webhook-mobile__item-detail">
                {{ row.status_detail || row.hook_url || row.target_webhook_url }}
              </div>
            </div>
          </n-spin>
        </div>
        <div class="config-card-actions">
          <n-space :size="12" wrap>
            <n-button
              type="primary"
              @click="handleSaveSection('gitlab')"
              :loading="sectionSaving.gitlab"
              :disabled="isGitLabBusy || !isSectionDirty('gitlab')"
            >
              {{ t('config.saveChanges') }}
            </n-button>
            <n-button
              secondary
              @click="resetSection('gitlab')"
              :disabled="isGitLabBusy || !isSectionDirty('gitlab')"
            >
              {{ t('config.revertChanges') }}
            </n-button>
            <n-button
              @click="handleTestGitLab"
              :loading="gitlabTesting"
              :disabled="isGitLabBusy"
            >
              {{ t('config.testGitlabConnection') }}
            </n-button>
            <n-button
              @click="handleInvalidateProjectCache"
              :loading="projectCacheInvalidating"
              :disabled="isGitLabBusy"
            >
              {{ t('config.invalidateProjectCache') }}
            </n-button>
            <n-button
              @click="handleClearSecret('gitlab_bot_token')"
              :disabled="isGitLabBusy || !formValue.gitlab_bot_token_configured"
            >
              {{ t('config.clearGitlabBotToken') }}
            </n-button>
            <n-button
              @click="handleClearSecret('gitlab_admin_token')"
              :disabled="isGitLabBusy || !formValue.gitlab_admin_token_configured"
            >
              {{ t('config.clearGitlabAdminToken') }}
            </n-button>
            <n-button
              @click="handleClearSecret('gitlab_webhook_secret')"
              :disabled="isGitLabBusy || !formValue.gitlab_webhook_secret_configured"
            >
              {{ t('config.clearGitlabWebhookSecret') }}
            </n-button>
          </n-space>
          <n-alert
            v-if="gitlabTestState"
            :type="gitlabTestState.type"
            :show-icon="false"
            class="config-actions__alert"
          >
            {{ gitlabTestState.message }}
          </n-alert>
          <n-alert
            v-if="webhookSetupState"
            :type="webhookSetupState.type"
            :show-icon="false"
            class="config-actions__alert"
          >
            {{ webhookSetupState.message }}
          </n-alert>
          <n-alert
            v-if="webhookStatusState"
            :type="webhookStatusState.type"
            :show-icon="false"
            class="config-actions__alert"
          >
            {{ webhookStatusState.message }}
          </n-alert>
        </div>
      </n-form>
    </n-card>
  </div>
</template>

<script setup lang="ts">
import { computed, h, ref } from 'vue'
import {
  NAlert,
  NButton,
  NCard,
  NDataTable,
  NForm,
  NFormItem,
  NGi,
  NGrid,
  NInput,
  NSpace,
  NSpin,
  NTag,
  type DataTableColumns,
  type FormInst,
  type FormRules
} from 'naive-ui'
import { useI18n } from 'vue-i18n'
import { useWindowSize } from '@vueuse/core'
import { useMessage } from 'naive-ui'
import { useConfigForm } from './useConfigForm'
import {
  invalidateProjectCache,
  listGitLabProjectWebhookStatuses,
  setupGitLabProjectWebhook,
  testGitLabConfig,
  type GitLabProjectWebhookSetupResult,
  type GitLabProjectWebhookStatusResult
} from '../../api'

const props = defineProps<{
  isMobile?: boolean
}>()

const { t } = useI18n()
const { width } = useWindowSize()
const message = useMessage()
const isMobile = computed(() => props.isMobile ?? width.value < 768)

// Use shared config form
const {
  formValue,
  sectionSaving,
  isSectionDirty,
  handleSaveSection,
  handleClearSecret,
  buildGitlabSectionUpdate
} = useConfigForm()

// GitLab-specific state
const gitlabTesting = ref(false)
const webhookStatusLoading = ref(false)
const webhookStatuses = ref<GitLabProjectWebhookStatusResult[]>([])
const webhookSearch = ref('')
const projectCacheInvalidating = ref(false)
const webhookActionProjectId = ref<number | null>(null)
const gitlabTestState = ref<{ type: 'success' | 'error', message: string } | null>(null)
const webhookSetupState = ref<{ type: 'success' | 'error', message: string } | null>(null)
const webhookStatusState = ref<{ type: 'success' | 'error', message: string } | null>(null)

const isGitLabBusy = computed(() =>
  sectionSaving.gitlab ||
  gitlabTesting.value ||
  webhookStatusLoading.value ||
  webhookActionProjectId.value !== null ||
  projectCacheInvalidating.value
)

// Form ref
const gitlabFormRef = ref<FormInst | null>(null)

const gitlabRules: FormRules = {
  gitlab_url: {
    required: true,
    message: t('config.enterGitlabUrl'),
    trigger: 'blur'
  }
}

// Filtered webhook statuses
const filteredWebhookStatuses = computed(() => {
  const keyword = webhookSearch.value.trim().toLowerCase()
  if (!keyword) {
    return webhookStatuses.value
  }
  return webhookStatuses.value.filter((row: GitLabProjectWebhookStatusResult) => {
    const text = [
      row.project_name,
      row.project_path_with_namespace,
      row.status,
      row.secret_mode,
      row.status_detail || ''
    ]
      .join(' ')
      .toLowerCase()
    return text.includes(keyword)
  })
})

const webhookSummaryItems = computed(() => {
  const rows = webhookStatuses.value
  const configured = rows.filter((row: GitLabProjectWebhookStatusResult) => row.status === 'configured').length
  const attention = rows.filter((row: GitLabProjectWebhookStatusResult) => row.status === 'needs_attention').length
  const missingOrError = rows.filter((row: GitLabProjectWebhookStatusResult) => row.status === 'missing' || row.status === 'error').length

  return [
    { label: t('config.webhookProjectsTotal'), value: String(rows.length) },
    { label: t('config.webhookProjectsConfigured'), value: String(configured) },
    { label: t('config.webhookProjectsAttention'), value: String(attention) },
    { label: t('config.webhookProjectsMissing'), value: String(missingOrError) }
  ]
})

// Helper functions
function getWebhookSecretLabel(secretMode: GitLabProjectWebhookStatusResult['secret_mode']) {
  if (secretMode === 'project') {
    return t('config.webhookSecretModeProject')
  }
  if (secretMode === 'global_fallback') {
    return t('config.webhookSecretModeGlobalFallback')
  }
  return t('config.webhookSecretModeNone')
}

function getWebhookStatusLabel(status: GitLabProjectWebhookStatusResult['status']) {
  if (status === 'configured') {
    return t('config.webhookStatusConfigured')
  }
  if (status === 'needs_attention') {
    return t('config.webhookStatusNeedsAttention')
  }
  if (status === 'missing') {
    return t('config.webhookStatusMissing')
  }
  return t('config.webhookStatusError')
}

function getWebhookStatusTagType(status: GitLabProjectWebhookStatusResult['status']): 'success' | 'warning' | 'error' | 'default' {
  if (status === 'configured') {
    return 'success'
  }
  if (status === 'needs_attention') {
    return 'warning'
  }
  if (status === 'missing' || status === 'error') {
    return 'error'
  }
  return 'default'
}

function resetSection(section: 'gitlab') {
  // Import the resetSection from useConfigForm
  const { resetSection: sharedResetSection } = useConfigForm()
  sharedResetSection(section)
}

// Webhook columns
const webhookColumns = computed<DataTableColumns<GitLabProjectWebhookStatusResult>>(() => [
  {
    title: t('config.webhookProjectColumn'),
    key: 'project',
    minWidth: 240,
    render: (row) =>
      h('div', { class: 'config-webhook-project' }, [
        h('div', { class: 'config-webhook-project__name' }, row.project_path_with_namespace || row.project_name || `#${row.project_id}`),
        h('div', { class: 'config-webhook-project__meta' }, `#${row.project_id}`)
      ])
  },
  {
    title: t('config.webhookStatusColumn'),
    key: 'status',
    width: 150,
    render: (row) =>
      h(NTag, { type: getWebhookStatusTagType(row.status), round: true }, { default: () => getWebhookStatusLabel(row.status) })
  },
  {
    title: t('config.webhookSecretModeColumn'),
    key: 'secret_mode',
    width: 170,
    render: (row) => h(NTag, { round: true }, { default: () => getWebhookSecretLabel(row.secret_mode) })
  },
  {
    title: t('config.webhookChecksColumn'),
    key: 'checks',
    minWidth: 220,
    render: (row) =>
      h('div', { class: 'config-webhook-checks' }, [
        h('span', `${t('config.webhookHookIdShort')}: ${row.hook_id ?? '-'}`),
        h('span', `${t('config.webhookNoteEventsShort')}: ${row.note_events === null ? '-' : row.note_events ? t('common.enabled') : t('common.disabled')}`),
        h('span', `${t('config.webhookMrEventsShort')}: ${row.merge_requests_events === null ? '-' : row.merge_requests_events ? t('common.enabled') : t('common.disabled')}`),
        h('span', `${t('config.webhookSslShort')}: ${row.enable_ssl_verification === null ? '-' : row.enable_ssl_verification ? t('common.enabled') : t('common.disabled')}`)
      ])
  },
  {
    title: t('config.webhookStatusDetailColumn'),
    key: 'status_detail',
    minWidth: 220,
    render: (row) => row.status_detail || row.hook_url || row.target_webhook_url
  },
  {
    title: t('config.actions'),
    key: 'actions',
    width: 140,
    fixed: isMobile.value ? undefined : 'right',
    render: (row) =>
      h(
        NButton,
        {
          size: 'small',
          type: row.status === 'configured' ? 'default' : 'primary',
          secondary: row.status !== 'configured',
          loading: webhookActionProjectId.value === row.project_id,
          disabled: isGitLabBusy.value && webhookActionProjectId.value !== row.project_id,
          onClick: () => handleSetupProjectWebhook(row.project_id)
        },
        { default: () => t('config.setupProjectWebhook') }
      )
  }
])

// Actions
async function fetchWebhookStatuses() {
  try {
    if (!formValue.value.gitlab_url.trim() || !formValue.value.gitlab_admin_token_configured) {
      webhookStatuses.value = []
      return
    }
    webhookStatusLoading.value = true
    webhookStatusState.value = null
    webhookStatuses.value = await listGitLabProjectWebhookStatuses()
  } catch (error: any) {
    webhookStatuses.value = []
    const detail = error?.response?.data?.detail || t('config.projectWebhookStatusFailed')
    webhookStatusState.value = { type: 'error', message: detail }
  } finally {
    webhookStatusLoading.value = false
  }
}

async function handleTestGitLab() {
  gitlabTesting.value = true
  try {
    const result = await testGitLabConfig(buildGitlabSectionUpdate())
    gitlabTestState.value = {
      type: 'success',
      message: t('config.gitlabConnectionSucceeded', {
        url: result.gitlab_url,
        username: result.username,
        version: result.server_version || t('common.notAvailable')
      })
    }
    message.success(t('config.gitlabConnectionPassed'))
  } catch (error: any) {
    const detail = error?.response?.data?.detail || t('config.gitlabConnectionFailed')
    gitlabTestState.value = { type: 'error', message: detail }
    message.error(detail)
  } finally {
    gitlabTesting.value = false
  }
}

async function handleInvalidateProjectCache() {
  projectCacheInvalidating.value = true
  try {
    await invalidateProjectCache()
    message.success(t('config.projectCacheInvalidated'))
  } catch (error: any) {
    const detail = error?.response?.data?.detail || t('config.projectCacheInvalidateFailed')
    message.error(detail)
  } finally {
    projectCacheInvalidating.value = false
  }
}

function buildWebhookSetupMessage(result: GitLabProjectWebhookSetupResult): string {
  const projectLabel = result.project_path_with_namespace || result.project_name || `#${result.project_id}`
  if (result.action === 'created') {
    return t('config.projectWebhookCreated', { project: projectLabel, hookId: result.hook_id })
  }
  return t('config.projectWebhookUpdated', { project: projectLabel, hookId: result.hook_id })
}

async function handleSetupProjectWebhook(projectId: number) {
  webhookActionProjectId.value = projectId
  try {
    const result = await setupGitLabProjectWebhook(projectId)
    const successMessage = buildWebhookSetupMessage(result)
    webhookSetupState.value = { type: 'success', message: successMessage }
    await fetchWebhookStatuses()
    message.success(successMessage)
  } catch (error: any) {
    const detail = error?.response?.data?.detail || t('config.projectWebhookSetupFailed')
    webhookSetupState.value = { type: 'error', message: detail }
    message.error(detail)
  } finally {
    webhookActionProjectId.value = null
  }
}

// Expose for parent to trigger initial fetch
defineExpose({
  fetchWebhookStatuses
})
</script>
