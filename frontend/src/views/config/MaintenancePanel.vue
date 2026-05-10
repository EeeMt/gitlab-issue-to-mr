<template>
  <div class="config-layout__main">
    <n-card id="config-actions" class="config-form-card" :bordered="false">
      <template #header>
        <div class="config-card-header">
          <div>
            <div class="config-card-header__title">{{ t('config.actions') }}</div>
            <div class="config-card-header__subtitle">{{ t('config.actionsSubtitle') }}</div>
          </div>
        </div>
      </template>

      <div class="config-form__section config-page-actions">
        <n-space :size="12" wrap>
          <n-button @click="handleReload" :disabled="isBusy">
            {{ t('common.reload') }}
          </n-button>
          <n-button @click="handleReset" :loading="pageActionLoading" :disabled="isBusy" secondary>
            {{ t('config.resetEnvDefaults') }}
          </n-button>
        </n-space>
      </div>
    </n-card>

    <n-card id="system-data-cleanup" class="config-form-card" :bordered="false">
      <template #header>
        <div class="config-card-header">
          <div>
            <div class="config-card-header__title">{{ t('config.systemDataCleanup') }}</div>
            <div class="config-card-header__subtitle">{{ t('config.systemDataCleanupSubtitle') }}</div>
          </div>
        </div>
      </template>

      <div class="config-form__section config-system-cleanup">
        <n-form-item :label="t('config.cleanupOlderThanDays')">
          <n-input-number
            v-model:value="cleanupOlderThanDays"
            data-test="cleanup-older-than-days-input"
            class="config-form__input"
            :min="1"
            clearable
            :placeholder="t('config.cleanupOlderThanDaysPlaceholder')"
          />
        </n-form-item>

        <div class="config-inline-toggle">
          <div class="config-inline-toggle__content">
            <div class="config-inline-toggle__label">{{ t('config.forceCleanupActiveTasks') }}</div>
            <div class="config-inline-toggle__hint">{{ t('config.forceCleanupActiveTasksHint') }}</div>
          </div>
          <n-switch
            v-model:value="forceCleanupActiveTasks"
            data-test="force-cleanup-active-switch"
            :disabled="cleanupLoading"
          />
        </div>

        <n-alert
          v-if="forceCleanupActiveTasks"
          type="warning"
          :bordered="false"
          class="config-system-cleanup__warning"
        >
          {{ t('config.forceCleanupActiveTasksWarning') }}
        </n-alert>

        <n-popconfirm
          :positive-text="t('config.cleanSystemData')"
          :negative-text="t('common.cancel')"
          @positive-click="handleCleanupSystemData"
        >
          <template #trigger>
            <n-button
              data-test="cleanup-system-data-button"
              type="error"
              secondary
              :loading="cleanupLoading"
              :disabled="isBusy"
            >
              {{ t('config.cleanSystemData') }}
            </n-button>
          </template>
          {{
            forceCleanupActiveTasks
              ? t('config.confirmForceCleanSystemData')
              : t('config.confirmCleanSystemData')
          }}
        </n-popconfirm>
      </div>
    </n-card>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { NAlert, NButton, NCard, NFormItem, NInputNumber, NPopconfirm, NSpace, NSwitch, useMessage } from 'naive-ui'
import { useI18n } from 'vue-i18n'
import { cleanupSystemData } from '../../api'
import { useConfigForm } from './useConfigForm'

const { t } = useI18n()
const message = useMessage()

// Use shared config form
const {
  loading,
  pageActionLoading,
  anySectionSaving,
  handleReload,
  handleReset
} = useConfigForm()

const cleanupOlderThanDays = ref<number | null>(null)
const forceCleanupActiveTasks = ref(false)
const cleanupLoading = ref(false)

const isBusy = computed(() =>
  loading.value ||
  pageActionLoading.value ||
  anySectionSaving.value ||
  cleanupLoading.value
)

async function handleCleanupSystemData() {
  cleanupLoading.value = true
  try {
    const result = await cleanupSystemData({
      older_than_days: cleanupOlderThanDays.value,
      force: forceCleanupActiveTasks.value
    })
    message.success(t('config.systemDataCleanupSuccess', {
      issues: result.deleted_issues,
      tasks: result.deleted_tasks,
      skipped: result.skipped_active_issues
    }))
  } catch (error: any) {
    message.error(error?.response?.data?.detail || t('config.systemDataCleanupFailed'))
  } finally {
    cleanupLoading.value = false
  }
}
</script>
