<template>
  <n-spin :show="loading">
    <div class="config-layout__main">
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

          <div class="config-form__section config-scripts-section">
            <div class="config-form__section-title">{{ t('config.workerCustomScripts') }}</div>
            <n-grid :cols="isMobile ? 1 : 2" :x-gap="16" :y-gap="8">
              <n-gi>
                <n-form-item :label="t('config.workerPreScript')">
                  <n-input
                    v-model:value="workerFormValue.worker_pre_script"
                    type="textarea"
                    :placeholder="t('config.workerPreScriptPlaceholder')"
                    :autosize="{ minRows: 5, maxRows: 12 }"
                    class="config-form__input config-form__textarea"
                  />
                  <template #feedback>
                    {{ t('config.workerPreScriptHint') }}
                  </template>
                </n-form-item>
              </n-gi>
              <n-gi>
                <n-form-item :label="t('config.workerPostScript')">
                  <n-input
                    v-model:value="workerFormValue.worker_post_script"
                    type="textarea"
                    :placeholder="t('config.workerPostScriptPlaceholder')"
                    :autosize="{ minRows: 5, maxRows: 12 }"
                    class="config-form__input config-form__textarea"
                  />
                  <template #feedback>
                    {{ t('config.workerPostScriptHint') }}
                  </template>
                </n-form-item>
              </n-gi>
            </n-grid>
          </div>

          <div class="config-form__section config-run-instructions-section">
            <div class="config-form__section-title">{{ t('config.runInstructions') }}</div>
            <n-form-item :label="t('config.defaultExecuteRunInstruction')">
              <RunInstructionTemplateEditor
                v-model="workerFormValue.default_execute_run_instruction_template"
                :available-placeholders="builtIns?.execute.available_placeholders ?? []"
                :known-placeholders="knownPromptPlaceholders"
                @restore-default="restoreBuiltIn('execute')"
              />
            </n-form-item>
            <n-form-item :label="t('config.defaultPlanRunInstruction')">
              <RunInstructionTemplateEditor
                v-model="workerFormValue.default_plan_run_instruction_template"
                :available-placeholders="builtIns?.plan.available_placeholders ?? []"
                :known-placeholders="knownPromptPlaceholders"
                @restore-default="restoreBuiltIn('plan')"
              />
            </n-form-item>
            <n-form-item :label="t('config.ciAutoRepairRunInstruction')">
              <RunInstructionTemplateEditor
                v-model="workerFormValue.ci_auto_repair_run_instruction_template"
                :available-placeholders="builtIns?.ci_auto_repair.available_placeholders ?? []"
                :known-placeholders="knownPromptPlaceholders"
                :warn-when-user-prompt-missing="false"
                @restore-default="restoreBuiltIn('ci_auto_repair')"
              />
            </n-form-item>
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
  NSelect,
  NSpace,
  NSpin,
  NTag,
  useMessage
} from 'naive-ui'
import { useI18n } from 'vue-i18n'
import {
  getConfig,
  getRunInstructionTemplateBuiltIns,
  updateConfig,
  type RunInstructionTemplateBuiltIns,
  type RuntimeConfig,
  type WorkerEnvironmentVariable,
  type WorkerEnvironmentVariableUpdate
} from '../../api'
import RunInstructionTemplateEditor from '../RunInstructionTemplateEditor.vue'

type MountItem = {
  host_path: string
  container_path: string
  mode: 'ro' | 'rw'
}

