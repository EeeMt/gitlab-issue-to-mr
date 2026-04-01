<template>
  <div class="config-page">
    <n-space vertical :size="16">
      <div class="config-page__hero">
        <div>
          <h2 class="config-page__title">{{ t('config.title') }}</h2>
          <p class="config-page__subtitle">
            {{ t('config.subtitle') }}
          </p>
        </div>
        <n-space :size="8" wrap>
          <n-tag v-if="isDirty" size="small" round type="warning">{{ t('config.unsavedChanges') }}</n-tag>
          <n-tag v-else size="small" round type="success">{{ t('config.inSync') }}</n-tag>
          <n-tag size="small" round type="info">{{ t('config.dbOverride') }}</n-tag>
          <n-tag size="small" round>{{ t('config.envFallback') }}</n-tag>
          <n-tag size="small" round>{{ t('config.defaultFallback') }}</n-tag>
        </n-space>
      </div>

      <n-alert type="info" :show-icon="false">
        {{ t('config.secretInfo') }}
      </n-alert>

      <n-grid :cols="isMobile ? 2 : 4" :x-gap="16" :y-gap="16">
        <n-gi v-for="item in summaryItems" :key="item.label">
          <n-card size="small" class="config-summary-card" :bordered="false">
            <div class="config-summary-card__label">{{ item.label }}</div>
            <div class="config-summary-card__value">{{ item.value }}</div>
          </n-card>
        </n-gi>
      </n-grid>

      <n-spin :show="loading">
        <div class="config-form">
          <n-tabs v-model:value="activeConfigTab" type="line" animated class="config-tabs">
            <n-tab-pane name="runtime" :tab="t('config.runtimeTab')">
              <RuntimeSettingsPanel :is-mobile="isMobile" />
            </n-tab-pane>

            <n-tab-pane name="gitlab" :tab="t('config.gitlabTab')">
              <GitLabSettingsPanel ref="gitlabPanelRef" :is-mobile="isMobile" />
            </n-tab-pane>

            <n-tab-pane name="notifications" :tab="t('config.notificationsTab')">
              <MattermostNotificationsPanel :is-mobile="isMobile" :reload-key="notificationReloadKey" />
            </n-tab-pane>

            <n-tab-pane name="auth" :tab="t('config.authenticationTab')">
              <AuthSettingsPanel :is-mobile="isMobile" />
            </n-tab-pane>

            <n-tab-pane name="worker" :tab="t('config.workerTab')">
              <WorkerSettingsPanel :is-mobile="isMobile" />
            </n-tab-pane>

            <n-tab-pane name="maintenance" :tab="t('config.maintenanceTab')">
              <MaintenancePanel />
            </n-tab-pane>

            <n-tab-pane name="prompt-templates" :tab="t('config.promptTemplatesTab')">
              <PromptTemplatesPanel ref="promptTemplatesPanelRef" />
            </n-tab-pane>
          </n-tabs>
        </div>
      </n-spin>
    </n-space>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import {
  NAlert,
  NCard,
  NGrid,
  NGi,
  NSpace,
  NSpin,
  NTabPane,
  NTag,
  NTabs
} from 'naive-ui'
import { useWindowSize } from '@vueuse/core'
import { useI18n } from 'vue-i18n'

// Panel components
import RuntimeSettingsPanel from './config/RuntimeSettingsPanel.vue'
import GitLabSettingsPanel from './config/GitLabSettingsPanel.vue'
import AuthSettingsPanel from './config/AuthSettingsPanel.vue'
import MaintenancePanel from './config/MaintenancePanel.vue'
import PromptTemplatesPanel from './config/PromptTemplatesPanel.vue'

// External components
import MattermostNotificationsPanel from '../components/config/MattermostNotificationsPanel.vue'
import OidcDiagnosticsPanel from '../components/config/OidcDiagnosticsPanel.vue'
import WorkerSettingsPanel from '../components/config/WorkerSettingsPanel.vue'

// Composable
import { provideConfigForm, useConfigForm } from './config/useConfigForm'
import { getConfig } from '../api'

const { t } = useI18n()
const route = useRoute()
const { width } = useWindowSize()
const isMobile = computed(() => width.value < 768)

// Provide shared config form state to all panel components
const {
  formValue,
  loading,
  isDirty,
  syncForm,
  fetchConfig
} = provideConfigForm()

// Panel refs
const gitlabPanelRef = ref<InstanceType<typeof GitLabSettingsPanel> | null>(null)
const promptTemplatesPanelRef = ref<InstanceType<typeof PromptTemplatesPanel> | null>(null)

