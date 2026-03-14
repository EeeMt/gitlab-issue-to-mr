<template>
  <div class="config-page">
    <n-space vertical :size="16">
      <div class="config-page__hero">
        <div>
          <h2 class="config-page__title">Configuration</h2>
          <p class="config-page__subtitle">
            Update runtime scheduler settings and persist them across service restarts.
          </p>
        </div>
        <n-space :size="8" wrap>
          <n-tag size="small" round type="info">DB override</n-tag>
          <n-tag size="small" round>env fallback</n-tag>
          <n-tag size="small" round>default fallback</n-tag>
        </n-space>
      </div>

      <n-alert type="info" :show-icon="false">
        Changes saved here take effect for the backend and scheduler. “Reset to defaults” removes DB overrides and falls back to env/default values.
      </n-alert>

      <n-grid :cols="isMobile ? 1 : 4" :x-gap="16" :y-gap="16">
        <n-gi v-for="item in summaryItems" :key="item.label">
          <n-card size="small" class="config-summary-card" :bordered="false">
            <div class="config-summary-card__label">{{ item.label }}</div>
            <div class="config-summary-card__value">{{ item.value }}</div>
          </n-card>
        </n-gi>
      </n-grid>

      <n-card title="Runtime Settings" class="config-form-card">
        <template #header-extra>
          <n-space :size="8" align="center">
            <n-tag v-if="isDirty" size="small" type="warning" round>
              Unsaved changes
            </n-tag>
            <n-tag v-else size="small" type="success" round>
              In sync
            </n-tag>
          </n-space>
        </template>

        <n-spin :show="loading">
          <n-form
            ref="formRef"
            :model="formValue"
            :rules="rules"
            label-placement="top"
            class="config-form"
          >
            <div class="config-form__section">
              <div class="config-form__section-title">Scheduler</div>
              <n-grid :cols="isMobile ? 1 : 2" :x-gap="16" :y-gap="8">
                <n-gi>
                  <n-form-item label="Max Concurrency" path="max_concurrency">
                    <n-input-number
                      v-model:value="formValue.max_concurrency"
                      :min="1"
                      :max="20"
                      class="config-form__input"
                    />
                    <template #feedback>
                      Maximum number of tasks that can run simultaneously.
                    </template>
                  </n-form-item>
                </n-gi>

                <n-gi>
                  <n-form-item label="Scheduler Interval (seconds)" path="scheduler_interval">
                    <n-input-number
                      v-model:value="formValue.scheduler_interval"
                      :min="1"
                      :max="60"
                      class="config-form__input"
                    />
                    <template #feedback>
                      How often the scheduler checks for new tasks.
                    </template>
                  </n-form-item>
                </n-gi>
              </n-grid>
            </div>

            <div class="config-form__section">
              <div class="config-form__section-title">Task Execution</div>
              <n-grid :cols="isMobile ? 1 : 2" :x-gap="16" :y-gap="8">
                <n-gi>
                  <n-form-item label="Task Timeout (seconds)" path="task_timeout">
                    <n-input-number
                      v-model:value="formValue.task_timeout"
                      :min="60"
                      :max="7200"
                      class="config-form__input"
                    />
                    <template #feedback>
                      Maximum time a task can run before being marked as failed.
                    </template>
                  </n-form-item>
                </n-gi>

                <n-gi>
                  <n-form-item label="Default Target Branch" path="default_target_branch">
                    <n-input
                      v-model:value="formValue.default_target_branch"
                      placeholder="main"
                      class="config-form__input"
                    />
                    <template #feedback>
                      Default branch used when creating merge requests.
                    </template>
                  </n-form-item>
                </n-gi>
              </n-grid>
            </div>

            <div class="config-form__actions">
              <n-space :size="12" wrap>
                <n-button
                  type="primary"
                  @click="handleSave"
                  :loading="saving"
                  :disabled="loading || saving || !isDirty"
                >
                  Save changes
                </n-button>
                <n-button @click="handleReload" :disabled="loading || saving">
                  Reload
                </n-button>
                <n-button @click="handleReset" :disabled="loading || saving" secondary>
                  Reset to defaults
                </n-button>
              </n-space>
            </div>
          </n-form>
        </n-spin>
      </n-card>
    </n-space>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import {
  NAlert,
  NButton,
  NCard,
  NForm,
  NFormItem,
  NGi,
  NGrid,
  NInput,
  NInputNumber,
  NSpace,
  NSpin,
  NTag,
  useMessage,
  type FormInst,
  type FormRules
} from 'naive-ui'
import { useWindowSize } from '@vueuse/core'
import { getConfig, resetConfig, updateConfig, type Config } from '../api'

