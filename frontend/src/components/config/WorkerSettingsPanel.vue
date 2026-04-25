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
        <n-alert type="info" :show-icon="true">
          {{ t('config.providers.movedNotice') }}
        </n-alert>
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

          <div class="config-form__section config-environment-section">
            <div class="config-form__section-header">
              <div class="config-form__section-title">{{ t('config.environmentVariables') }}</div>
              <n-button size="small" @click="addEnvironmentVariable">
                {{ t('config.addEnvironmentVariable') }}
              </n-button>
            </div>
            <div v-if="workerFormValue.environment_variables.length === 0" class="config-empty">
              {{ t('config.noEnvironmentVariables') }}
            </div>
            <div v-else class="config-mounts-list">
              <div
                v-for="(environmentVariable, index) in workerFormValue.environment_variables"
                :key="environmentVariable.id ?? `env-${index}`"
                class="config-mount-item"
              >
                <n-grid :cols="isMobile ? 1 : 3" :x-gap="12" :y-gap="8">
                  <n-gi>
                    <n-form-item :label="t('config.environmentVariableKey')" size="small">
                      <n-input
                        v-model:value="environmentVariable.key"
                        :placeholder="t('config.environmentVariableKeyPlaceholder')"
                        class="config-form__input"
                      />
                    </n-form-item>
                  </n-gi>
                  <n-gi>
                    <n-form-item :label="t('config.environmentVariableType')" size="small">
                      <n-select
                        :value="environmentVariable.is_secret ? 'secret' : 'plain_text'"
                        :options="environmentVariableTypeOptions"
                        @update:value="
                          (value) => {
                            environmentVariable.is_secret = value === 'secret'
                          }
                        "
                        class="config-form__input"
                      />
                    </n-form-item>
                  </n-gi>
                  <n-gi>
                    <n-form-item :label="t('config.environmentVariableValue')" size="small">
                      <n-input
                        v-model:value="environmentVariable.value"
                        :type="environmentVariable.is_secret ? 'password' : 'text'"
                        :placeholder="
                          environmentVariable.is_secret && environmentVariable.value_configured
                            ? t('config.configuredEnterNew')
                            : t('config.environmentVariableValuePlaceholder')
                        "
                        class="config-form__input"
                      />
                      <template v-if="environmentVariable.is_secret" #feedback>
                        <div class="config-secret-feedback">
                          <n-tag
                            :type="environmentVariable.value_configured ? 'success' : 'warning'"
                            round
                          >
                            {{
                              environmentVariable.value_configured
                                ? t('config.configured')
                                : t('config.missing')
                            }}
                          </n-tag>
                          <span>{{ t('config.environmentVariableSecretHint') }}</span>
                        </div>
                      </template>
                    </n-form-item>
                  </n-gi>
                </n-grid>
                <n-button
                  size="tiny"
                  type="error"
                  quaternary
                  @click="removeEnvironmentVariable(index)"
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
  NAlert,
  NButton,
  NCard,
  NForm,
  NFormItem,
  NGi,
  NGrid,
  NInput,
  NSelect,
  NSpace,
  NSpin,
  NTag,
  useMessage
} from 'naive-ui'
import { useI18n } from 'vue-i18n'
import {
  getConfig,
  updateConfig,
  type RuntimeConfig,
  type WorkerEnvironmentVariable,
  type WorkerEnvironmentVariableUpdate
} from '../../api'

type MountItem = {
  host_path: string
  container_path: string
  mode: 'ro' | 'rw'
}

type WorkerFormValue = {
  mounts: MountItem[]
  environment_variables: EnvironmentVariableFormItem[]
  maven_cache_host_path: string
  maven_settings_host_path: string
}

type EnvironmentVariableFormItem = {
  id?: number
  key: string
  value: string
  is_secret: boolean
  value_configured: boolean
}

const props = defineProps<{
  isMobile: boolean
  reloadKey?: number
}>()

const message = useMessage()
const { t } = useI18n()

const loading = ref(false)
const workerSaving = ref(false)

const mountModeOptions = [
  { label: 'Read-only (ro)', value: 'ro' },
  { label: 'Read-write (rw)', value: 'rw' }
]

const environmentVariableTypeOptions = [
  { label: t('config.environmentVariablePlainText'), value: 'plain_text' },
  { label: t('config.environmentVariableSecret'), value: 'secret' }
]

const workerFormValue = ref<WorkerFormValue>({
  mounts: [],
  environment_variables: [],
  maven_cache_host_path: '',
  maven_settings_host_path: ''
})

