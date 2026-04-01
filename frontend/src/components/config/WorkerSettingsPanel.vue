<template>
  <n-spin :show="loading">
    <div class="config-layout__main">
      <n-card class="config-form-card" :bordered="false">
        <template #header>
          <div class="config-card-header">
            <div>
              <div class="config-card-header__title">{{ t('config.aiProvider') }}</div>
              <div class="config-card-header__subtitle">{{ t('config.aiProviderSubtitle') }}</div>
            </div>
          </div>
        </template>

        <n-form
          ref="aiFormRef"
          :model="aiFormValue"
          :rules="aiRules"
          label-placement="top"
          class="config-section-form"
        >
          <div class="config-form__section">
            <n-grid :cols="isMobile ? 1 : 2" :x-gap="16" :y-gap="8">
              <n-gi>
                <n-form-item :label="t('config.anthropicBaseUrl')" path="anthropic_base_url">
                  <n-input
                    v-model:value="aiFormValue.anthropic_base_url"
                    placeholder="http://host.docker.internal:11434/v1"
                    class="config-form__input"
                  />
                  <template #feedback>
                    {{ t('config.anthropicBaseUrlHint') }}
                  </template>
                </n-form-item>
              </n-gi>
              <n-gi>
                <n-form-item :label="t('config.anthropicModel')" path="anthropic_model">
                  <n-input
                    v-model:value="aiFormValue.anthropic_model"
                    placeholder="claude-sonnet-4-20250514"
                    class="config-form__input"
                  />
                  <template #feedback>
                    {{ t('config.anthropicModelHint') }}
                  </template>
                </n-form-item>
              </n-gi>
              <n-gi>
                <n-form-item :label="t('config.claudeMaxTurns')" path="claude_max_turns">
                  <n-input-number
                    v-model:value="aiFormValue.claude_max_turns"
                    :min="1"
                    :max="1000"
                    class="config-form__input"
                  />
                  <template #feedback>
                    {{ t('config.claudeMaxTurnsHint') }}
                  </template>
                </n-form-item>
              </n-gi>
              <n-gi>
                <n-form-item :label="t('config.anthropicApiKeyStatus')">
                  <n-tag :type="aiFormValue.anthropic_api_key_configured ? 'success' : 'warning'" round>
                    {{ aiFormValue.anthropic_api_key_configured ? t('config.configured') : t('config.missing') }}
                  </n-tag>
                  <template #feedback>
                    {{ t('config.anthropicApiKeyStatusHint') }}
                  </template>
                </n-form-item>
              </n-gi>
              <n-gi :span="isMobile ? 1 : 2">
                <n-form-item :label="t('config.anthropicApiKey')">
                  <n-input
                    v-model:value="aiFormValue.anthropic_api_key_input"
                    type="password"
                    show-password-on="click"
                    :placeholder="
                      aiFormValue.anthropic_api_key_configured
                        ? t('config.configuredEnterNew')
                        : t('config.enterAnthropicApiKey')
                    "
                    class="config-form__input"
                  />
                  <template #feedback>
                    {{ t('config.anthropicApiKeyHint') }}
                  </template>
                </n-form-item>
              </n-gi>
            </n-grid>
          </div>

          <div class="config-card-actions">
            <n-space :size="12" wrap>
              <n-button
                type="primary"
                :loading="aiSaving"
                :disabled="isAiBusy || !isAiDirty"
                @click="handleSaveAi"
              >
                {{ t('config.saveChanges') }}
              </n-button>
              <n-button secondary :disabled="isAiBusy || !isAiDirty" @click="resetAi">
                {{ t('config.revertChanges') }}
              </n-button>
              <n-button
                :disabled="isAiBusy || !aiFormValue.anthropic_api_key_configured"
                @click="handleClearApiKey"
              >
                {{ t('config.clearAnthropicApiKey') }}
              </n-button>
            </n-space>
          </div>
        </n-form>
      </n-card>

      <n-card class="config-form-card" :bordered="false">
        <template #header>
          <div class="config-card-header">
            <div>
              <div class="config-card-header__title">{{ t('config.workerSettings') }}</div>
              <div class="config-card-header__subtitle">{{ t('config.workerSettingsSubtitle') }}</div>
            </div>
          </div>
        </template>

        <n-form :model="workerFormValue" label-placement="top" class="config-section-form">
          <div class="config-form__section">
            <div class="config-form__section-header">
              <div class="config-form__section-title">{{ t('config.volumeMounts') }}</div>
              <n-button size="small" @click="addMount">
                {{ t('config.addVolumeMount') }}
              </n-button>
            </div>
            <div v-if="workerFormValue.mounts.length === 0" class="config-empty">
              {{ t('config.noVolumeMounts') }}
            </div>
            <div v-else class="config-mounts-list">
              <div
                v-for="(mount, index) in workerFormValue.mounts"
                :key="index"
                class="config-mount-item"
              >
                <n-grid :cols="isMobile ? 1 : 3" :x-gap="12" :y-gap="8">
                  <n-gi>
                    <n-form-item :label="t('config.hostPath')" size="small">
                      <n-input
                        v-model:value="mount.host_path"
                        :placeholder="t('config.hostPathPlaceholder')"
                        class="config-form__input"
                      />
                    </n-form-item>
                  </n-gi>
                  <n-gi>
                    <n-form-item :label="t('config.containerPath')" size="small">
                      <n-input
                        v-model:value="mount.container_path"
                        :placeholder="t('config.containerPathPlaceholder')"
                        class="config-form__input"
                      />
                    </n-form-item>
                  </n-gi>
                  <n-gi>
                    <n-form-item :label="t('config.mountMode')" size="small">
                      <n-select
                        v-model:value="mount.mode"
                        :options="mountModeOptions"
                        class="config-form__input"
                      />
                    </n-form-item>
                  </n-gi>
                </n-grid>
                <n-button
                  size="tiny"
                  type="error"
                  quaternary
                  @click="removeMount(index)"
                  class="config-mount-remove"
                >
                  {{ t('config.remove') }}
                </n-button>
              </div>
            </div>
          </div>

          <div class="config-form__section config-maven-section">
            <div class="config-form__section-title">{{ t('config.mavenSettings') }}</div>
            <n-grid :cols="isMobile ? 1 : 2" :x-gap="16" :y-gap="8">
              <n-gi>
                <n-form-item :label="t('config.mavenCachePath')">
                  <n-input
                    v-model:value="workerFormValue.maven_cache_host_path"
                    :placeholder="t('config.mavenCachePathPlaceholder')"
                    class="config-form__input"
                  />
                  <template #feedback>
                    {{ t('config.mavenCachePathHint') }}
                  </template>
                </n-form-item>
              </n-gi>
              <n-gi>
                <n-form-item :label="t('config.mavenSettingsPath')">
                  <n-input
                    v-model:value="workerFormValue.maven_settings_host_path"
                    :placeholder="t('config.mavenSettingsPathPlaceholder')"
                    class="config-form__input"
                  />
                  <template #feedback>
                    {{ t('config.mavenSettingsPathHint') }}
                  </template>
                </n-form-item>
              </n-gi>
            </n-grid>
          </div>

          <div class="config-card-actions">
            <n-space :size="12" wrap>
              <n-button
                type="primary"
                :loading="workerSaving"
                :disabled="isWorkerBusy || !isWorkerDirty"
                @click="handleSaveWorker"
              >
                {{ t('config.saveChanges') }}
              </n-button>
              <n-button secondary :disabled="isWorkerBusy || !isWorkerDirty" @click="resetWorker">
                {{ t('config.revertChanges') }}
              </n-button>
            </n-space>
          </div>
        </n-form>
      </n-card>
    </div>
  </n-spin>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import {
  NButton,
  NCard,
  NForm,
  NFormItem,
  NGi,
  NGrid,
  NInput,
  NInputNumber,
  NSelect,
  NSpace,
  NSpin,
  NTag,
  useMessage,
  type FormInst,
  type FormRules
} from 'naive-ui'
import { useI18n } from 'vue-i18n'
import { getConfig, updateConfig, resetConfigKey } from '../../api'

