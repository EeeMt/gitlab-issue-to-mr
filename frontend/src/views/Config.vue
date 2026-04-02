<template>
  <div class="config-page">
    <n-space vertical :size="16">
      <PageHeader
        root-class="config-page__hero"
        title-class="config-page__title"
        subtitle-class="config-page__subtitle"
        :title="t('config.title')"
        :subtitle="t('config.subtitle')"
      >
        <template #actions>
          <n-space :size="8" wrap>
            <n-tag v-if="isDirty" size="small" round type="warning">{{ t('config.unsavedChanges') }}</n-tag>
            <n-tag v-else size="small" round type="success">{{ t('config.inSync') }}</n-tag>
            <n-tag size="small" round type="info">{{ t('config.dbOverride') }}</n-tag>
            <n-tag size="small" round>{{ t('config.envFallback') }}</n-tag>
            <n-tag size="small" round>{{ t('config.defaultFallback') }}</n-tag>
          </n-space>
        </template>
      </PageHeader>

      <n-alert type="info" :show-icon="false">
        {{ t('config.secretInfo') }}
      </n-alert>

      <n-grid :cols="isMobile ? 2 : 4" :x-gap="16" :y-gap="16">
        <n-gi v-for="item in summaryItems" :key="item.label">
          <SummaryCard
            :label="item.label"
            :value="item.value"
            card-class="config-summary-card"
            label-class="config-summary-card__label"
            value-class="config-summary-card__value"
          />
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
              <PromptTemplatesPanel ref="promptTemplatesPanelRef" :is-mobile="isMobile" />
            </n-tab-pane>
          </n-tabs>
        </div>
      </n-spin>
    </n-space>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import {
  NAlert,
  NGrid,
  NGi,
  NSpace,
  NSpin,
  NTabPane,
  NTag,
  NTabs
} from 'naive-ui'
import { useI18n } from 'vue-i18n'
import PageHeader from '../components/PageHeader.vue'
import SummaryCard from '../components/SummaryCard.vue'
import { useBreakpoints } from '../composables/useBreakpoints'

// Panel components
import RuntimeSettingsPanel from './config/RuntimeSettingsPanel.vue'
import GitLabSettingsPanel from './config/GitLabSettingsPanel.vue'
import AuthSettingsPanel from './config/AuthSettingsPanel.vue'
import MaintenancePanel from './config/MaintenancePanel.vue'
import PromptTemplatesPanel from './config/PromptTemplatesPanel.vue'

// External components
import MattermostNotificationsPanel from '../components/config/MattermostNotificationsPanel.vue'
import WorkerSettingsPanel from '../components/config/WorkerSettingsPanel.vue'

// Composable
import { provideConfigForm } from './config/useConfigForm'
import { getConfig } from '../api'

const { t } = useI18n()
const route = useRoute()
const { isMobile } = useBreakpoints()

// Provide shared config form state to all panel components
const {
  formValue,
  loading,
  isDirty,
  syncForm
} = provideConfigForm()

// Panel refs
const gitlabPanelRef = ref<InstanceType<typeof GitLabSettingsPanel> | null>(null)
const promptTemplatesPanelRef = ref<InstanceType<typeof PromptTemplatesPanel> | null>(null)

// Tab state
const activeConfigTab = ref<'runtime' | 'notifications' | 'gitlab' | 'auth' | 'worker' | 'maintenance' | 'prompt-templates'>('runtime')
const configTabs = ['runtime', 'notifications', 'gitlab', 'auth', 'worker', 'maintenance', 'prompt-templates'] as const
type ConfigTabKey = typeof configTabs[number]

const notificationReloadKey = ref(0)

async function fetchPromptTemplatesIfNeeded() {
  if (activeConfigTab.value !== 'prompt-templates') {
    return
  }

  await nextTick()
  promptTemplatesPanelRef.value?.fetchPromptTemplates()
}

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
    await fetchPromptTemplatesIfNeeded()
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

<style src="../styles/config-panels.css"></style>

<style scoped>
.config-page {
  max-width: var(--app-page-max-width);
}

.config-summary-card {
  min-height: 100%;
}

.config-summary-card__label {
  text-align: center;
}

.config-summary-card__value {
  margin-top: 4px;
  text-align: center;
}

.config-tabs {
  margin-top: 8px;
}
</style>