const lastLoadedWorker = ref<WorkerFormValue>(createEmptyWorkerFormValue())

const isWorkerDirty = computed(() =>
  JSON.stringify(workerFormValue.value) !== JSON.stringify(lastLoadedWorker.value)
)

const isWorkerBusy = computed(() => loading.value || workerSaving.value)

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

function parseEnvironmentVariables(
  environmentVariables: WorkerEnvironmentVariable[] | undefined
): EnvironmentVariableFormItem[] {
  if (!Array.isArray(environmentVariables)) return []

  return environmentVariables.map((environmentVariable) => ({
    id: environmentVariable.id,
    key: environmentVariable.key || '',
    value:
      environmentVariable.is_secret && environmentVariable.value_configured
        ? ''
        : (environmentVariable.value ?? ''),
    is_secret: Boolean(environmentVariable.is_secret),
    value_configured: Boolean(environmentVariable.value_configured || environmentVariable.value)
  }))
}

function serializeEnvironmentVariables(
  environmentVariables: EnvironmentVariableFormItem[]
): WorkerEnvironmentVariableUpdate[] {
  return environmentVariables
    .map((environmentVariable) => ({
      id: environmentVariable.id,
      key: environmentVariable.key.trim(),
      value: environmentVariable.value,
      is_secret: environmentVariable.is_secret
    }))
    .filter((environmentVariable) => environmentVariable.key)
}

function mapRuntimeConfigToWorkerFormValue(runtime?: Partial<RuntimeConfig>): WorkerFormValue {
  return {
    mounts: parseMounts(runtime?.worker_volume_mounts ?? ''),
    environment_variables: parseEnvironmentVariables(runtime?.worker_environment_variables),
    maven_cache_host_path: runtime?.maven_cache_host_path || '',
    maven_settings_host_path: runtime?.maven_settings_host_path || ''
  }
}

function cloneWorkerFormValue(value: WorkerFormValue): WorkerFormValue {
  return {
    mounts: value.mounts.map((mount) => ({ ...mount })),
    environment_variables: value.environment_variables.map((environmentVariable) => ({
      ...environmentVariable
    })),
    maven_cache_host_path: value.maven_cache_host_path,
    maven_settings_host_path: value.maven_settings_host_path
  }
}

async function fetchConfig() {
  loading.value = true
  try {
    const config = await getConfig()
    workerFormValue.value = mapRuntimeConfigToWorkerFormValue(config.runtime)
    lastLoadedWorker.value = cloneWorkerFormValue(workerFormValue.value)
  } catch {
    message.error(t('config.loadError'))
  } finally {
    loading.value = false
  }
}

function addMount() {
  workerFormValue.value.mounts.push({
    host_path: '',
    container_path: '',
    mode: 'ro'
  })
}

function addEnvironmentVariable() {
  workerFormValue.value.environment_variables.push({
    key: '',
    value: '',
    is_secret: false,
    value_configured: false
  })
}

function createEmptyWorkerFormValue(): WorkerFormValue {
  return {
    mounts: [],
    environment_variables: [],
    maven_cache_host_path: '',
    maven_settings_host_path: ''
  }
}

function removeMount(index: number) {
  workerFormValue.value.mounts.splice(index, 1)
}

function removeEnvironmentVariable(index: number) {
  workerFormValue.value.environment_variables.splice(index, 1)
}

async function handleSaveWorker() {
  workerSaving.value = true
  try {
    const savedConfig = await updateConfig({
      runtime: {
        worker_volume_mounts: serializeMounts(workerFormValue.value.mounts),
        worker_environment_variables: serializeEnvironmentVariables(
          workerFormValue.value.environment_variables
        ),
        maven_cache_host_path: workerFormValue.value.maven_cache_host_path.trim(),
        maven_settings_host_path: workerFormValue.value.maven_settings_host_path.trim()
      }
    })
    workerFormValue.value = mapRuntimeConfigToWorkerFormValue(savedConfig.runtime)
    lastLoadedWorker.value = cloneWorkerFormValue(workerFormValue.value)
    message.success(t('config.saved'))
  } catch (error: any) {
    message.error(error?.response?.data?.detail || t('config.saveError'))
  } finally {
    workerSaving.value = false
  }
}

function resetWorker() {
  workerFormValue.value = cloneWorkerFormValue(lastLoadedWorker.value)
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

.config-environment-section {
  margin-top: 20px;
}

.config-secret-feedback {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
</style>
