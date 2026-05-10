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
          <div class="config-system-cleanup__retention-field">
            <n-input-number
              v-model:value="cleanupOlderThanDays"
              data-test="cleanup-older-than-days-input"
              class="config-system-cleanup__days-input"
              :min="1"
              clearable
              :placeholder="t('config.cleanupOlderThanDaysPlaceholder')"
            />
            <span class="config-system-cleanup__unit">{{ t('config.cleanupOlderThanDaysUnit') }}</span>
          </div>
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

        <n-button
          data-test="cleanup-system-data-button"
          type="error"
          secondary
          :loading="cleanupLoading"
          :disabled="isBusy"
          class="config-system-cleanup__action"
          @click="openCleanupConfirm"
        >
          {{ t('config.cleanSystemData') }}
        </n-button>
      </div>
    </n-card>

    <n-modal
      v-model:show="cleanupConfirmVisible"
      preset="card"
      :closable="false"
      :mask-closable="!cleanupLoading"
      class="config-editor-modal config-cleanup-confirm"
    >
      <div class="config-cleanup-confirm__body">
        <div class="config-cleanup-confirm__icon">!</div>
        <div class="config-cleanup-confirm__content">
          <div class="config-cleanup-confirm__title">{{ t('config.cleanSystemData') }}</div>
          <div class="config-cleanup-confirm__text">
            {{
              forceCleanupActiveTasks
                ? t('config.confirmForceCleanSystemData')
                : t('config.confirmCleanSystemData')
            }}
          </div>
          <n-alert
            v-if="forceCleanupActiveTasks"
            type="warning"
            :bordered="false"
            class="config-cleanup-confirm__warning"
          >
            {{ t('config.forceCleanupActiveTasksWarning') }}
          </n-alert>
        </div>
      </div>

      <template #footer>
        <div class="config-cleanup-confirm__footer">
          <n-button :disabled="cleanupLoading" @click="cleanupConfirmVisible = false">
            {{ t('common.cancel') }}
          </n-button>
          <n-button
            data-test="confirm-cleanup-system-data-button"
            type="error"
            :loading="cleanupLoading"
            @click="handleCleanupSystemData"
          >
            {{ t('config.cleanSystemData') }}
          </n-button>
        </div>
      </template>
    </n-modal>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { NAlert, NButton, NCard, NFormItem, NInputNumber, NModal, NSpace, NSwitch, useMessage } from 'naive-ui'
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
const cleanupConfirmVisible = ref(false)

const isBusy = computed(() =>
  loading.value ||
  pageActionLoading.value ||
  anySectionSaving.value ||
  cleanupLoading.value
)

function openCleanupConfirm() {
  cleanupConfirmVisible.value = true
}

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
    cleanupConfirmVisible.value = false
  } catch (error: any) {
    message.error(error?.response?.data?.detail || t('config.systemDataCleanupFailed'))
  } finally {
    cleanupLoading.value = false
  }
}
</script>

<style scoped>
.config-system-cleanup__retention-field {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  max-width: 220px;
}

.config-system-cleanup__days-input {
  width: 132px;
}

.config-system-cleanup__unit {
  font-size: 13px;
  color: rgba(15, 23, 42, 0.62);
  white-space: nowrap;
}

.config-system-cleanup__warning {
  max-width: 720px;
}

.config-system-cleanup__action {
  justify-self: flex-start;
}

.config-cleanup-confirm {
  width: min(460px, calc(100vw - 32px));
}

.config-cleanup-confirm__body {
  display: grid;
  grid-template-columns: 40px 1fr;
  gap: 14px;
  align-items: start;
}

.config-cleanup-confirm__icon {
  display: grid;
  width: 40px;
  height: 40px;
  place-items: center;
  border-radius: 10px;
  background: rgba(220, 38, 38, 0.1);
  color: #b91c1c;
  font-size: 20px;
  font-weight: 700;
  line-height: 1;
}

.config-cleanup-confirm__content {
  display: grid;
  gap: 8px;
}

.config-cleanup-confirm__title {
  font-size: 16px;
  font-weight: 700;
  line-height: 1.35;
  color: #0f172a;
}

.config-cleanup-confirm__text {
  font-size: 13px;
  line-height: 1.55;
  color: rgba(15, 23, 42, 0.68);
}

.config-cleanup-confirm__warning {
  margin-top: 2px;
}

.config-cleanup-confirm__footer {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
}

@media (max-width: 560px) {
  .config-system-cleanup__retention-field {
    width: 100%;
    max-width: 100%;
  }

  .config-system-cleanup__days-input {
    width: min(150px, 50vw);
  }

  .config-cleanup-confirm__body {
    grid-template-columns: 1fr;
  }

  .config-cleanup-confirm__footer {
    flex-direction: column-reverse;
  }
}
</style>