type AiFormValue = {
  anthropic_base_url: string
  anthropic_api_key_configured: boolean
  anthropic_api_key_input: string
  anthropic_model: string
  claude_max_turns: number
}

type MountItem = {
  host_path: string
  container_path: string
  mode: 'ro' | 'rw'
}

type WorkerFormValue = {
  mounts: MountItem[]
  maven_cache_host_path: string
  maven_settings_host_path: string
}

const props = defineProps<{
  isMobile: boolean
  reloadKey?: number
}>()

const message = useMessage()
const { t } = useI18n()

const loading = ref(false)
const aiFormRef = ref<FormInst | null>(null)
const aiSaving = ref(false)
const workerSaving = ref(false)

const mountModeOptions = [
  { label: 'Read-only (ro)', value: 'ro' },
  { label: 'Read-write (rw)', value: 'rw' }
]

const aiFormValue = ref<AiFormValue>({
  anthropic_base_url: 'http://localhost:11434/v1',
  anthropic_api_key_configured: false,
  anthropic_api_key_input: '',
  anthropic_model: 'claude-sonnet-4-20250514',
  claude_max_turns: 20
})

const workerFormValue = ref<WorkerFormValue>({
  mounts: [],
  maven_cache_host_path: '',
  maven_settings_host_path: ''
})

