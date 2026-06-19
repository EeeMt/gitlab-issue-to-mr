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
          <div class="config-form__section config-collection-section">
            <div class="config-form__section-header">
              <div class="config-collection-heading">
                <div class="config-form__section-title">{{ t('config.volumeMounts') }}</div>
                <n-tag size="small" round :bordered="false">
                  {{ workerFormValue.mounts.length }}
                </n-tag>
              </div>
              <n-button size="small" secondary @click="addMount">
                {{ t('config.addVolumeMount') }}
              </n-button>
            </div>
            <div v-if="workerFormValue.mounts.length === 0" class="config-empty config-compact-empty">
              {{ t('config.noVolumeMounts') }}
            </div>
            <div v-else class="config-compact-table config-compact-table--mounts">
              <div class="config-compact-table__header" aria-hidden="true">
                <span>{{ t('config.hostPath') }}</span>
                <span>{{ t('config.containerPath') }}</span>
                <span>{{ t('config.mountMode') }}</span>
                <span></span>
              </div>
              <div
                v-for="(mount, index) in workerFormValue.mounts"
                :key="index"
                class="config-compact-row config-compact-row--mount"
              >
                <label class="config-compact-field">
                  <span class="config-compact-field__label">{{ t('config.hostPath') }}</span>
                  <n-input
                    v-model:value="mount.host_path"
                    size="small"
                    :placeholder="t('config.hostPathPlaceholder')"
                    class="config-form__input"
                  />
                </label>
                <label class="config-compact-field">
                  <span class="config-compact-field__label">{{ t('config.containerPath') }}</span>
                  <n-input
                    v-model:value="mount.container_path"
                    size="small"
                    :placeholder="t('config.containerPathPlaceholder')"
                    class="config-form__input"
                  />
                </label>
                <label class="config-compact-field">
                  <span class="config-compact-field__label">{{ t('config.mountMode') }}</span>
                  <n-select
                    v-model:value="mount.mode"
                    size="small"
                    :options="mountModeOptions"
                    class="config-form__input"
                  />
                </label>
                <n-button
                  size="small"
                  type="error"
                  quaternary
                  @click="removeMount(index)"
                  class="config-compact-row__remove"
                >
                  {{ t('config.remove') }}
                </n-button>
              </div>
            </div>
          </div>

          <div class="config-form__section config-collection-section">
            <div class="config-form__section-header">
              <div class="config-collection-heading">
                <div class="config-form__section-title">{{ t('config.environmentVariables') }}</div>
                <n-tag size="small" round :bordered="false">
                  {{ workerFormValue.environment_variables.length }}
                </n-tag>
                <span class="config-collection-heading__hint">
                  {{ t('config.environmentVariableSecretHint') }}
                </span>
              </div>
              <n-button size="small" secondary @click="addEnvironmentVariable">
                {{ t('config.addEnvironmentVariable') }}
              </n-button>
            </div>
            <div
              v-if="workerFormValue.environment_variables.length === 0"
              class="config-empty config-compact-empty"
            >
              {{ t('config.noEnvironmentVariables') }}
            </div>
            <div v-else class="config-compact-table config-compact-table--environment">
              <div class="config-compact-table__header" aria-hidden="true">
                <span>{{ t('config.environmentVariableKey') }}</span>
                <span>{{ t('config.environmentVariableType') }}</span>
                <span>{{ t('config.environmentVariableValue') }}</span>
                <span></span>
              </div>
              <div
                v-for="(environmentVariable, index) in workerFormValue.environment_variables"
                :key="environmentVariable.id ?? `env-${index}`"
                class="config-compact-row config-compact-row--environment"
              >
                <label class="config-compact-field">
                  <span class="config-compact-field__label">
                    {{ t('config.environmentVariableKey') }}
                  </span>
                  <n-input
                    v-model:value="environmentVariable.key"
                    size="small"
                    :placeholder="t('config.environmentVariableKeyPlaceholder')"
                    class="config-form__input"
                  />
                </label>
                <label class="config-compact-field">
                  <span class="config-compact-field__label">
                    {{ t('config.environmentVariableType') }}
                  </span>
                  <n-select
                    :value="environmentVariable.is_secret ? 'secret' : 'plain_text'"
                    size="small"
                    :options="environmentVariableTypeOptions"
                    @update:value="
                      (value) => {
                        environmentVariable.is_secret = value === 'secret'
                      }
                    "
                    class="config-form__input"
                  />
                </label>
                <label class="config-compact-field config-compact-field--value">
                  <span class="config-compact-field__label">
                    {{ t('config.environmentVariableValue') }}
                  </span>
                  <div class="config-compact-value">
                    <n-input
                      v-model:value="environmentVariable.value"
                      size="small"
                      :type="environmentVariable.is_secret ? 'password' : 'text'"
                      :placeholder="
                        environmentVariable.is_secret && environmentVariable.value_configured
                          ? t('config.configuredEnterNew')
                          : t('config.environmentVariableValuePlaceholder')
                      "
                      class="config-form__input"
                    />
                    <n-tag
                      v-if="environmentVariable.is_secret"
                      size="small"
                      :type="environmentVariable.value_configured ? 'success' : 'warning'"
                      round
                      :bordered="false"
                    >
                      {{
                        environmentVariable.value_configured
                          ? t('config.configured')
                          : t('config.missing')
                      }}
                    </n-tag>
                  </div>
                </label>
                <n-button
                  size="small"
                  type="error"
                  quaternary
                  @click="removeEnvironmentVariable(index)"
                  class="config-compact-row__remove"
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
  workerFormValue.value.mounts.unshift({
    host_path: '',
    container_path: '',
    mode: 'ro'
  })
}