// Tab state
const activeConfigTab = ref<'runtime' | 'notifications' | 'gitlab' | 'auth' | 'worker' | 'maintenance' | 'prompt-templates'>('runtime')
const configTabs = ['runtime', 'notifications', 'gitlab', 'auth', 'worker', 'maintenance', 'prompt-templates'] as const
type ConfigTabKey = typeof configTabs[number]

const notificationReloadKey = ref(0)

// Summary items
const sharedPagesEnabledCount = computed(
  () =>
    [
      formValue.value.allow_monitor_for_users,
      formValue.value.allow_schedule_overview_for_users,
      formValue.value.allow_analytics_for_users
    ].filter(Boolean).length
)

const summaryItems = computed(() => [
  { label: t('config.maxConcurrency'), value: String(formValue.value.max_concurrency) },
  { label: t('config.taskTimeout'), value: `${formValue.value.task_timeout}s` },
  { label: t('config.oidcLogin'), value: formValue.value.oidc_enabled ? t('common.enabled') : t('common.disabled') },
  { label: t('config.sharedPages'), value: String(sharedPagesEnabledCount.value) }
])

// Load initial config
async function loadConfig() {
  try {
    const config = await getConfig()
    syncForm(config)
    // Trigger webhook statuses fetch
    gitlabPanelRef.value?.fetchWebhookStatuses()
  } catch (error) {
    console.error('Failed to load config:', error)
  }
}

// Watch for tab changes
watch(activeConfigTab, (tab) => {
  if (tab === 'prompt-templates' && promptTemplatesPanelRef.value) {
    promptTemplatesPanelRef.value.fetchPromptTemplates()
  }
})

// Watch route query for tab
watch(
  () => route.query.tab,
  (tab) => {
    if (typeof tab === 'string' && configTabs.includes(tab as ConfigTabKey)) {
      activeConfigTab.value = tab as ConfigTabKey
    }
  },
  { immediate: true }
)

onMounted(() => {
  loadConfig()
})
</script>

<style scoped>
.config-page {
  max-width: 1240px;
}

.config-page__hero {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 16px;
  flex-wrap: wrap;
}

.config-page__title {
  margin: 0;
  font-size: 24px;
  font-weight: 600;
}

.config-page__subtitle {
  margin: 4px 0 0;
  color: var(--text-color-secondary);
}

.config-summary-card {
  text-align: center;
}

.config-summary-card__label {
  font-size: 12px;
  color: var(--text-color-secondary);
}

.config-summary-card__value {
  font-size: 20px;
  font-weight: 600;
  margin-top: 4px;
}

.config-tabs {
  margin-top: 8px;
}

.config-layout__main {
  padding: 8px 0;
}

.config-form-card {
  margin-bottom: 16px;
}

.config-card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.config-card-header--stacked {
  flex-direction: column;
  align-items: flex-start;
  gap: 12px;
}

.config-card-header__title {
  font-size: 16px;
  font-weight: 600;
}

.config-card-header__subtitle {
  font-size: 13px;
  color: var(--text-color-secondary);
  margin-top: 2px;
}

.config-form__section {
  margin-bottom: 24px;
}

.config-form__section:last-child {
  margin-bottom: 0;
}

.config-form__section-title {
  font-size: 14px;
  font-weight: 500;
  margin-bottom: 12px;
  color: var(--text-color);
}

.config-section-form {
  max-width: 800px;
}

.config-form__input {
  width: 100%;
}

.config-card-actions {
  margin-top: 16px;
  padding-top: 16px;
  border-top: 1px solid var(--border-color);
}

.config-page-actions {
  padding: 8px 0;
}

.config-actions__alert {
  margin-top: 12px;
}

.config-table-wrapper {
  margin-top: 16px;
  border: 1px solid var(--border-color);
  border-radius: 4px;
}

.config-webhook-project {
  display: flex;
  flex-direction: column;
}

.config-webhook-project__name {
  font-weight: 500;
}

.config-webhook-project__meta {
  font-size: 12px;
  color: var(--text-color-secondary);
}

.config-webhook-checks {
  display: flex;
  flex-direction: column;
  gap: 2px;
  font-size: 12px;
  color: var(--text-color-secondary);
}

.config-webhook-summary {
  margin-bottom: 16px;
}

.config-webhook-mobile__empty {
  text-align: center;
  padding: 24px;
  color: var(--text-color-secondary);
}

.config-webhook-mobile__item {
  padding: 12px;
  border: 1px solid var(--border-color);
  border-radius: 4px;
  margin-bottom: 8px;
}

.config-webhook-mobile__item-top {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}

.config-webhook-mobile__item-tags {
  display: flex;
  gap: 8px;
  margin-bottom: 4px;
}

.config-webhook-mobile__item-detail {
  font-size: 12px;
  color: var(--text-color-secondary);
}

.prompt-template-content-preview {
  font-family: monospace;
  font-size: 12px;
}
</style>