const lastLoadedAi = ref({ ...aiFormValue.value })
const lastLoadedWorker = ref<WorkerFormValue>(createEmptyWorkerFormValue())

const isAiDirty = computed(() =>
  JSON.stringify(aiFormValue.value) !== JSON.stringify(lastLoadedAi.value)
)

const isWorkerDirty = computed(() =>
  JSON.stringify(workerFormValue.value) !== JSON.stringify(lastLoadedWorker.value)
)

const isAiBusy = computed(() => loading.value || aiSaving.value || workerSaving.value)
const isWorkerBusy = computed(() => loading.value || aiSaving.value || workerSaving.value)

const aiRules: FormRules = {
  anthropic_base_url: {
    required: true,
    message: t('config.enterAnthropicBaseUrl'),
    trigger: 'blur'
  },
  anthropic_model: {
    required: true,
    message: t('config.enterAnthropicModel'),
    trigger: 'blur'
  },
  claude_max_turns: {
    required: true,
    type: 'number',
    message: t('config.enterClaudeMaxTurns'),
    trigger: 'blur'
  }
}

function parseMounts(jsonStr: string): MountItem[] {
  if (!jsonStr || !jsonStr.trim()) return []
  try {
    const parsed = JSON.parse(jsonStr)
    if (Array.isArray(parsed)) {
      return parsed.map(m => ({
        host_path: m.host_path || '',
        container_path: m.container_path || '',
        mode: m.mode === 'rw' ? 'rw' : 'ro'
      }))
    }
    return []
  } catch {
    return []
  }
}

function serializeMounts(mounts: MountItem[]): string {
  return JSON.stringify(mounts.filter(m => m.host_path && m.container_path))
}

async function fetchConfig() {
  loading.value = true
  try {
    const config = await getConfig()
    aiFormValue.value = {
      anthropic_base_url: config.runtime.anthropic_base_url,
      anthropic_api_key_configured: config.runtime.anthropic_api_key_configured,
      anthropic_api_key_input: '',
      anthropic_model: config.runtime.anthropic_model,
      claude_max_turns: config.runtime.claude_max_turns
    }
    workerFormValue.value = {
      mounts: parseMounts(config.runtime.worker_volume_mounts),
      maven_cache_host_path: config.runtime.maven_cache_host_path || '',
      maven_settings_host_path: config.runtime.maven_settings_host_path || ''
    }
    lastLoadedAi.value = { ...aiFormValue.value }
    lastLoadedWorker.value = JSON.parse(JSON.stringify(workerFormValue.value))
  } catch {
    message.error(t('config.loadError'))
  } finally {
    loading.value = false
  }
}

