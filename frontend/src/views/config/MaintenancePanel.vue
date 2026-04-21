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
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { NButton, NCard, NSpace } from 'naive-ui'
import { useI18n } from 'vue-i18n'
import { useConfigForm } from './useConfigForm'

const { t } = useI18n()

// Use shared config form
const {
  loading,
  pageActionLoading,
  anySectionSaving,
  handleReload,
  handleReset
} = useConfigForm()

const isBusy = computed(() =>
  loading.value ||
  pageActionLoading.value ||
  anySectionSaving.value
)
</script>