function addEnvironmentVariable() {
  workerFormValue.value.environment_variables.unshift({
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
.config-collection-section {
  gap: 8px;
}

.config-collection-heading {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.config-collection-heading__hint {
  font-size: 12px;
  color: rgba(15, 23, 42, 0.48);
}

.config-compact-empty {
  padding: 12px 16px;
  border-radius: 10px;
}

.config-compact-table {
  overflow: hidden;
  border: 1px solid rgba(15, 23, 42, 0.08);
  border-radius: 10px;
  background: #fff;
}

.config-compact-table__header,
.config-compact-row {
  display: grid;
  align-items: center;
  column-gap: 10px;
}

.config-compact-table--mounts .config-compact-table__header,
.config-compact-row--mount {
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr) 158px 52px;
}

.config-compact-table--environment .config-compact-table__header,
.config-compact-row--environment {
  grid-template-columns: minmax(140px, 0.8fr) 120px minmax(220px, 1.2fr) 52px;
}

.config-compact-table__header {
  padding: 6px 10px;
  font-size: 11px;
  font-weight: 600;
  line-height: 1.3;
  color: rgba(15, 23, 42, 0.48);
  background: rgba(15, 23, 42, 0.025);
}

.config-compact-row {
  min-height: 48px;
  padding: 7px 10px;
  border-top: 1px solid rgba(15, 23, 42, 0.07);
}

.config-compact-field {
  display: block;
  min-width: 0;
}

.config-compact-field__label {
  display: none;
}

.config-compact-value {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.config-compact-value .n-tag {
  flex: 0 0 auto;
}

.config-compact-row__remove {
  justify-self: end;
}

@media (max-width: 767px) {
  .config-collection-heading {
    flex-wrap: wrap;
  }

  .config-collection-heading__hint {
    flex-basis: 100%;
  }

  .config-compact-table__header {
    display: none;
  }

  .config-compact-row--mount,
  .config-compact-row--environment {
    grid-template-columns: minmax(0, 1fr);
    gap: 8px;
    padding: 10px;
  }

  .config-compact-table__header + .config-compact-row {
    border-top: 0;
  }

  .config-compact-field__label {
    display: block;
    margin-bottom: 4px;
    font-size: 11px;
    font-weight: 600;
    color: rgba(15, 23, 42, 0.52);
  }

  .config-compact-row__remove {
    justify-self: start;
  }
}
</style>