async function handleSaveAi() {
  if (!aiFormRef.value) return

  try {
    await aiFormRef.value.validate()
  } catch {
    return
  }

  aiSaving.value = true
  try {
    const update: any = {
      runtime: {
        anthropic_base_url: aiFormValue.value.anthropic_base_url.trim(),
        anthropic_model: aiFormValue.value.anthropic_model.trim(),
        claude_max_turns: aiFormValue.value.claude_max_turns
      }
    }

    if (aiFormValue.value.anthropic_api_key_input.trim()) {
      update.runtime.anthropic_api_key = aiFormValue.value.anthropic_api_key_input.trim()
    }

    await updateConfig(update)
    lastLoadedAi.value = {
      ...aiFormValue.value,
      anthropic_api_key_input: '',
      anthropic_api_key_configured: true
    }
    aiFormValue.value.anthropic_api_key_input = ''
    aiFormValue.value.anthropic_api_key_configured = true
    message.success(t('config.saved'))
  } catch (error: any) {
    message.error(error?.response?.data?.detail || t('config.saveError'))
  } finally {
    aiSaving.value = false
  }
}

async function handleClearApiKey() {
  workerSaving.value = true
  try {
    await resetConfigKey('anthropic_api_key')
    aiFormValue.value.anthropic_api_key_configured = false
    lastLoadedAi.value.anthropic_api_key_configured = false
    message.success(t('config.cleared'))
  } catch (error: any) {
    message.error(error?.response?.data?.detail || t('config.clearError'))
  } finally {
    workerSaving.value = false
  }
}

function resetAi() {
  aiFormValue.value = { ...lastLoadedAi.value }
  aiFormValue.value.anthropic_api_key_input = ''
}

function addMount() {
  workerFormValue.value.mounts.push({
    host_path: '',
    container_path: '',
    mode: 'ro'
  })
}

function createEmptyWorkerFormValue(): WorkerFormValue {
  return {
    mounts: [],
    maven_cache_host_path: '',
    maven_settings_host_path: ''
  }
}

function removeMount(index: number) {
  workerFormValue.value.mounts.splice(index, 1)
}

async function handleSaveWorker() {
  workerSaving.value = true
  try {
    await updateConfig({
      runtime: {
        worker_volume_mounts: serializeMounts(workerFormValue.value.mounts),
        maven_cache_host_path: workerFormValue.value.maven_cache_host_path.trim(),
        maven_settings_host_path: workerFormValue.value.maven_settings_host_path.trim()
      }
    })
    // Safely clone the form value to preserve current state
    try {
      lastLoadedWorker.value = JSON.parse(JSON.stringify(workerFormValue.value))
    } catch {
      // Cloning failed, but save succeeded - use empty object as fallback
      lastLoadedWorker.value = createEmptyWorkerFormValue()
    }
    message.success(t('config.saved'))
  } catch (error: any) {
    message.error(error?.response?.data?.detail || t('config.saveError'))
  } finally {
    workerSaving.value = false
  }
}

function resetWorker() {
  // Safely clone last loaded worker config with error boundary
  if (!lastLoadedWorker.value) {
    workerFormValue.value = createEmptyWorkerFormValue()
    return
  }
  try {
    workerFormValue.value = JSON.parse(JSON.stringify(lastLoadedWorker.value))
  } catch {
    // If cloning fails, reset to empty mounts
    workerFormValue.value = createEmptyWorkerFormValue()
  }
}

onMounted(() => {
  fetchConfig()
})

watch(() => props.reloadKey, () => {
  fetchConfig()
})
</script>

<style scoped>
.config-maven-section {
  margin-top: 20px;
}
</style>
