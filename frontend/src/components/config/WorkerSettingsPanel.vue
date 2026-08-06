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
              <div class="config-form__section-title">{{ t('config.workerWorkspaceCleanup') }}</div>
              <n-button
                size="small"
                type="primary"
                :loading="workspaceSaving"
                :disabled="isWorkerBusy || !isWorkspaceDirty"
                @click="handleSaveWorkspace"
              >
                {{ t('config.saveWorkspaceSettings') }}
              </n-button>
            </div>
            <n-grid :cols="isMobile ? 1 : 2" :x-gap="16" :y-gap="8">
              <n-gi>
                <n-form-item
                  :label="t('config.workerWorkspaceHostPath')"
                >
                  <n-input
                    v-model:value="workerFormValue.worker_workspace_host_path"
                    class="config-form__input"
                    placeholder="/opt/codify-workspaces"
                    disabled
                  />
                  <template #feedback>
                    {{ t('config.workerWorkspaceHostPathDeploymentHint') }}
                  </template>
                </n-form-item>
              </n-gi>
              <n-gi>
                <n-form-item :label="t('config.workerWorkspaceRetentionDays')">
                  <n-input-number
                    v-model:value="workerFormValue.worker_workspace_retention_days"
                    :min="0"
                    :max="365"
                    class="config-form__input"
                  />
                  <template #feedback>
                    {{ t('config.workerWorkspaceRetentionDaysHint') }}
                  </template>
                </n-form-item>
              </n-gi>
            </n-grid>
          </div>

          <div class="config-form__section">
            <div class="config-form__section-header">
              <div class="config-form__section-title">{{ t('config.taskArtifacts') }}</div>
              <n-button
                size="small"
                type="primary"
                :loading="artifactSaving"
                :disabled="isWorkerBusy || !isArtifactDirty || !artifactLimitsValid"
                @click="handleSaveArtifacts"
              >
                {{ t('config.saveArtifactSettings') }}
              </n-button>
            </div>
            <n-grid :cols="isMobile ? 1 : 2" :x-gap="16" :y-gap="8">
              <n-gi>
                <n-form-item :label="t('config.artifactMaxTotalMiB')">
                  <n-input-number
                    v-model:value="artifactFormValue.maxTotalMiB"
                    :min="1"
                    :max="512"
                    class="config-form__input"
                  />
                </n-form-item>
              </n-gi>
              <n-gi>
                <n-form-item
                  :label="t('config.artifactMaxFileMiB')"
                  :validation-status="artifactLimitsValid ? undefined : 'error'"
                  :feedback="artifactLimitsValid ? undefined : t('config.artifactFileLimitError')"
                >
                  <n-input-number
                    v-model:value="artifactFormValue.maxFileMiB"
                    :min="1"
                    :max="artifactFormValue.maxTotalMiB"
                    class="config-form__input"
                  />
                </n-form-item>
              </n-gi>
              <n-gi>
                <n-form-item :label="t('config.artifactMaxEntries')">
                  <n-input-number
                    v-model:value="artifactFormValue.maxEntries"
                    :min="1"
                    :max="100000"
                    class="config-form__input"
                  />
                </n-form-item>
              </n-gi>
              <n-gi>
                <n-form-item :label="t('config.runtimeArchiveRetentionDays')">
                  <n-input-number
                    v-model:value="artifactFormValue.retentionDays"
                    :min="1"
                    :max="3650"
                    class="config-form__input"
                  />
                  <template #feedback>
                    {{ t('config.runtimeArchiveRetentionDaysHint') }}
                  </template>
                </n-form-item>
              </n-gi>
            </n-grid>
          </div>

          <div class="worker-profile-layout">
            <aside class="worker-profile-list">
              <div class="worker-profile-list__header">
                <span>{{ t('config.workerProfiles') }}</span>
                <n-button size="small" secondary @click="handleCreateProfile">
                  {{ t('config.createWorkerProfile') }}
                </n-button>
              </div>
              <button
                v-for="profile in workerProfiles"
                :key="profile.id"
                type="button"
                class="worker-profile-list__item"
                :class="{ 'worker-profile-list__item--active': profile.id === selectedProfileId }"
                @click="selectProfile(profile.id)"
              >
                <span class="worker-profile-list__name">{{ profile.name }}</span>
                <span class="worker-profile-list__tags">
                  <n-tag v-if="profile.is_default" size="small" type="success" :bordered="false">
                    {{ t('config.defaultWorkerProfile') }}
                  </n-tag>
                  <n-tag v-if="!profile.enabled" size="small" type="warning" :bordered="false">
                    {{ t('config.disabled') }}
                  </n-tag>
                </span>
                <small>{{ profile.image }}</small>
              </button>
            </aside>
            <section class="worker-profile-editor">
          <div class="config-form__section">
            <div class="config-form__section-header">
              <div class="config-form__section-title">{{ t('config.workerProfiles') }}</div>
              <n-space :size="8" wrap>
                <n-button
                  size="small"
                  secondary
                  :disabled="selectedProfileId === null || isWorkerBusy"
                  @click="handleDuplicateProfile"
                >
                  {{ t('config.duplicateWorkerProfile') }}
                </n-button>
                <n-button
                  size="small"
                  secondary
                  :disabled="
                    selectedProfileId === null ||
                    workerFormValue.is_default ||
                    !workerFormValue.enabled ||
                    isWorkerBusy
                  "
                  @click="handleSetDefaultProfile"
                >
                  {{ t('config.setDefaultWorkerProfile') }}
                </n-button>
                <n-button
                  v-if="workerFormValue.enabled"
                  size="small"
                  secondary
                  :disabled="
                    selectedProfileId === null ||
                    workerFormValue.is_default ||
                    !workerFormValue.enabled ||
                    isWorkerBusy
                  "
                  @click="handleDisableProfile"
                >
                  {{ t('config.disableWorkerProfile') }}
                </n-button>
                <n-button
                  v-else
                  size="small"
                  type="primary"
                  secondary
                  :disabled="selectedProfileId === null || isWorkerBusy"
                  @click="handleEnableProfile"
                >
                  {{ t('config.enableWorkerProfile') }}
                </n-button>
                <n-popconfirm
                  :positive-text="t('common.confirm')"
                  :negative-text="t('common.cancel')"
                  @positive-click="handleDeleteProfile"
                >
                  <template #trigger>
                    <n-button
                      size="small"
                      type="error"
                      secondary
                      :disabled="
                        selectedProfileId === null ||
                        workerFormValue.is_default ||
                        workerFormValue.enabled ||
                        isWorkerBusy
                      "
                    >
                      {{ t('config.deleteWorkerProfile') }}
                    </n-button>
                  </template>
                  {{
                    t('config.deleteWorkerProfileConfirm', {
                      name: workerFormValue.name
                    })
                  }}
                </n-popconfirm>
              </n-space>
            </div>
            <n-grid :cols="isMobile ? 1 : 2" :x-gap="16" :y-gap="8">
              <n-gi>
                <n-form-item :label="t('config.workerProfileName')">
                  <n-input v-model:value="workerFormValue.name" class="config-form__input" />
                </n-form-item>
              </n-gi>
              <n-gi>
                <n-form-item :label="t('config.workerProfileImage')">
                  <n-input v-model:value="workerFormValue.image" class="config-form__input" />
                </n-form-item>
              </n-gi>
              <n-gi>
                <n-form-item :label="t('config.workerRuntimeMode')">
                  <n-select
                    v-model:value="workerFormValue.runtime_mode"
                    :options="workerRuntimeModeOptions"
                    class="config-form__input"
                  />
                  <template v-if="workerFormValue.runtime_mode === 'baked_image'" #feedback>
                    {{ t('config.workerRuntimeModeBakedImageHint') }}
                  </template>
                </n-form-item>
              </n-gi>
              <n-gi>
                <n-form-item :label="t('config.codegraph')">
                  <n-switch v-model:value="workerFormValue.codegraph_enabled" />
                  <template #feedback>
                    {{ t('config.codegraphHint') }}
                  </template>
                </n-form-item>
                <n-form-item :label="t('config.harnesses')" path="enabled_harnesses">
                  <n-select
                    v-model:value="workerFormValue.enabled_harnesses"
                    multiple
                    :options="harnessSelectOptions"
                    :disabled="workerFormValue.runtime_mode !== 'mounted_kit'"
                  />
                  <template #feedback>
                    {{ t('config.harnessesHint') }}
                  </template>
                </n-form-item>
                <n-form-item :label="t('config.defaultHarness')" path="default_harness_key">
                  <n-select
                    v-model:value="workerFormValue.default_harness_key"
                    :options="harnessSelectOptions"
                    :disabled="workerFormValue.runtime_mode !== 'mounted_kit'"
                  />
                  <template #feedback>
                    {{ t('config.defaultHarnessHint') }}
                  </template>
                </n-form-item>
              </n-gi>
            </n-grid>
            <n-grid
              v-if="workerFormValue.runtime_mode === 'mounted_kit'"
              :cols="isMobile ? 1 : 2"
              :x-gap="16"
              :y-gap="8"
            >
              <n-gi>
                <n-form-item :label="t('config.workerKitVersion')">
                  <n-input
                    v-model:value="workerFormValue.worker_kit_version"
                    class="config-form__input"
                    placeholder="0.3.6"
                  />
                </n-form-item>
              </n-gi>
              <n-gi>
                <n-form-item :label="t('config.workerKitPath')">
                  <n-input
                    v-model:value="workerFormValue.worker_kit_path"
                    class="config-form__input"
                    placeholder="/opt/codify/worker-kits/0.3.6-linux-amd64"
                  />
                  <template #feedback>
                    {{ t('config.workerKitPathHint') }}
                  </template>
                </n-form-item>
              </n-gi>
            </n-grid>
          </div>

          <div class="config-form__section">
            <div class="config-form__section-title">{{ t('config.defaultSkills') }}</div>
            <n-form-item>
              <n-select
                v-model:value="workerFormValue.default_skill_ids"
                multiple
                clearable
                filterable
                :disabled="workerFormValue.runtime_mode !== 'mounted_kit'"
                :options="skillOptions"
                :placeholder="t('config.selectDefaultSkills')"
                class="config-form__input"
              />
              <template #feedback>
                {{ t('config.defaultSkillsHint') }}
              </template>
            </n-form-item>
          </div>

          <div class="config-form__section docker-target-section">
            <div class="config-form__section-header">
              <div class="config-form__section-title">{{ t('config.dockerTarget') }}</div>
              <n-button
                size="small"
                secondary
                :loading="dockerTesting"
                :disabled="isWorkerBusy"
                @click="handleTestDockerConnection"
              >
                {{ t('config.testDockerConnection') }}
              </n-button>
            </div>
            <n-form-item :label="t('config.useSystemDockerTarget')">
              <n-switch v-model:value="workerFormValue.use_system_docker" />
            </n-form-item>
            <n-grid
              v-if="!workerFormValue.use_system_docker"
              :cols="isMobile ? 1 : 2"
              :x-gap="16"
              :y-gap="8"
            >
              <n-gi :span="isMobile ? 1 : 2">
                <n-form-item :label="t('config.dockerHost')">
                  <n-input
                    v-model:value="workerFormValue.docker_host"
                    class="config-form__input"
                    placeholder="tcp://docker-host:2376"
                  />
                </n-form-item>
              </n-gi>
              <n-gi>
                <n-form-item :label="t('config.dockerTlsCa')">
                  <n-input
                    v-model:value="workerFormValue.docker_tls_ca"
                    class="config-form__input"
                    placeholder="/etc/codify/docker/ca.pem"
                  />
                </n-form-item>
              </n-gi>
              <n-gi>
                <n-form-item :label="t('config.dockerTlsCert')">
                  <n-input
                    v-model:value="workerFormValue.docker_tls_cert"
                    class="config-form__input"
                    placeholder="/etc/codify/docker/cert.pem"
                  />
                </n-form-item>
              </n-gi>
              <n-gi>
                <n-form-item :label="t('config.dockerTlsKey')">
                  <n-input
                    v-model:value="workerFormValue.docker_tls_key"
                    class="config-form__input"
                    placeholder="/etc/codify/docker/key.pem"
                  />
                </n-form-item>
              </n-gi>
            </n-grid>
            <div v-if="insecureRemoteDocker" class="docker-target-warning">
              {{ t('config.insecureDockerTargetWarning') }}
            </div>
            <div v-if="dockerTestResult" class="docker-test-result">
              <strong>{{ dockerTestResult.architecture || '—' }}</strong>
              <span>{{ dockerTestResult.operating_system || '—' }}</span>
              <span>{{ dockerTestResult.server_version || '—' }}</span>
              <span>{{ dockerTestResult.elapsed_ms }} ms</span>
            </div>
          </div>

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
            <n-tabs
              v-model:value="activeRunInstructionTab"
              type="segment"
              class="config-run-instructions-tabs"
            >
              <n-tab-pane name="execute" :tab="t('config.runInstructionImplementationTab')">
                <RunInstructionTemplateEditor
                  v-model="workerFormValue.default_execute_run_instruction_template"
                  :fixed-rows="12"
                  :available-placeholders="builtIns?.execute.available_placeholders ?? []"
                  :known-placeholders="knownPromptPlaceholders"
                  @use-prompt-only="usePromptOnly('execute')"
                  @restore-default="restoreBuiltIn('execute')"
                />
              </n-tab-pane>
              <n-tab-pane name="plan" :tab="t('config.runInstructionAnalysisTab')">
                <RunInstructionTemplateEditor
                  v-model="workerFormValue.default_plan_run_instruction_template"
                  :fixed-rows="12"
                  :available-placeholders="builtIns?.plan.available_placeholders ?? []"
                  :known-placeholders="knownPromptPlaceholders"
                  @use-prompt-only="usePromptOnly('plan')"
                  @restore-default="restoreBuiltIn('plan')"
                />
              </n-tab-pane>
              <n-tab-pane
                name="ci_auto_repair"
                :tab="t('config.runInstructionCiAutoRepairTab')"
              >
                <RunInstructionTemplateEditor
                  v-model="workerFormValue.ci_auto_repair_run_instruction_template"
                  :fixed-rows="12"
                  :available-placeholders="builtIns?.ci_auto_repair.available_placeholders ?? []"
                  :known-placeholders="knownPromptPlaceholders"
                  :warn-when-user-prompt-missing="false"
                  hide-prompt-only
                  @restore-default="restoreBuiltIn('ci_auto_repair')"
                />
              </n-tab-pane>
            </n-tabs>
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
            </section>
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
  NPopconfirm,
  NSelect,
  NSpace,
  NSpin,
  NSwitch,
  NTabPane,
  NTabs,
  NTag,
  useMessage
} from 'naive-ui'
import { useI18n } from 'vue-i18n'
import {
  createWorkerProfile,
  deleteWorkerProfile,
  disableWorkerProfile,
  duplicateWorkerProfile,
  enableWorkerProfile,
  getAdminSkills,
  getConfig,
  getAdminWorkerProfiles,
  getRunInstructionTemplateBuiltIns,
  setDefaultWorkerProfile,
  testWorkerDockerConnection,
  updateConfig,
  updateWorkerProfile,
  type RunInstructionTemplateBuiltIns,
  type SkillSummary,
  type DockerConnectionTestResult,
  type WorkerProfile,
  type WorkerProfileEnvironmentVariable,
  type WorkerProfileEnvironmentVariableUpdate,
  type WorkerProfileMount,
  type WorkerProfilePayload
} from '../../api'
import RunInstructionTemplateEditor from '../RunInstructionTemplateEditor.vue'

