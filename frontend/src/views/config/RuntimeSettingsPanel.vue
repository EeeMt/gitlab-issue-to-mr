<template>
  <div class="config-layout__main">
    <n-card id="runtime-settings" class="config-form-card" :bordered="false">
      <template #header>
        <div class="config-card-header">
          <div>
            <div class="config-card-header__title">{{ t('config.runtimeSettings') }}</div>
            <div class="config-card-header__subtitle">{{ t('config.runtimeSettingsSubtitle') }}</div>
          </div>
        </div>
      </template>

      <n-form ref="runtimeFormRef" :model="formValue" :rules="runtimeRules" label-placement="top" class="config-section-form">
        <div class="config-form__section">
          <div class="config-form__section-title">{{ t('config.scheduler') }}</div>
          <n-grid :cols="isMobile ? 1 : 2" :x-gap="16" :y-gap="8">
            <n-gi>
              <n-form-item :label="t('config.maxConcurrency')" path="max_concurrency">
                <n-input-number
                  v-model:value="formValue.max_concurrency"
                  :min="1"
                  :max="20"
                  class="config-form__input"
                />
                <template #feedback>
                  {{ t('config.maxConcurrencyHint') }}
                </template>
              </n-form-item>
            </n-gi>
            <n-gi>
              <n-form-item :label="t('config.schedulerInterval')" path="scheduler_interval">
                <n-input-number
                  v-model:value="formValue.scheduler_interval"
                  :min="1"
                  :max="60"
                  class="config-form__input"
                />
                <template #feedback>
                  {{ t('config.schedulerIntervalHint') }}
                </template>
              </n-form-item>
            </n-gi>
            <n-gi>
              <n-form-item :label="t('config.taskTimeout')" path="task_timeout">
                <n-input-number
                  v-model:value="formValue.task_timeout"
                  :min="60"
                  :max="7200"
                  class="config-form__input"
                />
                <template #feedback>
                  {{ t('config.taskTimeoutHint') }}
                </template>
              </n-form-item>
            </n-gi>
            <n-gi>
              <n-form-item :label="t('config.defaultTargetBranch')" path="default_target_branch">
                <n-input
                  v-model:value="formValue.default_target_branch"
                  placeholder="main"
                  class="config-form__input"
                />
                <template #feedback>
                  {{ t('config.defaultTargetBranchHint') }}
                </template>
              </n-form-item>
            </n-gi>
          </n-grid>
        </div>

        <div class="config-form__section">
          <div class="config-form__section-title">{{ t('config.retryAndAlerts') }}</div>
          <n-grid :cols="isMobile ? 1 : 2" :x-gap="16" :y-gap="8">
            <n-gi>
              <n-form-item :label="t('config.maxRetries')" path="max_retries">
                <n-input-number
                  v-model:value="formValue.max_retries"
                  :min="0"
                  :max="10"
                  class="config-form__input"
                />
                <template #feedback>
                  {{ t('config.maxRetriesHint') }}
                </template>
              </n-form-item>
            </n-gi>
            <n-gi>
              <n-form-item :label="t('config.retryDelay')" path="retry_delay">
                <n-input-number
                  v-model:value="formValue.retry_delay"
                  :min="1"
                  :max="3600"
                  class="config-form__input"
                />
                <template #feedback>
                  {{ t('config.retryDelayHint') }}
                </template>
              </n-form-item>
            </n-gi>
            <n-gi>
              <n-form-item :label="t('config.alertOnFailure')" path="alert_on_failure">
                <n-switch v-model:value="formValue.alert_on_failure" />
                <template #feedback>
                  {{ t('config.alertOnFailureHint') }}
                </template>
              </n-form-item>
            </n-gi>
            <n-gi>
              <n-form-item :label="t('config.alertWebhookStatus')">
                <n-tag :type="formValue.alert_webhook_url_configured ? 'success' : 'warning'" round>
                  {{ formValue.alert_webhook_url_configured ? t('config.configured') : t('config.missing') }}
                </n-tag>
                <template #feedback>
                  {{ t('config.alertWebhookStatusHint') }}
                </template>
              </n-form-item>
            </n-gi>
            <n-gi :span="isMobile ? 1 : 2">
              <n-form-item :label="t('config.alertWebhookUrl')">
                <n-input
                  v-model:value="formValue.alert_webhook_url_input"
                  type="password"
                  show-password-on="click"
                  :placeholder="
                    formValue.alert_webhook_url_configured
                      ? t('config.configuredEnterNew')
                      : t('config.enterAlertWebhookUrl')
                  "
                  class="config-form__input"
                />
                <template #feedback>
                  {{ t('config.alertWebhookHint') }}
                </template>
              </n-form-item>
            </n-gi>
          </n-grid>
        </div>

        <div class="config-card-actions">
          <n-space :size="12" wrap>
            <n-button
              type="primary"
              @click="handleSaveSection('runtime')"
              :loading="sectionSaving.runtime"
              :disabled="isSectionBusy('runtime') || !isSectionDirty('runtime')"
            >
              {{ t('config.saveChanges') }}
            </n-button>
            <n-button
              secondary
              @click="resetSection('runtime')"
              :disabled="isSectionBusy('runtime') || !isSectionDirty('runtime')"
            >
              {{ t('config.revertChanges') }}
            </n-button>
            <n-button
              @click="handleClearSecret('alert_webhook_url')"
              :disabled="isSectionBusy('runtime') || !formValue.alert_webhook_url_configured"
            >
              {{ t('config.clearAlertWebhook') }}
            </n-button>
          </n-space>
        </div>
      </n-form>
    </n-card>

    <n-card id="shared-page-settings" class="config-form-card" :bordered="false">
      <template #header>
        <div class="config-card-header">
          <div>
            <div class="config-card-header__title">{{ t('config.sharedPageAccess') }}</div>
            <div class="config-card-header__subtitle">{{ t('config.sharedPageAccessSubtitle') }}</div>
          </div>
        </div>
      </template>

      <n-form :model="formValue" label-placement="top" class="config-section-form">
        <div class="config-form__section">
          <div class="config-form__section-title">{{ t('config.pagePermissions') }}</div>
          <n-grid :cols="isMobile ? 1 : 2" :x-gap="16" :y-gap="8">
            <n-gi>
              <n-form-item :label="t('config.allowMonitor')">
                <n-switch v-model:value="formValue.allow_monitor_for_users" />
                <template #feedback>
                  {{ t('config.allowMonitorHint') }}
                </template>
              </n-form-item>
            </n-gi>
            <n-gi>
              <n-form-item :label="t('config.allowScheduleOverview')">
                <n-switch v-model:value="formValue.allow_schedule_overview_for_users" />
                <template #feedback>
                  {{ t('config.allowScheduleOverviewHint') }}
                </template>
              </n-form-item>
            </n-gi>
            <n-gi>
              <n-form-item :label="t('config.allowAnalytics')">
                <n-switch v-model:value="formValue.allow_analytics_for_users" />
                <template #feedback>
                  {{ t('config.allowAnalyticsHint') }}
                </template>
              </n-form-item>
            </n-gi>
          </n-grid>
        </div>
        <div class="config-card-actions">
          <n-space :size="12" wrap>
            <n-button
              type="primary"
              @click="handleSaveSection('sharedPages')"
              :loading="sectionSaving.sharedPages"
              :disabled="isSectionBusy('sharedPages') || !isSectionDirty('sharedPages')"
            >
              {{ t('config.saveChanges') }}
            </n-button>
            <n-button
              secondary
              @click="resetSection('sharedPages')"
              :disabled="isSectionBusy('sharedPages') || !isSectionDirty('sharedPages')"
            >
              {{ t('config.revertChanges') }}
            </n-button>
          </n-space>
        </div>
      </n-form>
    </n-card>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import {
  NButton,
  NCard,
  NForm,
  NFormItem,
  NGi,
  NGrid,
  NInputNumber,
  NInput,
  NSpace,
  NSwitch,
  NTag,
  type FormInst,
  type FormRules
} from 'naive-ui'
import { useI18n } from 'vue-i18n'
import { useWindowSize } from '@vueuse/core'
import { useConfigForm } from './useConfigForm'

