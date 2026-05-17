<template>
  <div class="config-layout__main">
    <n-card id="announcement-settings" class="config-form-card" :bordered="false">
      <template #header>
        <div class="config-card-header">
          <div>
            <div class="config-card-header__title">{{ t('config.announcement.title') }}</div>
            <div class="config-card-header__subtitle">{{ t('config.announcement.subtitle') }}</div>
          </div>
        </div>
      </template>

      <n-spin :show="loading">
        <n-form ref="formRef" :model="formValue" label-placement="top" class="config-section-form">
          <div class="config-form__section">
            <n-grid :cols="isMobile ? 1 : 2" :x-gap="16" :y-gap="8">
              <n-gi :span="isMobile ? 1 : 2">
                <n-form-item :label="t('config.announcement.enabled')" path="announcement_enabled">
                  <n-switch v-model:value="formValue.announcement_enabled" />
                  <template #feedback>
                    {{ t('config.announcement.enabledHint') }}
                  </template>
                </n-form-item>
              </n-gi>

              <n-gi :span="isMobile ? 1 : 2">
                <n-form-item :label="t('config.announcement.level')" path="announcement_level">
                  <n-select
                    v-model:value="formValue.announcement_level"
                    :options="levelOptions"
                    style="width: 140px"
                  />
                  <template #feedback>
                    {{ t('config.announcement.levelHint') }}
                  </template>
                </n-form-item>
              </n-gi>

              <n-gi :span="isMobile ? 1 : 2">
                <n-form-item :label="t('config.announcement.text')" path="announcement_text">
                  <n-input
                    v-model:value="formValue.announcement_text"
                    type="textarea"
                    :autosize="{ minRows: 2, maxRows: 5 }"
                    :placeholder="t('config.announcement.textPlaceholder')"
                    class="config-form__input"
                  />
                  <template #feedback>
                    {{ t('config.announcement.textHint') }}
                  </template>
                </n-form-item>
              </n-gi>
            </n-grid>
          </div>

          <div class="config-form__actions">
            <n-button type="primary" :loading="saving" @click="handleSave">
              {{ t('common.save') }}
            </n-button>
          </div>
        </n-form>
      </n-spin>
    </n-card>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { NButton, NCard, NForm, NFormItem, NGrid, NGi, NInput, NSelect, NSpin, NSwitch } from 'naive-ui'
import { useMessage } from 'naive-ui'
import { useI18n } from 'vue-i18n'
import { getConfig, updateConfig } from '../../api'

defineProps<{
  isMobile: boolean
}>()

const { t } = useI18n()
const message = useMessage()

const loading = ref(false)
const saving = ref(false)
const formRef = ref()

const formValue = ref({
  announcement_enabled: false,
  announcement_text: '',
  announcement_level: 'info',
})

const levelOptions = computed(() => [
  { label: t('config.announcement.levelInfo'), value: 'info' },
  { label: t('config.announcement.levelWarning'), value: 'warning' },
  { label: t('config.announcement.levelError'), value: 'error' },
  { label: t('config.announcement.levelSuccess'), value: 'success' },
])

async function loadConfig() {
  loading.value = true
  try {
    const config = await getConfig()
    formValue.value.announcement_enabled = config.runtime.announcement_enabled
    formValue.value.announcement_text = config.runtime.announcement_text
    formValue.value.announcement_level = config.runtime.announcement_level || 'info'
  } catch {
    message.error(t('common.loadFailed'))
  } finally {
    loading.value = false
  }
}

async function handleSave() {
  saving.value = true
  try {
    await updateConfig({
      runtime: {
        announcement_enabled: formValue.value.announcement_enabled,
        announcement_text: formValue.value.announcement_text,
        announcement_level: formValue.value.announcement_level,
      }
    })
    message.success(t('common.saveSuccess'))
  } catch {
    message.error(t('common.saveFailed'))
  } finally {
    saving.value = false
  }
}

onMounted(() => {
  loadConfig()
})
</script>
