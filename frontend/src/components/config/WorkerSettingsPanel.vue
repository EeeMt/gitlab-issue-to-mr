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
  useMessage
} from 'naive-ui'
import { useI18n } from 'vue-i18n'
import { getConfig, updateConfig } from '../../api'

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
const workerSaving = ref(false)

const mountModeOptions = [
  { label: 'Read-only (ro)', value: 'ro' },
  { label: 'Read-write (rw)', value: 'rw' }
]

const workerFormValue = ref<WorkerFormValue>({
  mounts: [],
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

async function fetchConfig() {
  loading.value = true
  try {
    const config = await getConfig()
    workerFormValue.value = {
      mounts: parseMounts(config.runtime.worker_volume_mounts),
      maven_cache_host_path: config.runtime.maven_cache_host_path || '',
      maven_settings_host_path: config.runtime.maven_settings_host_path || ''
    }
    lastLoadedWorker.value = JSON.parse(JSON.stringify(workerFormValue.value))
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