type WorkerFormValue = {
  name: string
  description: string | null
  enabled: boolean
  is_default: boolean
  image: string
  runtime_mode: 'baked_image' | 'mounted_kit'
  worker_kit_version: string
  worker_kit_path: string
  use_system_docker: boolean
  docker_host: string
  docker_tls_ca: string
  docker_tls_cert: string
  docker_tls_key: string
  codegraph_enabled: boolean
  enabled_harnesses: string[]
  default_harness_key: string
  harness_constraints: Record<string, unknown>
  image_digest: string | null
  mounts: WorkerProfileMount[]
  environment_variables: EnvironmentVariableFormItem[]
  default_skill_ids: number[]
  worker_workspace_retention_days: number
  worker_workspace_host_path: string
  worker_pre_script: string
  worker_post_script: string
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

type ArtifactFormValue = {
  maxTotalMiB: number
  maxFileMiB: number
  maxEntries: number
  retentionDays: number
}

const props = defineProps<{
  isMobile: boolean
  reloadKey?: number
}>()

const message = useMessage()
const { t } = useI18n()

const loading = ref(false)
const workerSaving = ref(false)
const dockerTesting = ref(false)
const dockerTestResult = ref<DockerConnectionTestResult | null>(null)
const builtIns = ref<RunInstructionTemplateBuiltIns | null>(null)
const workerProfiles = ref<WorkerProfile[]>([])
const skills = ref<SkillSummary[]>([])
const selectedProfileId = ref<number | null>(null)
const creatingWorkerProfile = ref(false)
const activeRunInstructionTab = ref<'execute' | 'plan' | 'ci_auto_repair'>('execute')
const harnessSelectOptions = computed(() => [
  { label: t('createTask.harnessClaude'), value: 'claude' },
  { label: t('createTask.harnessCodex'), value: 'codex' },
])
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

const workerRuntimeModeOptions = [
  { label: t('config.workerRuntimeModeBakedImage'), value: 'baked_image' },
  { label: t('config.workerRuntimeModeMountedKit'), value: 'mounted_kit' }
]

const environmentVariableTypeOptions = [
  { label: t('config.environmentVariablePlainText'), value: 'plain_text' },
  { label: t('config.environmentVariableSecret'), value: 'secret' }
]
const skillOptions = computed(() =>
  skills.value.map(skill => ({
    label: skill.enabled
      ? skill.name
      : `${skill.name} (${t('config.disabled')})`,
    value: skill.id,
    disabled: !skill.enabled,
  }))
)

const workerFormValue = ref<WorkerFormValue>({
  name: '',
  description: null,
  enabled: true,
  is_default: false,
  image: '',
  runtime_mode: 'baked_image',
  worker_kit_version: '',
  worker_kit_path: '',
  use_system_docker: true,
  docker_host: '',
  docker_tls_ca: '',
  docker_tls_cert: '',
  docker_tls_key: '',
  codegraph_enabled: false,
  enabled_harnesses: ['claude'],
  default_harness_key: 'claude',
  harness_constraints: {},
  image_digest: null,
  mounts: [],
  environment_variables: [],
  default_skill_ids: [],
  worker_workspace_retention_days: 14,
  worker_workspace_host_path: '/opt/codify-workspaces',
  worker_pre_script: '',
  worker_post_script: '',
  default_execute_run_instruction_template: '',
  default_plan_run_instruction_template: '',
  ci_auto_repair_run_instruction_template: ''
})

const lastLoadedWorker = ref<WorkerFormValue>(createEmptyWorkerFormValue())
const lastLoadedWorkspace = ref({
  worker_workspace_retention_days: 14,
  worker_workspace_host_path: '/opt/codify-workspaces'
})
const workspaceSaving = ref(false)
const artifactSaving = ref(false)
const MEBIBYTE = 1024 * 1024
const artifactFormValue = ref<ArtifactFormValue>({
  maxTotalMiB: 200,
  maxFileMiB: 100,
  maxEntries: 5000,
  retentionDays: 30
})
const lastLoadedArtifacts = ref<ArtifactFormValue>({ ...artifactFormValue.value })

const isWorkerDirty = computed(() =>
  JSON.stringify(workerProfileComparable(workerFormValue.value)) !==
  JSON.stringify(workerProfileComparable(lastLoadedWorker.value))
)
const isWorkspaceDirty = computed(() =>
  workerFormValue.value.worker_workspace_retention_days !==
    lastLoadedWorkspace.value.worker_workspace_retention_days
)
const isArtifactDirty = computed(
  () => JSON.stringify(artifactFormValue.value) !== JSON.stringify(lastLoadedArtifacts.value)
)
const artifactLimitsValid = computed(
  () => artifactFormValue.value.maxFileMiB <= artifactFormValue.value.maxTotalMiB
)

const isWorkerBusy = computed(() =>
  loading.value ||
  workerSaving.value ||
  workspaceSaving.value ||
  artifactSaving.value ||
  dockerTesting.value
)
const insecureRemoteDocker = computed(() =>
  !workerFormValue.value.use_system_docker &&
  workerFormValue.value.docker_host.startsWith('tcp://') &&
  !workerFormValue.value.docker_tls_ca
)

function compareMountContainerPaths(
  left: Pick<WorkerProfileMount, 'container_path'>,
  right: Pick<WorkerProfileMount, 'container_path'>
): number {
  return left.container_path.localeCompare(right.container_path)
}

function parseMounts(mounts: WorkerProfileMount[] | undefined): WorkerProfileMount[] {
  if (!Array.isArray(mounts)) return []

  return mounts.map((mount) => ({ ...mount })).sort(compareMountContainerPaths)
}

function serializeMounts(mounts: WorkerProfileMount[]): WorkerProfileMount[] {
  return mounts
    .filter((mount) => mount.host_path && mount.container_path)
    .sort(compareMountContainerPaths)
}

function parseEnvironmentVariables(
  environmentVariables: WorkerProfileEnvironmentVariable[] | undefined
): EnvironmentVariableFormItem[] {
  if (!Array.isArray(environmentVariables)) return []

  return [...environmentVariables]
    .sort(compareEnvironmentVariableKeys)
    .map((environmentVariable) => ({
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
): WorkerProfileEnvironmentVariableUpdate[] {
  return environmentVariables
    .map((environmentVariable) => ({
      id: environmentVariable.id,
      key: environmentVariable.key.trim(),
      value: environmentVariable.value,
      is_secret: environmentVariable.is_secret
    }))
    .filter((environmentVariable) => environmentVariable.key)
    .sort(compareEnvironmentVariableKeys)
}

function compareEnvironmentVariableKeys(
  left: Pick<EnvironmentVariableFormItem, 'key'>,
  right: Pick<EnvironmentVariableFormItem, 'key'>
): number {
  return left.key.localeCompare(right.key)
}

function mapProfileToWorkerFormValue(
  profile: WorkerProfile | null,
  workerWorkspaceRetentionDays: number,
  workerWorkspaceHostPath = '/opt/codify-workspaces'
): WorkerFormValue {
  return {
    name: profile?.name ?? '',
    description: profile?.description ?? null,
    enabled: profile?.enabled ?? true,
    is_default: profile?.is_default ?? false,
    image: profile?.image ?? '',
    runtime_mode: profile?.runtime_mode ?? 'baked_image',
    worker_kit_version: profile?.worker_kit_version ?? '',
    worker_kit_path: profile?.worker_kit_path ?? '',
    use_system_docker: !profile?.docker_host,
    docker_host: profile?.docker_host ?? '',
    docker_tls_ca: profile?.docker_tls_ca ?? '',
    docker_tls_cert: profile?.docker_tls_cert ?? '',
    docker_tls_key: profile?.docker_tls_key ?? '',
    codegraph_enabled: profile?.codegraph_enabled ?? false,
    enabled_harnesses: profile?.enabled_harnesses?.length
      ? [...profile.enabled_harnesses]
      : ['claude'],
    default_harness_key: profile?.default_harness_key ?? 'claude',
    harness_constraints: profile?.harness_constraints ?? {},
    image_digest: profile?.image_digest ?? null,
    mounts: parseMounts(profile?.volume_mounts),
    environment_variables: parseEnvironmentVariables(profile?.environment_variables),
    default_skill_ids: [...(profile?.default_skill_ids ?? [])],
    worker_workspace_retention_days: workerWorkspaceRetentionDays,
    worker_workspace_host_path: workerWorkspaceHostPath,
    worker_pre_script: profile?.pre_script || '',
    worker_post_script: profile?.post_script || '',
    default_execute_run_instruction_template:
      profile?.default_execute_run_instruction_template || '',
    default_plan_run_instruction_template:
      profile?.default_plan_run_instruction_template || '',
    ci_auto_repair_run_instruction_template:
      profile?.ci_auto_repair_run_instruction_template || ''
  }
}

function cloneWorkerFormValue(value: WorkerFormValue): WorkerFormValue {
  return {
    name: value.name,
    description: value.description,
    enabled: value.enabled,
    is_default: value.is_default,
    image: value.image,
    runtime_mode: value.runtime_mode,
    worker_kit_version: value.worker_kit_version,
    worker_kit_path: value.worker_kit_path,
    use_system_docker: value.use_system_docker,
    docker_host: value.docker_host,
    docker_tls_ca: value.docker_tls_ca,
    docker_tls_cert: value.docker_tls_cert,
    docker_tls_key: value.docker_tls_key,
    codegraph_enabled: value.codegraph_enabled,
    enabled_harnesses: value.enabled_harnesses?.length
      ? [...value.enabled_harnesses]
      : ['claude'],
    default_harness_key: value.default_harness_key ?? 'claude',
    harness_constraints: value.harness_constraints ?? {},
    image_digest: value.image_digest ?? null,
    mounts: value.mounts.map((mount) => ({ ...mount })),
    environment_variables: value.environment_variables.map((environmentVariable) => ({
      ...environmentVariable
    })),
    default_skill_ids: [...value.default_skill_ids],
    worker_workspace_retention_days: value.worker_workspace_retention_days,
    worker_workspace_host_path: value.worker_workspace_host_path,
    worker_pre_script: value.worker_pre_script,
    worker_post_script: value.worker_post_script,
    default_execute_run_instruction_template: value.default_execute_run_instruction_template,
    default_plan_run_instruction_template: value.default_plan_run_instruction_template,
    ci_auto_repair_run_instruction_template: value.ci_auto_repair_run_instruction_template
  }
}

function workerProfileComparable(value: WorkerFormValue) {
  const {
    worker_workspace_retention_days: _retentionDays,
    worker_workspace_host_path: _workspaceHostPath,
    ...profile
  } = value
  return profile
}

async function fetchConfig() {
  loading.value = true
  try {
    const [configResult, builtInsResult, profilesResult, skillsResult] = await Promise.allSettled([
      getConfig(),
      getRunInstructionTemplateBuiltIns(),
      getAdminWorkerProfiles(),
      getAdminSkills()
    ])
    if (configResult.status === 'rejected') throw configResult.reason
    if (profilesResult.status === 'rejected') throw profilesResult.reason
    if (skillsResult.status === 'rejected') throw skillsResult.reason
    const config = configResult.value
    if (builtInsResult.status === 'fulfilled') {
      builtIns.value = builtInsResult.value
    }
    workerProfiles.value = profilesResult.value
    skills.value = skillsResult.value
    const retentionDays = config.runtime?.worker_workspace_retention_days ?? 14
    const selectedProfile =
      workerProfiles.value.find((profile) => profile.is_default) ??
      workerProfiles.value.find((profile) => profile.enabled) ??
      workerProfiles.value[0] ??
      null
    creatingWorkerProfile.value = false
    selectedProfileId.value = selectedProfile?.id ?? null
    workerFormValue.value = mapProfileToWorkerFormValue(
      selectedProfile,
      retentionDays,
      config.runtime?.worker_workspace_host_path ?? '/opt/codify-workspaces'
    )
    lastLoadedWorker.value = cloneWorkerFormValue(workerFormValue.value)
    lastLoadedWorkspace.value = {
      worker_workspace_retention_days: workerFormValue.value.worker_workspace_retention_days,
      worker_workspace_host_path: workerFormValue.value.worker_workspace_host_path
    }
    artifactFormValue.value = {
      maxTotalMiB: (config.runtime?.worker_artifacts_max_total_bytes ?? 200 * MEBIBYTE) / MEBIBYTE,
      maxFileMiB: (config.runtime?.worker_artifacts_max_file_bytes ?? 100 * MEBIBYTE) / MEBIBYTE,
      maxEntries: config.runtime?.worker_artifacts_max_entries ?? 5000,
      retentionDays: config.runtime?.worker_runtime_archive_retention_days ?? 30
    }
    lastLoadedArtifacts.value = { ...artifactFormValue.value }
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
    name: '',
    description: null,
    enabled: true,
    is_default: false,
    image: '',
    runtime_mode: 'baked_image',
    worker_kit_version: '',
    worker_kit_path: '',
    use_system_docker: true,
    docker_host: '',
    docker_tls_ca: '',
    docker_tls_cert: '',
    docker_tls_key: '',
    codegraph_enabled: false,
    enabled_harnesses: ['claude'],
    default_harness_key: 'claude',
    harness_constraints: {},
    image_digest: null,
    mounts: [],
    environment_variables: [],
    default_skill_ids: [],
    worker_workspace_retention_days: 14,
    worker_workspace_host_path: '/opt/codify-workspaces',
    worker_pre_script: '',
    worker_post_script: '',
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

function usePromptOnly(mode: 'execute' | 'plan') {
  if (mode === 'execute') {
    workerFormValue.value.default_execute_run_instruction_template = '{{user_prompt}}'
    return
  }
  workerFormValue.value.default_plan_run_instruction_template = '{{user_prompt}}'
}

function selectProfile(profileId: number) {
  const profile = workerProfiles.value.find((item) => item.id === profileId)
  if (!profile) return
  creatingWorkerProfile.value = false
  selectedProfileId.value = profileId
  workerFormValue.value = mapProfileToWorkerFormValue(
    profile,
    workerFormValue.value.worker_workspace_retention_days,
    workerFormValue.value.worker_workspace_host_path
  )
  lastLoadedWorker.value = cloneWorkerFormValue(workerFormValue.value)
}

function buildWorkerProfilePayload(): WorkerProfilePayload {
  return {
    name: workerFormValue.value.name,
    description: workerFormValue.value.description,
    enabled: workerFormValue.value.enabled,
    image: workerFormValue.value.image,
    runtime_mode: workerFormValue.value.runtime_mode,
    worker_kit_version:
      workerFormValue.value.runtime_mode === 'mounted_kit'
        ? workerFormValue.value.worker_kit_version
        : null,
    worker_kit_path:
      workerFormValue.value.runtime_mode === 'mounted_kit'
        ? workerFormValue.value.worker_kit_path
        : null,
    docker_host: workerFormValue.value.use_system_docker
      ? null
      : workerFormValue.value.docker_host,
    docker_tls_ca: workerFormValue.value.use_system_docker
      ? null
      : workerFormValue.value.docker_tls_ca,
    docker_tls_cert: workerFormValue.value.use_system_docker
      ? null
      : workerFormValue.value.docker_tls_cert,
    docker_tls_key: workerFormValue.value.use_system_docker
      ? null
      : workerFormValue.value.docker_tls_key,
    codegraph_enabled: workerFormValue.value.codegraph_enabled,
    volume_mounts: serializeMounts(workerFormValue.value.mounts),
    environment_variables: serializeEnvironmentVariables(
      workerFormValue.value.environment_variables
    ),
    default_skill_ids:
      workerFormValue.value.runtime_mode === 'mounted_kit'
        ? [...workerFormValue.value.default_skill_ids]
        : [],
    pre_script: workerFormValue.value.worker_pre_script,
    post_script: workerFormValue.value.worker_post_script,
    default_execute_run_instruction_template:
      workerFormValue.value.default_execute_run_instruction_template,
    default_plan_run_instruction_template: workerFormValue.value.default_plan_run_instruction_template,
    ci_auto_repair_run_instruction_template: workerFormValue.value.ci_auto_repair_run_instruction_template
  }
}

function replaceLoadedProfile(profile: WorkerProfile) {
  const index = workerProfiles.value.findIndex((item) => item.id === profile.id)
  if (index >= 0) {
    workerProfiles.value.splice(index, 1, profile)
  } else {
    workerProfiles.value.unshift(profile)
  }
}

async function handleSaveWorker() {
  if (selectedProfileId.value === null && !creatingWorkerProfile.value) {
    message.error(t('config.saveError'))
    return
  }
  workerSaving.value = true
  try {
    const savedProfile = creatingWorkerProfile.value
      ? await createWorkerProfile(buildWorkerProfilePayload())
      : await updateWorkerProfile(
          selectedProfileId.value as number,
          buildWorkerProfilePayload()
        )
    replaceLoadedProfile(savedProfile)
    selectedProfileId.value = savedProfile.id
    creatingWorkerProfile.value = false
    workerFormValue.value = mapProfileToWorkerFormValue(
      savedProfile,
      workerFormValue.value.worker_workspace_retention_days,
      workerFormValue.value.worker_workspace_host_path
    )
    lastLoadedWorker.value = cloneWorkerFormValue(workerFormValue.value)
    message.success(t('config.saved'))
  } catch (error: any) {
    message.error(error?.response?.data?.detail || t('config.saveError'))
  } finally {
    workerSaving.value = false
  }
}

async function handleSaveWorkspace() {
  workspaceSaving.value = true
  try {
    const savedConfig = await updateConfig({
      runtime: {
        worker_workspace_retention_days:
          workerFormValue.value.worker_workspace_retention_days
      }
    })
    workerFormValue.value.worker_workspace_retention_days =
      savedConfig.runtime?.worker_workspace_retention_days ??
      workerFormValue.value.worker_workspace_retention_days
    workerFormValue.value.worker_workspace_host_path =
      savedConfig.runtime?.worker_workspace_host_path ?? workerFormValue.value.worker_workspace_host_path
    lastLoadedWorkspace.value = {
      worker_workspace_retention_days: workerFormValue.value.worker_workspace_retention_days,
      worker_workspace_host_path: workerFormValue.value.worker_workspace_host_path
    }
    message.success(t('config.saved'))
  } catch (error: any) {
    message.error(error?.response?.data?.detail || t('config.saveError'))
  } finally {
    workspaceSaving.value = false
  }
}

async function handleSaveArtifacts() {
  if (!artifactLimitsValid.value) {
    message.error(t('config.artifactFileLimitError'))
    return
  }
  artifactSaving.value = true
  try {
    const savedConfig = await updateConfig({
      runtime: {
        worker_artifacts_max_total_bytes: Math.round(
          artifactFormValue.value.maxTotalMiB * MEBIBYTE
        ),
        worker_artifacts_max_file_bytes: Math.round(
          artifactFormValue.value.maxFileMiB * MEBIBYTE
        ),
        worker_artifacts_max_entries: artifactFormValue.value.maxEntries,
        worker_runtime_archive_retention_days: artifactFormValue.value.retentionDays
      }
    })
    artifactFormValue.value = {
      maxTotalMiB:
        (savedConfig.runtime?.worker_artifacts_max_total_bytes ??
          artifactFormValue.value.maxTotalMiB * MEBIBYTE) / MEBIBYTE,
      maxFileMiB:
        (savedConfig.runtime?.worker_artifacts_max_file_bytes ??
          artifactFormValue.value.maxFileMiB * MEBIBYTE) / MEBIBYTE,
      maxEntries:
        savedConfig.runtime?.worker_artifacts_max_entries ?? artifactFormValue.value.maxEntries,
      retentionDays:
        savedConfig.runtime?.worker_runtime_archive_retention_days ??
        artifactFormValue.value.retentionDays
    }
    lastLoadedArtifacts.value = { ...artifactFormValue.value }
    message.success(t('config.saved'))
  } catch (error: any) {
    message.error(error?.response?.data?.detail || t('config.saveError'))
  } finally {
    artifactSaving.value = false
  }
}

function resetWorker() {
  const retentionDays = workerFormValue.value.worker_workspace_retention_days
  const workspaceHostPath = workerFormValue.value.worker_workspace_host_path
  workerFormValue.value = cloneWorkerFormValue(lastLoadedWorker.value)
  workerFormValue.value.worker_workspace_retention_days = retentionDays
  workerFormValue.value.worker_workspace_host_path = workspaceHostPath
}

function handleCreateProfile() {
  const draft = createEmptyWorkerFormValue()
  draft.image = workerFormValue.value.image || 'codify-worker/java21-maven:2026.07'
  draft.worker_workspace_retention_days = workerFormValue.value.worker_workspace_retention_days
  draft.worker_workspace_host_path = workerFormValue.value.worker_workspace_host_path
  draft.default_execute_run_instruction_template =
    builtIns.value?.execute.content ||
    workerFormValue.value.default_execute_run_instruction_template
  draft.default_plan_run_instruction_template =
    builtIns.value?.plan.content || workerFormValue.value.default_plan_run_instruction_template
  draft.ci_auto_repair_run_instruction_template =
    builtIns.value?.ci_auto_repair.content ||
    workerFormValue.value.ci_auto_repair_run_instruction_template

  creatingWorkerProfile.value = true
  selectedProfileId.value = null
  workerFormValue.value = draft
  lastLoadedWorker.value = cloneWorkerFormValue(draft)
}

async function handleDuplicateProfile() {
  if (selectedProfileId.value === null) return
  workerSaving.value = true
  try {
    const copy = await duplicateWorkerProfile(selectedProfileId.value)
    replaceLoadedProfile(copy)
    selectProfile(copy.id)
    message.success(t('config.saved'))
  } catch (error: any) {
    message.error(error?.response?.data?.detail || t('config.saveError'))
  } finally {
    workerSaving.value = false
  }
}

async function handleSetDefaultProfile() {
  if (selectedProfileId.value === null) return
  workerSaving.value = true
  try {
    const updated = await setDefaultWorkerProfile(selectedProfileId.value)
    workerProfiles.value = workerProfiles.value.map((profile) => ({
      ...profile,
      is_default: profile.id === updated.id
    }))
    replaceLoadedProfile(updated)
    selectProfile(updated.id)
    message.success(t('config.saved'))
  } catch (error: any) {
    message.error(error?.response?.data?.detail || t('config.saveError'))
  } finally {
    workerSaving.value = false
  }
}

async function handleDisableProfile() {
  if (selectedProfileId.value === null) return
  workerSaving.value = true
  try {
    const disabled = await disableWorkerProfile(selectedProfileId.value)
    replaceLoadedProfile(disabled)
    selectProfile(disabled.id)
    message.success(t('config.saved'))
  } catch (error: any) {
    message.error(error?.response?.data?.detail || t('config.saveError'))
  } finally {
    workerSaving.value = false
  }
}

async function handleEnableProfile() {
  if (selectedProfileId.value === null) return
  workerSaving.value = true
  try {
    const enabled = await enableWorkerProfile(selectedProfileId.value)
    replaceLoadedProfile(enabled)
    selectProfile(enabled.id)
    message.success(t('config.workerProfileEnabled'))
  } catch (error: any) {
    message.error(error?.response?.data?.detail || t('config.saveError'))
  } finally {
    workerSaving.value = false
  }
}

async function handleDeleteProfile() {
  if (selectedProfileId.value === null) return
  const profileId = selectedProfileId.value
  workerSaving.value = true
  try {
    await deleteWorkerProfile(profileId)
    workerProfiles.value = workerProfiles.value.filter((profile) => profile.id !== profileId)
    const nextProfile =
      workerProfiles.value.find((profile) => profile.is_default) ??
      workerProfiles.value.find((profile) => profile.enabled) ??
      workerProfiles.value[0] ??
      null
    creatingWorkerProfile.value = false
    selectedProfileId.value = nextProfile?.id ?? null
    workerFormValue.value = mapProfileToWorkerFormValue(
      nextProfile,
      workerFormValue.value.worker_workspace_retention_days,
      workerFormValue.value.worker_workspace_host_path
    )
    lastLoadedWorker.value = cloneWorkerFormValue(workerFormValue.value)
    message.success(t('config.workerProfileDeleted'))
  } catch (error: any) {
    message.error(error?.response?.data?.detail || t('config.deleteWorkerProfileFailed'))
  } finally {
    workerSaving.value = false
  }
}

async function handleTestDockerConnection() {
  dockerTesting.value = true
  dockerTestResult.value = null
  try {
    dockerTestResult.value = await testWorkerDockerConnection({
      docker_host: workerFormValue.value.use_system_docker
        ? null
        : workerFormValue.value.docker_host,
      docker_tls_ca: workerFormValue.value.use_system_docker
        ? null
        : workerFormValue.value.docker_tls_ca,
      docker_tls_cert: workerFormValue.value.use_system_docker
        ? null
        : workerFormValue.value.docker_tls_cert,
      docker_tls_key: workerFormValue.value.use_system_docker
        ? null
        : workerFormValue.value.docker_tls_key
    })
    message.success(t('config.dockerConnectionSucceeded'))
  } catch (error: any) {
    message.error(error?.response?.data?.detail || t('config.dockerConnectionFailed'))
  } finally {
    dockerTesting.value = false
  }
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

watch(
  () => workerFormValue.value.enabled_harnesses,
  (enabled) => {
    const list = enabled?.length ? enabled : ['claude']
    const def = workerFormValue.value.default_harness_key
    if (!def || !list.includes(def)) {
      workerFormValue.value.default_harness_key = list[0]
    }
  },
)

watch(
  () => [
    workerFormValue.value.use_system_docker,
    workerFormValue.value.docker_host,
    workerFormValue.value.docker_tls_ca,
    workerFormValue.value.docker_tls_cert,
    workerFormValue.value.docker_tls_key
  ],
  () => {
    dockerTestResult.value = null
  }
)
</script>

<style scoped>
.worker-profile-layout {
  display: grid;
  grid-template-columns: minmax(180px, 240px) minmax(0, 1fr);
  gap: 16px;
  align-items: start;
}

.worker-profile-list {
  display: grid;
  gap: 8px;
  min-width: 0;
}

.worker-profile-list__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  font-size: 13px;
  font-weight: 600;
  color: rgba(15, 23, 42, 0.68);
}

.worker-profile-list__item {
  display: grid;
  gap: 4px;
  width: 100%;
  min-width: 0;
  padding: 10px;
  text-align: left;
  cursor: pointer;
  background: #fff;
  border: 1px solid rgba(15, 23, 42, 0.08);
  border-radius: 8px;
}

.worker-profile-list__item--active {
  border-color: rgba(24, 160, 88, 0.42);
  background: rgba(24, 160, 88, 0.06);
}

.worker-profile-list__name {
  min-width: 0;
  overflow: hidden;
  font-weight: 600;
  color: rgba(15, 23, 42, 0.84);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.worker-profile-list__tags {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}

.worker-profile-list small {
  min-width: 0;
  overflow: hidden;
  color: rgba(15, 23, 42, 0.52);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.worker-profile-editor {
  min-width: 0;
}

.docker-target-section {
  gap: 8px;
}

.docker-target-warning {
  padding: 8px 10px;
  font-size: 12px;
  color: #8a5a00;
  background: #fff8e6;
  border: 1px solid #f0d79a;
  border-radius: 6px;
}

.docker-test-result {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 16px;
  padding: 9px 10px;
  font-size: 12px;
  color: rgba(15, 23, 42, 0.68);
  background: rgba(24, 160, 88, 0.06);
  border: 1px solid rgba(24, 160, 88, 0.2);
  border-radius: 6px;
}

.config-collection-section {
  gap: 8px;
}

.config-run-instructions-tabs {
  width: 100%;
}

.config-run-instructions-tabs :deep(.n-tabs-rail),
.config-run-instructions-tabs :deep(.n-tabs-capsule),
.config-run-instructions-tabs :deep(.n-tabs-tab) {
  border-radius: 8px;
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
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr) 158px 76px;
}

.config-compact-table--environment .config-compact-table__header,
.config-compact-row--environment {
  grid-template-columns: minmax(140px, 0.8fr) 120px minmax(220px, 1.2fr) 76px;
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
  max-width: 100%;
  justify-self: end;
}

@media (max-width: 767px) {
  .worker-profile-layout {
    grid-template-columns: minmax(0, 1fr);
  }

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