const props = defineProps<{
  isMobile?: boolean
}>()

const { t } = useI18n()
const { width } = useWindowSize()
const isMobile = computed(() => props.isMobile ?? width.value < 768)

// Use shared config form
const {
  formValue,
  sectionSaving,
  isSectionDirty,
  isSectionBusy,
  resetSection,
  handleSaveSection,
  handleClearSecret
} = useConfigForm()

// Form validation rules
const runtimeFormRef = ref<FormInst | null>(null)

const runtimeRules: FormRules = {
  max_concurrency: { required: true, type: 'number', message: t('config.enterMaxConcurrency'), trigger: 'blur' },
  task_timeout: { required: true, type: 'number', message: t('config.enterTaskTimeout'), trigger: 'blur' },
  scheduler_interval: {
    required: true,
    type: 'number',
    message: t('config.enterSchedulerInterval'),
    trigger: 'blur'
  },
  default_target_branch: {
    required: true,
    message: t('config.enterDefaultTargetBranch'),
    trigger: 'blur'
  },
  max_retries: {
    required: true,
    type: 'number',
    message: t('config.enterMaxRetries'),
    trigger: 'blur'
  },
  retry_delay: {
    required: true,
    type: 'number',
    message: t('config.enterRetryDelay'),
    trigger: 'blur'
  }
}
</script>