const message = useMessage()
const { width } = useWindowSize()
const isMobile = computed(() => width.value < 768)

const loading = ref(false)
const saving = ref(false)
const formRef = ref<FormInst | null>(null)

const formValue = ref<Config>({
  max_concurrency: 3,
  task_timeout: 1800,
  scheduler_interval: 5,
  default_target_branch: 'main'
})

const lastLoadedValue = ref<Config>({
  ...formValue.value
})

const isDirty = computed(() =>
  JSON.stringify(formValue.value) !== JSON.stringify(lastLoadedValue.value)
)

const summaryItems = computed(() => [
  { label: 'Max Concurrency', value: String(formValue.value.max_concurrency) },
  { label: 'Task Timeout', value: `${formValue.value.task_timeout}s` },
  { label: 'Scheduler Interval', value: `${formValue.value.scheduler_interval}s` },
  { label: 'Target Branch', value: formValue.value.default_target_branch }
])

const rules: FormRules = {
  max_concurrency: {
    required: true,
    type: 'number',
    message: 'Please enter max concurrency',
    trigger: 'blur'
  },
  task_timeout: {
    required: true,
    type: 'number',
    message: 'Please enter task timeout',
    trigger: 'blur'
  },
  scheduler_interval: {
    required: true,
    type: 'number',
    message: 'Please enter scheduler interval',
    trigger: 'blur'
  },
  default_target_branch: {
    required: true,
    message: 'Please enter default target branch',
    trigger: 'blur'
  }
}

function syncForm(config: Config) {
  formValue.value = { ...config }
  lastLoadedValue.value = { ...config }
}

async function fetchConfig() {
  loading.value = true
  try {
    const config = await getConfig()
    syncForm(config)
  } catch (error) {
    message.error('Failed to fetch config')
  } finally {
    loading.value = false
  }
}

async function handleSave() {
  const valid = await formRef.value?.validate().then(() => true).catch(() => false)
  if (!valid) {
    return
  }

  saving.value = true
  try {
    syncForm(await updateConfig(formValue.value))
    message.success('Configuration saved')
  } catch (error) {
    message.error('Failed to save config')
  } finally {
    saving.value = false
  }
}

async function handleReset() {
  saving.value = true
  try {
    syncForm(await resetConfig())
    message.success('Configuration reset to env/default values')
  } catch (error) {
    message.error('Failed to reset config')
  } finally {
    saving.value = false
  }
}

function handleReload() {
  fetchConfig()
}

onMounted(() => {
  fetchConfig()
})
</script>

<style scoped>
.config-page {
  max-width: 1080px;
}

.config-page__hero {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 16px;
}

.config-page__title {
  margin: 0;
  font-size: 28px;
  line-height: 1.2;
}

.config-page__subtitle {
  margin: 8px 0 0;
  color: rgba(15, 23, 42, 0.68);
  max-width: 720px;
}

.config-summary-card {
  background: linear-gradient(180deg, rgba(32, 128, 240, 0.06), rgba(32, 128, 240, 0.02));
  border-radius: 12px;
}

.config-summary-card__label {
  font-size: 12px;
  color: rgba(15, 23, 42, 0.6);
  margin-bottom: 8px;
}

.config-summary-card__value {
  font-size: 20px;
  font-weight: 600;
  color: var(--n-text-color-1);
  word-break: break-word;
}

.config-form-card {
  border-radius: 16px;
}

.config-form {
  margin-top: 8px;
}

.config-form__section + .config-form__section {
  margin-top: 8px;
}

.config-form__section-title {
  margin-bottom: 12px;
  font-size: 13px;
  font-weight: 600;
  letter-spacing: 0.02em;
  color: rgba(15, 23, 42, 0.62);
  text-transform: uppercase;
}

.config-form__input {
  width: 100%;
}

.config-form__actions {
  margin-top: 8px;
  padding-top: 8px;
  border-top: 1px solid rgba(15, 23, 42, 0.08);
}

@media (max-width: 767px) {
  .config-page__hero {
    flex-direction: column;
  }

  .config-page__title {
    font-size: 24px;
  }

  .config-page__subtitle {
    max-width: none;
  }
}
</style>