type WorkerFormValue = {
  mounts: MountItem[]
  environment_variables: EnvironmentVariableFormItem[]
  worker_pre_script: string
  worker_post_script: string
  maven_cache_host_path: string
  maven_settings_host_path: string
  default_execute_run_instruction_template: string
  default_plan_run_instruction_template: string
  ci_auto_repair_run_instruction_template: string
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
const builtIns = ref<RunInstructionTemplateBuiltIns | null>(null)
const knownPromptPlaceholders = computed(() => [
  ...new Set(builtIns.value?.execute.known_placeholders ?? [
    ...(builtIns.value?.execute.available_placeholders ?? []),
    ...(builtIns.value?.plan.available_placeholders ?? []),
    ...(builtIns.value?.ci_auto_repair.available_placeholders ?? [])
  ])
])

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
  worker_pre_script: '',
  worker_post_script: '',
  maven_cache_host_path: '',
  maven_settings_host_path: '',
  default_execute_run_instruction_template: '',
  default_plan_run_instruction_template: '',
  ci_auto_repair_run_instruction_template: ''
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
    worker_pre_script: runtime?.worker_pre_script || '',
    worker_post_script: runtime?.worker_post_script || '',
    maven_cache_host_path: runtime?.maven_cache_host_path || '',
    maven_settings_host_path: runtime?.maven_settings_host_path || '',
    default_execute_run_instruction_template:
      runtime?.default_execute_run_instruction_template || '',
    default_plan_run_instruction_template:
      runtime?.default_plan_run_instruction_template || '',
    ci_auto_repair_run_instruction_template:
      runtime?.ci_auto_repair_run_instruction_template || ''
  }
}

function cloneWorkerFormValue(value: WorkerFormValue): WorkerFormValue {
  return {
    mounts: value.mounts.map((mount) => ({ ...mount })),
    environment_variables: value.environment_variables.map((environmentVariable) => ({
      ...environmentVariable
    })),
    worker_pre_script: value.worker_pre_script,
    worker_post_script: value.worker_post_script,
    maven_cache_host_path: value.maven_cache_host_path,
    maven_settings_host_path: value.maven_settings_host_path,
    default_execute_run_instruction_template: value.default_execute_run_instruction_template,
    default_plan_run_instruction_template: value.default_plan_run_instruction_template,
    ci_auto_repair_run_instruction_template: value.ci_auto_repair_run_instruction_template
  }
}

async function fetchConfig() {
  loading.value = true
  try {
    const [configResult, builtInsResult] = await Promise.allSettled([
      getConfig(),
      getRunInstructionTemplateBuiltIns()
    ])
    if (configResult.status === 'rejected') throw configResult.reason
    const config = configResult.value
    if (builtInsResult.status === 'fulfilled') {
      builtIns.value = builtInsResult.value
    }
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
    worker_pre_script: '',
    worker_post_script: '',
    maven_cache_host_path: '',
    maven_settings_host_path: '',
    default_execute_run_instruction_template: '',
    default_plan_run_instruction_template: '',
    ci_auto_repair_run_instruction_template: ''
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
        worker_pre_script: workerFormValue.value.worker_pre_script,
        worker_post_script: workerFormValue.value.worker_post_script,
        maven_cache_host_path: workerFormValue.value.maven_cache_host_path.trim(),
        maven_settings_host_path: workerFormValue.value.maven_settings_host_path.trim(),
        default_execute_run_instruction_template: workerFormValue.value.default_execute_run_instruction_template,
        default_plan_run_instruction_template: workerFormValue.value.default_plan_run_instruction_template,
        ci_auto_repair_run_instruction_template: workerFormValue.value.ci_auto_repair_run_instruction_template
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

function restoreBuiltIn(kind: keyof RunInstructionTemplateBuiltIns) {
  if (!builtIns.value) return
  if (kind === 'execute') {
    workerFormValue.value.default_execute_run_instruction_template = builtIns.value.execute.content
  } else if (kind === 'plan') {
    workerFormValue.value.default_plan_run_instruction_template = builtIns.value.plan.content
  } else {
    workerFormValue.value.ci_auto_repair_run_instruction_template = builtIns.value.ci_auto_repair.content
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

.config-environment-section {
  margin-top: 20px;
}

.config-scripts-section {
  margin-top: 20px;
}

.config-run-instructions-section { margin-top: 20px; }

.config-secret-feedback {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
</style>
