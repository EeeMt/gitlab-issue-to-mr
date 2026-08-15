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
              <button
                type="button"
                class="worker-shared-entry"
                :class="{ 'worker-shared-entry--active': editorMode === 'shared' }"
                data-testid="worker-shared-configuration-entry"
                @click="selectSharedConfiguration"
              >
                <span class="worker-shared-entry__eyebrow">{{ t('config.systemBaseline') }}</span>
                <strong>{{ t('config.workerSharedConfiguration') }}</strong>
                <small>{{ t('config.workerSharedConfigurationEntryHint') }}</small>
              </button>
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
                :class="{
                  'worker-profile-list__item--active':
                    editorMode === 'profile' && profile.id === selectedProfileId
                }"
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
                  <n-tag
                    size="small"
                    :type="readinessTagType(profile.runtime_readiness?.status)"
                    :bordered="false"
                  >
                    {{ readinessLabel(profile.runtime_readiness?.status) }}
                  </n-tag>
                  <n-tag
                    size="small"
                    :type="profile.runtime_verification?.matches_current_input ? 'success' : 'default'"
                    :bordered="false"
                  >
                    {{
                      profile.runtime_verification?.matches_current_input
                        ? t('config.profileRuntimeVerified')
                        : t('config.profileRuntimeUnverified')
                    }}
                  </n-tag>
                </span>
                <small>{{ profile.image }}</small>
              </button>
            </aside>
            <section
              v-if="editorMode === 'shared'"
              class="worker-profile-editor worker-shared-editor"
              data-testid="worker-shared-configuration-editor"
            >
              <div class="config-form__section worker-editor-heading">
                <div class="worker-editor-heading__copy">
                  <span class="worker-editor-heading__eyebrow">{{ t('config.systemBaseline') }}</span>
                  <div class="config-form__section-title">{{ t('config.workerSharedConfiguration') }}</div>
                  <p>{{ t('config.workerSharedConfigurationHint') }}</p>
                </div>
                <div class="worker-shared-meta">
                  <n-tag size="small" :bordered="false">
                    {{ t('config.sharedRevision', { revision: sharedFormValue.revision }) }}
                  </n-tag>
                  <span v-if="sharedFormValue.updated_at">
                    {{ t('config.lastUpdatedAt', { time: formatTimestamp(sharedFormValue.updated_at) }) }}
                  </span>
                </div>
              </div>

              <div class="config-form__section">
                <div class="config-form__section-title">{{ t('config.workerKit') }}</div>
                <n-grid :cols="isMobile ? 1 : 2" :x-gap="16" :y-gap="8">
                  <n-gi>
                    <n-form-item :label="t('config.workerRuntimeMode')">
                      <n-select
                        v-model:value="sharedFormValue.runtime_mode"
                        :options="workerRuntimeModeOptions"
                        class="config-form__input"
                      />
                    </n-form-item>
                  </n-gi>
                  <n-gi v-if="sharedFormValue.runtime_mode === 'mounted_kit'">
                    <n-form-item :label="t('config.workerKitVersion')">
                      <n-input
                        v-model:value="sharedFormValue.worker_kit_version"
                        class="config-form__input"
                        placeholder="0.4.0"
                      />
                    </n-form-item>
                  </n-gi>
                  <n-gi v-if="sharedFormValue.runtime_mode === 'mounted_kit'" :span="isMobile ? 1 : 2">
                    <n-form-item :label="t('config.workerKitPath')">
                      <n-input
                        v-model:value="sharedFormValue.worker_kit_path"
                        class="config-form__input"
                        placeholder="/opt/codify/worker-kits/0.4.0"
                      />
                      <template #feedback>{{ t('config.workerKitPathHint') }}</template>
                    </n-form-item>
                  </n-gi>
                </n-grid>
              </div>

              <div class="config-form__section config-collection-section">
                <div class="config-form__section-header">
                  <div class="config-collection-heading">
                    <div class="config-form__section-title">{{ t('config.sharedVolumeMounts') }}</div>
                    <n-tag size="small" round :bordered="false">{{ sharedFormValue.mounts.length }}</n-tag>
                  </div>
                  <n-button size="small" secondary @click="addSharedMount">
                    {{ t('config.addVolumeMount') }}
                  </n-button>
                </div>
                <div v-if="sharedFormValue.mounts.length === 0" class="config-empty config-compact-empty">
                  {{ t('config.noVolumeMounts') }}
                </div>
                <div v-else class="config-compact-table config-compact-table--mounts config-compact-table--shared">
                  <div class="config-compact-table__header" aria-hidden="true">
                    <span>{{ t('config.hostPath') }}</span>
                    <span>{{ t('config.containerPath') }}</span>
                    <span>{{ t('config.mountMode') }}</span>
                    <span></span>
                  </div>
                  <div
                    v-for="(mount, index) in sharedFormValue.mounts"
                    :key="`shared-mount-${index}`"
                    class="config-compact-row config-compact-row--mount config-compact-row--shared"
                  >
                    <label class="config-compact-field">
                      <span class="config-compact-field__label">{{ t('config.hostPath') }}</span>
                      <n-input v-model:value="mount.host_path" size="small" :placeholder="t('config.hostPathPlaceholder')" />
                    </label>
                    <label class="config-compact-field">
                      <span class="config-compact-field__label">{{ t('config.containerPath') }}</span>
                      <n-input v-model:value="mount.container_path" size="small" :placeholder="t('config.containerPathPlaceholder')" />
                    </label>
                    <label class="config-compact-field">
                      <span class="config-compact-field__label">{{ t('config.mountMode') }}</span>
                      <n-select v-model:value="mount.mode" size="small" :options="mountModeOptions" />
                    </label>
                    <n-button size="small" type="error" quaternary class="config-compact-row__remove" @click="removeSharedMount(index)">
                      {{ t('config.remove') }}
                    </n-button>
                  </div>
                </div>
              </div>

              <div class="config-form__section config-collection-section">
                <div class="config-form__section-header">
                  <div class="config-collection-heading">
                    <div class="config-form__section-title">{{ t('config.sharedEnvironmentVariables') }}</div>
                    <n-tag size="small" round :bordered="false">{{ sharedFormValue.environment_variables.length }}</n-tag>
                    <span class="config-collection-heading__hint">{{ t('config.environmentVariableSecretHint') }}</span>
                  </div>
                  <n-button size="small" secondary @click="addSharedEnvironmentVariable">
                    {{ t('config.addEnvironmentVariable') }}
                  </n-button>
                </div>
                <div v-if="sharedFormValue.environment_variables.length === 0" class="config-empty config-compact-empty">
                  {{ t('config.noEnvironmentVariables') }}
                </div>
                <div v-else class="config-compact-table config-compact-table--environment config-compact-table--shared">
                  <div class="config-compact-table__header" aria-hidden="true">
                    <span>{{ t('config.environmentVariableKey') }}</span>
                    <span>{{ t('config.environmentVariableType') }}</span>
                    <span>{{ t('config.environmentVariableValue') }}</span>
                    <span></span>
                  </div>
                  <div
                    v-for="(environmentVariable, index) in sharedFormValue.environment_variables"
                    :key="environmentVariable.id ?? `shared-env-${index}`"
                    class="config-compact-row config-compact-row--environment config-compact-row--shared"
                  >
                    <label class="config-compact-field">
                      <span class="config-compact-field__label">{{ t('config.environmentVariableKey') }}</span>
                      <n-input v-model:value="environmentVariable.key" size="small" :placeholder="t('config.environmentVariableKeyPlaceholder')" />
                    </label>
                    <label class="config-compact-field">
                      <span class="config-compact-field__label">{{ t('config.environmentVariableType') }}</span>
                      <n-select
                        :value="environmentVariable.is_secret ? 'secret' : 'plain_text'"
                        size="small"
                        :options="environmentVariableTypeOptions"
                        @update:value="(value) => { environmentVariable.is_secret = value === 'secret' }"
                      />
                    </label>
                    <label class="config-compact-field config-compact-field--value">
                      <span class="config-compact-field__label">{{ t('config.environmentVariableValue') }}</span>
                      <div class="config-compact-value">
                        <n-input
                          v-model:value="environmentVariable.value"
                          size="small"
                          :type="environmentVariable.is_secret ? 'password' : 'text'"
                          :placeholder="environmentVariable.is_secret && environmentVariable.value_configured ? t('config.configuredEnterNew') : t('config.environmentVariableValuePlaceholder')"
                        />
                        <n-tag v-if="environmentVariable.is_secret" size="small" :type="environmentVariable.value_configured ? 'success' : 'warning'" round :bordered="false">
                          {{ environmentVariable.value_configured ? t('config.configured') : t('config.missing') }}
                        </n-tag>
                      </div>
                    </label>
                    <n-button size="small" type="error" quaternary class="config-compact-row__remove" @click="removeSharedEnvironmentVariable(index)">
                      {{ t('config.remove') }}
                    </n-button>
                  </div>
                </div>
              </div>

              <div class="config-form__section config-scripts-section">
                <div class="config-form__section-title">{{ t('config.sharedScripts') }}</div>
                <n-grid :cols="isMobile ? 1 : 2" :x-gap="16" :y-gap="8">
                  <n-gi>
                    <n-form-item :label="t('config.workerPreScript')">
                      <n-input v-model:value="sharedFormValue.pre_script" type="textarea" :autosize="{ minRows: 5, maxRows: 12 }" />
                    </n-form-item>
                  </n-gi>
                  <n-gi>
                    <n-form-item :label="t('config.workerPostScript')">
                      <n-input v-model:value="sharedFormValue.post_script" type="textarea" :autosize="{ minRows: 5, maxRows: 12 }" />
                    </n-form-item>
                  </n-gi>
                </n-grid>
              </div>

              <div class="config-form__section config-run-instructions-section">
                <div class="config-form__section-title">{{ t('config.sharedRunInstructions') }}</div>
                <n-tabs v-model:value="sharedRunInstructionTab" type="segment" class="config-run-instructions-tabs">
                  <n-tab-pane name="execute" :tab="t('config.runInstructionImplementationTab')">
                    <RunInstructionTemplateEditor
                      v-model="sharedFormValue.default_execute_run_instruction_template"
                      :fixed-rows="12"
                      :available-placeholders="builtIns?.execute.available_placeholders ?? []"
                      :known-placeholders="knownPromptPlaceholders"
                      @use-prompt-only="useSharedPromptOnly('execute')"
                      @restore-default="restoreSharedBuiltIn('execute')"
                    />
                  </n-tab-pane>
                  <n-tab-pane name="plan" :tab="t('config.runInstructionAnalysisTab')">
                    <RunInstructionTemplateEditor
                      v-model="sharedFormValue.default_plan_run_instruction_template"
                      :fixed-rows="12"
                      :available-placeholders="builtIns?.plan.available_placeholders ?? []"
                      :known-placeholders="knownPromptPlaceholders"
                      @use-prompt-only="useSharedPromptOnly('plan')"
                      @restore-default="restoreSharedBuiltIn('plan')"
                    />
                  </n-tab-pane>
                  <n-tab-pane name="ci_auto_repair" :tab="t('config.runInstructionCiAutoRepairTab')">
                    <RunInstructionTemplateEditor
                      v-model="sharedFormValue.ci_auto_repair_run_instruction_template"
                      :fixed-rows="12"
                      :available-placeholders="builtIns?.ci_auto_repair.available_placeholders ?? []"
                      :known-placeholders="knownPromptPlaceholders"
                      :warn-when-user-prompt-missing="false"
                      hide-prompt-only
                      @restore-default="restoreSharedBuiltIn('ci_auto_repair')"
                    />
                  </n-tab-pane>
                </n-tabs>
              </div>

              <div class="config-card-actions config-card-actions--safe-area">
                <n-space :size="12" wrap>
                  <n-button type="primary" :loading="sharedSaving" :disabled="isWorkerBusy || !isSharedDirty" @click="handleSaveSharedConfiguration">
                    {{ t('config.saveSharedConfiguration') }}
                  </n-button>
                  <n-button secondary :disabled="isWorkerBusy || !isSharedDirty" @click="resetSharedConfiguration">
                    {{ t('config.revertChanges') }}
                  </n-button>
                </n-space>
              </div>
            </section>
            <section v-else class="worker-profile-editor" data-testid="worker-profile-editor">
          <div class="config-form__section">
            <div class="config-form__section-header">
              <div>
                <div class="config-form__section-title">{{ t('config.workerProfileConfiguration') }}</div>
                <div v-if="workerFormValue.shared_revision" class="worker-editor-heading__revision">
                  {{ t('config.usingSharedRevision', { revision: workerFormValue.shared_revision }) }}
                </div>
              </div>
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
            <div v-if="selectedProfileId !== null" class="worker-runtime-status" data-testid="worker-profile-runtime-status">
              <div class="worker-runtime-status__item">
                <span>{{ t('config.profileRuntimeVerification') }}</span>
                <n-tag
                  size="small"
                  :type="workerFormValue.runtime_verification.matches_current_input ? 'success' : 'warning'"
                  :bordered="false"
                >
                  {{
                    workerFormValue.runtime_verification.matches_current_input
                      ? t('config.profileRuntimeVerified')
                      : t('config.profileRuntimeUnverified')
                  }}
                </n-tag>
              </div>
              <div class="worker-runtime-status__item">
                <span>{{ t('config.workerKitReadiness') }}</span>
                <n-tag
                  size="small"
                  :type="readinessTagType(workerFormValue.runtime_readiness.status)"
                  :bordered="false"
                >
                  {{ readinessLabel(workerFormValue.runtime_readiness.status) }}
                </n-tag>
              </div>
              <div v-if="effectiveRuntimeMode === 'mounted_kit'" class="worker-runtime-status__details">
                <code>{{ effectiveWorkerKitVersion || '—' }}</code>
                <code>{{ effectiveWorkerKitPath || '—' }}</code>
                <span v-if="workerFormValue.runtime_readiness.checked_at">
                  {{ t('config.runtimeLastChecked', { time: formatTimestamp(workerFormValue.runtime_readiness.checked_at) }) }}
                </span>
                <span
                  v-if="workerFormValue.runtime_readiness.status === 'unavailable'"
                  class="worker-runtime-status__error"
                >
                  {{ workerFormValue.runtime_readiness.failure_message || t('config.runtimeFailureDetailsUnavailable') }}
                </span>
              </div>
              <n-button
                v-if="effectiveRuntimeMode === 'mounted_kit'"
                size="small"
                secondary
                :loading="runtimeVerifying"
                :disabled="isWorkerBusy || selectedProfileId === null"
                @click="handleVerifyProfileRuntime"
              >
                {{ t('config.verifyWorkerRuntime') }}
              </n-button>
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
                <n-form-item :label="t('config.followSystemWorkerKit')">
                  <n-switch :value="workerFormValue.worker_kit_source === 'system'" @update:value="setWorkerKitFollowsSystem" />
                  <template #feedback>{{ t('config.followSystemWorkerKitHint') }}</template>
                </n-form-item>
              </n-gi>
              <n-gi>
                <n-form-item :label="t('config.codegraph')">
                  <n-switch v-model:value="workerFormValue.codegraph_enabled" />
                  <template #feedback>
                    {{ t('config.codegraphHint') }}
                  </template>
                </n-form-item>
              </n-gi>
              <n-gi v-if="workerFormValue.worker_kit_source === 'system'" :span="isMobile ? 1 : 2">
                <div class="inherited-value-card">
                  <span class="source-label source-label--system">{{ t('config.sourceSystem') }}</span>
                  <strong>{{ runtimeModeLabel(effectiveRuntimeMode) }}</strong>
                  <code v-if="effectiveRuntimeMode === 'mounted_kit'">{{ effectiveWorkerKitVersion || '—' }}</code>
                  <code v-if="effectiveRuntimeMode === 'mounted_kit'">{{ effectiveWorkerKitPath || '—' }}</code>
                </div>
              </n-gi>
              <n-gi v-if="workerFormValue.worker_kit_source === 'profile'">
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
              <n-gi v-if="workerFormValue.worker_kit_source === 'profile' && workerFormValue.runtime_mode === 'mounted_kit'">
                <n-form-item :label="t('config.workerKitVersion')">
                  <n-input
                    v-model:value="workerFormValue.worker_kit_version"
                    class="config-form__input"
                    placeholder="0.3.6"
                  />
                </n-form-item>
              </n-gi>
              <n-gi v-if="workerFormValue.worker_kit_source === 'profile' && workerFormValue.runtime_mode === 'mounted_kit'">
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
              <n-gi>
                <n-form-item :label="t('config.harnesses')" path="enabled_harnesses">
                  <n-select
                    v-model:value="workerFormValue.enabled_harnesses"
                    multiple
                    :options="harnessSelectOptions"
                    :disabled="effectiveRuntimeMode !== 'mounted_kit'"
                  />
                  <template #feedback>
                    {{ t('config.harnessesHint') }}
                  </template>
                </n-form-item>
              </n-gi>
              <n-gi>
                <n-form-item :label="t('config.defaultHarness')" path="default_harness_key">
                  <n-select
                    v-model:value="workerFormValue.default_harness_key"
                    :options="harnessSelectOptions"
                    :disabled="effectiveRuntimeMode !== 'mounted_kit'"
                  />
                  <template #feedback>
                    {{ t('config.defaultHarnessHint') }}
                  </template>
                </n-form-item>
              </n-gi>
            </n-grid>
            <n-form-item :label="t('config.defaultSkills')">
              <n-select
                v-model:value="workerFormValue.default_skill_ids"
                multiple
                clearable
                filterable
                :disabled="effectiveRuntimeMode !== 'mounted_kit'"
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
                <div class="config-form__section-title">{{ t('config.profileVolumeMounts') }}</div>
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
                <span>{{ t('config.source') }}</span>
                <span>{{ t('config.hostPath') }}</span>
                <span>{{ t('config.containerPath') }}</span>
                <span>{{ t('config.mountMode') }}</span>
                <span></span>
              </div>
              <div
                v-for="(mount, index) in workerFormValue.mounts"
                :key="`${mount.source}-${mount.container_path}-${index}`"
                class="config-compact-row config-compact-row--mount"
                :class="`config-compact-row--${mount.source}`"
              >
                <div class="config-source-cell">
                  <span class="config-compact-field__label">{{ t('config.source') }}</span>
                  <span class="source-label" :class="`source-label--${mount.source}`">
                    {{ sourceLabel(mount.source) }}
                  </span>
                </div>
                <label class="config-compact-field">
                  <span class="config-compact-field__label">{{ t('config.hostPath') }}</span>
                  <n-input
                    v-model:value="mount.host_path"
                    size="small"
                    :placeholder="t('config.hostPathPlaceholder')"
                    :disabled="mount.source === 'system' || mount.source === 'profile_mask'"
                    class="config-form__input"
                  />
                </label>
                <label class="config-compact-field">
                  <span class="config-compact-field__label">{{ t('config.containerPath') }}</span>
                  <n-input
                    v-model:value="mount.container_path"
                    size="small"
                    :placeholder="t('config.containerPathPlaceholder')"
                    :disabled="mount.source !== 'profile_new'"
                    class="config-form__input"
                  />
                </label>
                <label class="config-compact-field">
                  <span class="config-compact-field__label">{{ t('config.mountMode') }}</span>
                  <n-select
                    v-model:value="mount.mode"
                    size="small"
                    :options="mountModeOptions"
                    :disabled="mount.source === 'system' || mount.source === 'profile_mask'"
                    class="config-form__input"
                  />
                </label>
                <div class="config-row-actions">
                  <template v-if="mount.source === 'system'">
                    <n-button size="small" secondary @click="overrideMount(index)">
                      {{ t('config.overrideHere') }}
                    </n-button>
                    <n-button size="small" secondary type="warning" @click="maskMount(index)">
                      {{ t('config.maskInProfile') }}
                    </n-button>
                  </template>
                  <n-button
                    v-else-if="mount.source === 'profile_override'"
                    size="small"
                    secondary
                    @click="restoreMountInheritance(index)"
                  >
                    {{ t('config.restoreSystemValue') }}
                  </n-button>
                  <n-button
                    v-else-if="mount.source === 'profile_mask'"
                    size="small"
                    secondary
                    @click="restoreMountInheritance(index)"
                  >
                    {{ t('config.restoreInheritance') }}
                  </n-button>
                  <n-button v-else size="small" type="error" quaternary @click="removeMount(index)">
                    {{ t('config.remove') }}
                  </n-button>
                </div>
              </div>
            </div>
          </div>

          <div class="config-form__section config-collection-section">
            <div class="config-form__section-header">
              <div class="config-collection-heading">
                <div class="config-form__section-title">{{ t('config.profileEnvironmentVariables') }}</div>
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
                <span>{{ t('config.source') }}</span>
                <span>{{ t('config.environmentVariableKey') }}</span>
                <span>{{ t('config.environmentVariableType') }}</span>
                <span>{{ t('config.environmentVariableValue') }}</span>
                <span></span>
              </div>
              <div
                v-for="(environmentVariable, index) in workerFormValue.environment_variables"
                :key="environmentVariable.id ?? `env-${index}`"
                class="config-compact-row config-compact-row--environment"
                :class="`config-compact-row--${environmentVariable.source}`"
              >
                <div class="config-source-cell">
                  <span class="config-compact-field__label">{{ t('config.source') }}</span>
                  <span class="source-label" :class="`source-label--${environmentVariable.source}`">
                    {{ sourceLabel(environmentVariable.source) }}
                  </span>
                </div>
                <label class="config-compact-field">
                  <span class="config-compact-field__label">
                    {{ t('config.environmentVariableKey') }}
                  </span>
                  <n-input
                    v-model:value="environmentVariable.key"
                    size="small"
                    :placeholder="t('config.environmentVariableKeyPlaceholder')"
                    :disabled="environmentVariable.source !== 'profile_new'"
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
                    :disabled="environmentVariable.source === 'system' || environmentVariable.source === 'profile_mask'"
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
                      :disabled="environmentVariable.source === 'system' || environmentVariable.source === 'profile_mask'"
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
                <div class="config-row-actions">
                  <template v-if="environmentVariable.source === 'system'">
                    <n-button size="small" secondary @click="overrideEnvironmentVariable(index)">
                      {{ t('config.overrideHere') }}
                    </n-button>
                    <n-button size="small" secondary type="warning" @click="maskEnvironmentVariable(index)">
                      {{ t('config.maskInProfile') }}
                    </n-button>
                  </template>
                  <n-button
                    v-else-if="environmentVariable.source === 'profile_override'"
                    size="small"
                    secondary
                    @click="restoreEnvironmentVariableInheritance(index)"
                  >
                    {{ t('config.restoreSystemValue') }}
                  </n-button>
                  <n-button
                    v-else-if="environmentVariable.source === 'profile_mask'"
                    size="small"
                    secondary
                    @click="restoreEnvironmentVariableInheritance(index)"
                  >
                    {{ t('config.restoreInheritance') }}
                  </n-button>
                  <n-button v-else size="small" type="error" quaternary @click="removeEnvironmentVariable(index)">
                    {{ t('config.remove') }}
                  </n-button>
                </div>
              </div>
            </div>
          </div>

          <div class="config-form__section config-scripts-section">
            <div class="config-form__section-title">{{ t('config.workerCustomScripts') }}</div>
            <n-grid :cols="isMobile ? 1 : 2" :x-gap="16" :y-gap="8">
              <n-gi>
                <div class="inheritable-field">
                  <div class="inheritable-field__header">
                    <strong>{{ t('config.workerPreScript') }}</strong>
                    <span class="source-label" :class="workerFormValue.worker_pre_script === null ? 'source-label--system' : 'source-label--profile_override'">
                      {{ workerFormValue.worker_pre_script === null ? t('config.sourceSystem') : t('config.sourceProfileOverride') }}
                    </span>
                  </div>
                  <label class="inheritance-toggle">
                    <n-switch :value="workerFormValue.worker_pre_script === null" @update:value="(value) => setScriptFollowsSystem('pre', value)" />
                    <span>{{ t('config.followSystem') }}</span>
                  </label>
                  <pre v-if="workerFormValue.worker_pre_script === null" class="inherited-preview">{{ sharedFormValue.pre_script || t('config.emptyValue') }}</pre>
                  <n-input
                    v-else
                    v-model:value="workerFormValue.worker_pre_script"
                    type="textarea"
                    :placeholder="t('config.workerPreScriptPlaceholder')"
                    :autosize="{ minRows: 5, maxRows: 12 }"
                    class="config-form__input config-form__textarea"
                  />
                  <span v-if="workerFormValue.worker_pre_script === ''" class="explicit-empty-note">{{ t('config.overriddenEmpty') }}</span>
                </div>
              </n-gi>
              <n-gi>
                <div class="inheritable-field">
                  <div class="inheritable-field__header">
                    <strong>{{ t('config.workerPostScript') }}</strong>
                    <span class="source-label" :class="workerFormValue.worker_post_script === null ? 'source-label--system' : 'source-label--profile_override'">
                      {{ workerFormValue.worker_post_script === null ? t('config.sourceSystem') : t('config.sourceProfileOverride') }}
                    </span>
                  </div>
                  <label class="inheritance-toggle">
                    <n-switch :value="workerFormValue.worker_post_script === null" @update:value="(value) => setScriptFollowsSystem('post', value)" />
                    <span>{{ t('config.followSystem') }}</span>
                  </label>
                  <pre v-if="workerFormValue.worker_post_script === null" class="inherited-preview">{{ sharedFormValue.post_script || t('config.emptyValue') }}</pre>
                  <n-input
                    v-else
                    v-model:value="workerFormValue.worker_post_script"
                    type="textarea"
                    :placeholder="t('config.workerPostScriptPlaceholder')"
                    :autosize="{ minRows: 5, maxRows: 12 }"
                    class="config-form__input config-form__textarea"
                  />
                  <span v-if="workerFormValue.worker_post_script === ''" class="explicit-empty-note">{{ t('config.overriddenEmpty') }}</span>
                </div>
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
                <div class="inheritable-field__toolbar">
                  <span class="source-label" :class="workerFormValue.default_execute_run_instruction_template === null ? 'source-label--system' : 'source-label--profile_override'">
                    {{ workerFormValue.default_execute_run_instruction_template === null ? t('config.sourceSystem') : t('config.sourceProfileOverride') }}
                  </span>
                  <label class="inheritance-toggle">
                    <n-switch :value="workerFormValue.default_execute_run_instruction_template === null" @update:value="(value) => setTemplateFollowsSystem('execute', value)" />
                    <span>{{ t('config.followSystem') }}</span>
                  </label>
                </div>
                <pre v-if="workerFormValue.default_execute_run_instruction_template === null" class="inherited-preview inherited-preview--template">{{ sharedFormValue.default_execute_run_instruction_template }}</pre>
                <RunInstructionTemplateEditor
                  v-else
                  :model-value="workerFormValue.default_execute_run_instruction_template ?? ''"
                  @update:model-value="(value) => { workerFormValue.default_execute_run_instruction_template = value }"
                  :fixed-rows="12"
                  :available-placeholders="builtIns?.execute.available_placeholders ?? []"
                  :known-placeholders="knownPromptPlaceholders"
                  @use-prompt-only="usePromptOnly('execute')"
                  @restore-default="restoreBuiltIn('execute')"
                />
              </n-tab-pane>
              <n-tab-pane name="plan" :tab="t('config.runInstructionAnalysisTab')">
                <div class="inheritable-field__toolbar">
                  <span class="source-label" :class="workerFormValue.default_plan_run_instruction_template === null ? 'source-label--system' : 'source-label--profile_override'">
                    {{ workerFormValue.default_plan_run_instruction_template === null ? t('config.sourceSystem') : t('config.sourceProfileOverride') }}
                  </span>
                  <label class="inheritance-toggle">
                    <n-switch :value="workerFormValue.default_plan_run_instruction_template === null" @update:value="(value) => setTemplateFollowsSystem('plan', value)" />
                    <span>{{ t('config.followSystem') }}</span>
                  </label>
                </div>
                <pre v-if="workerFormValue.default_plan_run_instruction_template === null" class="inherited-preview inherited-preview--template">{{ sharedFormValue.default_plan_run_instruction_template }}</pre>
                <RunInstructionTemplateEditor
                  v-else
                  :model-value="workerFormValue.default_plan_run_instruction_template ?? ''"
                  @update:model-value="(value) => { workerFormValue.default_plan_run_instruction_template = value }"
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
                <div class="inheritable-field__toolbar">
                  <span class="source-label" :class="workerFormValue.ci_auto_repair_run_instruction_template === null ? 'source-label--system' : 'source-label--profile_override'">
                    {{ workerFormValue.ci_auto_repair_run_instruction_template === null ? t('config.sourceSystem') : t('config.sourceProfileOverride') }}
                  </span>
                  <label class="inheritance-toggle">
                    <n-switch :value="workerFormValue.ci_auto_repair_run_instruction_template === null" @update:value="(value) => setTemplateFollowsSystem('ci_auto_repair', value)" />
                    <span>{{ t('config.followSystem') }}</span>
                  </label>
                </div>
                <pre v-if="workerFormValue.ci_auto_repair_run_instruction_template === null" class="inherited-preview inherited-preview--template">{{ sharedFormValue.ci_auto_repair_run_instruction_template }}</pre>
                <RunInstructionTemplateEditor
                  v-else
                  :model-value="workerFormValue.ci_auto_repair_run_instruction_template ?? ''"
                  @update:model-value="(value) => { workerFormValue.ci_auto_repair_run_instruction_template = value }"
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

          <div class="config-card-actions config-card-actions--safe-area">
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
  getWorkerSharedConfiguration,
  getRunInstructionTemplateBuiltIns,
  setDefaultWorkerProfile,
  testWorkerDockerConnection,
  updateConfig,
  updateWorkerSharedConfiguration,
  updateWorkerProfile,
  verifyWorkerProfileRuntime,
  type RunInstructionTemplateBuiltIns,
  type SkillSummary,
  type DockerConnectionTestResult,
  type WorkerProfile,
  type WorkerProfileEnvironmentVariable,
  type WorkerProfileEnvironmentVariableUpdate,
  type WorkerProfileMount,
  type WorkerProfilePayload,
  type WorkerProfileRuntimeVerification,
  type WorkerRuntimeReadiness,
  type WorkerSharedConfiguration,
  type WorkerSharedConfigurationPayload
} from '../../api'
import RunInstructionTemplateEditor from '../RunInstructionTemplateEditor.vue'

type WorkerFormValue = {
  name: string
  description: string | null
  enabled: boolean
  is_default: boolean
  image: string
  worker_kit_source: 'system' | 'profile'
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
  mounts: ProfileMountFormItem[]
  environment_variables: EnvironmentVariableFormItem[]
  default_skill_ids: number[]
  worker_workspace_retention_days: number
  worker_workspace_host_path: string
  worker_pre_script: string | null
  worker_post_script: string | null
  default_execute_run_instruction_template: string | null
  default_plan_run_instruction_template: string | null
  ci_auto_repair_run_instruction_template: string | null
  shared_revision: number
  runtime_verification: WorkerProfileRuntimeVerification
  runtime_readiness: WorkerRuntimeReadiness
}

type ProfileCollectionSource = 'system' | 'profile_override' | 'profile_mask' | 'profile_new'

type ProfileMountFormItem = WorkerProfileMount & {
  source: ProfileCollectionSource
  system_value?: WorkerProfileMount
}

type EnvironmentVariableFormItem = {
  id?: number
  key: string
  value: string
  is_secret: boolean
  value_configured: boolean
  source: ProfileCollectionSource
  system_value?: WorkerProfileEnvironmentVariable
}

type SharedFormValue = {
  revision: number
  runtime_mode: 'baked_image' | 'mounted_kit'
  worker_kit_version: string
  worker_kit_path: string
  mounts: WorkerProfileMount[]
  environment_variables: EnvironmentVariableFormItem[]
  pre_script: string
  post_script: string
  default_execute_run_instruction_template: string
  default_plan_run_instruction_template: string
  ci_auto_repair_run_instruction_template: string
  updated_at: string
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
const sharedSaving = ref(false)
const runtimeVerifying = ref(false)
const dockerTesting = ref(false)
const dockerTestResult = ref<DockerConnectionTestResult | null>(null)
const builtIns = ref<RunInstructionTemplateBuiltIns | null>(null)
const workerProfiles = ref<WorkerProfile[]>([])
const skills = ref<SkillSummary[]>([])
const selectedProfileId = ref<number | null>(null)
const editorMode = ref<'shared' | 'profile'>('profile')
const creatingWorkerProfile = ref(false)
const activeRunInstructionTab = ref<'execute' | 'plan' | 'ci_auto_repair'>('execute')
const sharedRunInstructionTab = ref<'execute' | 'plan' | 'ci_auto_repair'>('execute')
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
  worker_kit_source: 'system',
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
  worker_pre_script: null,
  worker_post_script: null,
  default_execute_run_instruction_template: null,
  default_plan_run_instruction_template: null,
  ci_auto_repair_run_instruction_template: null,
  shared_revision: 0,
  runtime_verification: emptyRuntimeVerification(),
  runtime_readiness: emptyRuntimeReadiness()
})

const lastLoadedWorker = ref<WorkerFormValue>(createEmptyWorkerFormValue())
const sharedFormValue = ref<SharedFormValue>(createEmptySharedFormValue())
const lastLoadedShared = ref<SharedFormValue>(createEmptySharedFormValue())
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
const isSharedDirty = computed(
  () => JSON.stringify(sharedFormValue.value) !== JSON.stringify(lastLoadedShared.value)
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
  sharedSaving.value ||
  runtimeVerifying.value ||
  workspaceSaving.value ||
  artifactSaving.value ||
  dockerTesting.value
)
const effectiveRuntimeMode = computed(() =>
  workerFormValue.value.worker_kit_source === 'system'
    ? sharedFormValue.value.runtime_mode
    : workerFormValue.value.runtime_mode
)
const effectiveWorkerKitVersion = computed(() =>
  workerFormValue.value.worker_kit_source === 'system'
    ? sharedFormValue.value.worker_kit_version
    : workerFormValue.value.worker_kit_version
)
const effectiveWorkerKitPath = computed(() =>
  workerFormValue.value.worker_kit_source === 'system'
    ? sharedFormValue.value.worker_kit_path
    : workerFormValue.value.worker_kit_path
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
  return [...mounts]
    .filter((mount) => mount.host_path && mount.container_path)
    .sort(compareMountContainerPaths)
    .map(({ host_path, container_path, mode }) => ({ host_path, container_path, mode }))
}

function toEnvironmentVariableFormItem(
  environmentVariable: WorkerProfileEnvironmentVariable,
  source: ProfileCollectionSource,
  systemValue?: WorkerProfileEnvironmentVariable
): EnvironmentVariableFormItem {
  const displayValue = source === 'profile_mask' && systemValue ? systemValue : environmentVariable
  return {
    id: environmentVariable.id,
    key: environmentVariable.key || '',
    value:
      displayValue.is_secret && displayValue.value_configured
        ? ''
        : (displayValue.value ?? ''),
    is_secret: Boolean(displayValue.is_secret),
    value_configured: Boolean(displayValue.value_configured || displayValue.value),
    source,
    system_value: systemValue ? { ...systemValue } : undefined
  }
}

function parseEnvironmentVariables(
  environmentVariables: WorkerProfileEnvironmentVariable[] | undefined,
  source: ProfileCollectionSource = 'profile_new'
): EnvironmentVariableFormItem[] {
  if (!Array.isArray(environmentVariables)) return []

  return [...environmentVariables]
    .sort(compareEnvironmentVariableKeys)
    .map((environmentVariable) => toEnvironmentVariableFormItem(environmentVariable, source))
}

function serializeSharedEnvironmentVariables(
  environmentVariables: EnvironmentVariableFormItem[]
): Array<Pick<WorkerProfileEnvironmentVariableUpdate, 'key' | 'value' | 'is_secret'>> {
  return environmentVariables
    .map((environmentVariable) => ({
      key: environmentVariable.key.trim(),
      value: environmentVariable.value,
      is_secret: environmentVariable.is_secret
    }))
    .filter((environmentVariable) => environmentVariable.key)
    .sort(compareEnvironmentVariableKeys)
}

function composeProfileMounts(
  sharedMounts: WorkerProfileMount[],
  overrides: WorkerProfileMount[],
  maskedPaths: string[]
): ProfileMountFormItem[] {
  const overrideByPath = new Map(overrides.map((mount) => [mount.container_path, mount]))
  const masked = new Set(maskedPaths)
  const rows: ProfileMountFormItem[] = sharedMounts.map((sharedMount) => {
    const override = overrideByPath.get(sharedMount.container_path)
    if (override) {
      overrideByPath.delete(sharedMount.container_path)
      return { ...override, source: 'profile_override', system_value: { ...sharedMount } }
    }
    if (masked.has(sharedMount.container_path)) {
      masked.delete(sharedMount.container_path)
      return { ...sharedMount, source: 'profile_mask', system_value: { ...sharedMount } }
    }
    return { ...sharedMount, source: 'system', system_value: { ...sharedMount } }
  })
  for (const override of overrideByPath.values()) {
    rows.push({ ...override, source: 'profile_new' })
  }
  for (const path of masked) {
    rows.push({ host_path: '', container_path: path, mode: 'ro', source: 'profile_mask' })
  }
  return rows.sort(compareMountContainerPaths)
}

function composeProfileEnvironmentVariables(
  sharedVariables: WorkerProfileEnvironmentVariable[],
  overrides: WorkerProfileEnvironmentVariable[]
): EnvironmentVariableFormItem[] {
  const overrideByKey = new Map(overrides.map((item) => [item.key, item]))
  const rows = sharedVariables.map((sharedVariable) => {
    const override = overrideByKey.get(sharedVariable.key)
    if (!override) {
      return toEnvironmentVariableFormItem(sharedVariable, 'system', sharedVariable)
    }
    overrideByKey.delete(sharedVariable.key)
    if (override.operation === 'mask') {
      return toEnvironmentVariableFormItem(override, 'profile_mask', sharedVariable)
    }
    return toEnvironmentVariableFormItem(override, 'profile_override', sharedVariable)
  })
  for (const override of overrideByKey.values()) {
    rows.push(
      toEnvironmentVariableFormItem(
        override,
        override.operation === 'mask' ? 'profile_mask' : 'profile_new'
      )
    )
  }
  return rows.sort(compareEnvironmentVariableKeys)
}

function serializeProfileEnvironmentVariables(
  environmentVariables: EnvironmentVariableFormItem[]
): WorkerProfileEnvironmentVariableUpdate[] {
  return environmentVariables
    .filter((item) => item.source !== 'system')
    .map((item) => ({
      id: item.id,
      key: item.key.trim(),
      value: item.source === 'profile_mask' ? null : item.value,
      is_secret: item.source === 'profile_mask' ? false : item.is_secret,
      operation: item.source === 'profile_mask' ? 'mask' as const : 'set' as const
    }))
    .filter((item) => item.key)
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
  shared: SharedFormValue,
  workerWorkspaceRetentionDays: number,
  workerWorkspaceHostPath = '/opt/codify-workspaces'
): WorkerFormValue {
  const profileMounts = profile?.overrides?.volume_mounts ?? profile?.volume_mounts ?? []
  const mountMasks =
    profile?.overrides?.masked_volume_mount_paths ?? profile?.volume_mount_masks ?? []
  const profileEnvironment =
    profile?.overrides?.environment_variables ?? profile?.environment_variables ?? []
  return {
    name: profile?.name ?? '',
    description: profile?.description ?? null,
    enabled: profile?.enabled ?? true,
    is_default: profile?.is_default ?? false,
    image: profile?.image ?? '',
    worker_kit_source: profile?.worker_kit_source ?? (profile?.overrides?.worker_kit ? 'profile' : 'system'),
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
    mounts: composeProfileMounts(shared.mounts, profileMounts, mountMasks),
    environment_variables: composeProfileEnvironmentVariables(
      shared.environment_variables.map((item) => ({
        id: item.id,
        key: item.key,
        value: item.value,
        is_secret: item.is_secret,
        value_configured: item.value_configured
      })),
      profileEnvironment
    ),
    default_skill_ids: [...(profile?.default_skill_ids ?? [])],
    worker_workspace_retention_days: workerWorkspaceRetentionDays,
    worker_workspace_host_path: workerWorkspaceHostPath,
    worker_pre_script: profile?.overrides?.pre_script ?? profile?.pre_script ?? null,
    worker_post_script: profile?.overrides?.post_script ?? profile?.post_script ?? null,
    default_execute_run_instruction_template:
      profile?.default_execute_run_instruction_template ?? null,
    default_plan_run_instruction_template:
      profile?.default_plan_run_instruction_template ?? null,
    ci_auto_repair_run_instruction_template:
      profile?.ci_auto_repair_run_instruction_template ?? null,
    shared_revision: profile?.shared_revision ?? shared.revision,
    runtime_verification: profile?.runtime_verification ?? emptyRuntimeVerification(),
    runtime_readiness: profile?.runtime_readiness ?? emptyRuntimeReadiness()
  }
}

function cloneWorkerFormValue(value: WorkerFormValue): WorkerFormValue {
  return {
    name: value.name,
    description: value.description,
    enabled: value.enabled,
    is_default: value.is_default,
    image: value.image,
    worker_kit_source: value.worker_kit_source,
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
    mounts: value.mounts.map((mount) => ({
      ...mount,
      system_value: mount.system_value ? { ...mount.system_value } : undefined
    })),
    environment_variables: value.environment_variables.map((environmentVariable) => ({
      ...environmentVariable,
      system_value: environmentVariable.system_value
        ? { ...environmentVariable.system_value }
        : undefined
    })),
    default_skill_ids: [...value.default_skill_ids],
    worker_workspace_retention_days: value.worker_workspace_retention_days,
    worker_workspace_host_path: value.worker_workspace_host_path,
    worker_pre_script: value.worker_pre_script,
    worker_post_script: value.worker_post_script,
    default_execute_run_instruction_template: value.default_execute_run_instruction_template,
    default_plan_run_instruction_template: value.default_plan_run_instruction_template,
    ci_auto_repair_run_instruction_template: value.ci_auto_repair_run_instruction_template,
    shared_revision: value.shared_revision,
    runtime_verification: { ...value.runtime_verification },
    runtime_readiness: { ...value.runtime_readiness }
  }
}

function mapSharedConfigurationToForm(shared: WorkerSharedConfiguration): SharedFormValue {
  return {
    revision: shared.revision,
    runtime_mode: shared.runtime_mode,
    worker_kit_version: shared.worker_kit_version ?? '',
    worker_kit_path: shared.worker_kit_path ?? '',
    mounts: parseMounts(shared.volume_mounts),
    environment_variables: parseEnvironmentVariables(shared.environment_variables),
    pre_script: shared.pre_script ?? '',
    post_script: shared.post_script ?? '',
    default_execute_run_instruction_template: shared.default_execute_run_instruction_template,
    default_plan_run_instruction_template: shared.default_plan_run_instruction_template,
    ci_auto_repair_run_instruction_template: shared.ci_auto_repair_run_instruction_template,
    updated_at: shared.updated_at
  }
}

function cloneSharedFormValue(value: SharedFormValue): SharedFormValue {
  return {
    ...value,
    mounts: value.mounts.map((mount) => ({ ...mount })),
    environment_variables: value.environment_variables.map((item) => ({ ...item }))
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
    const [configResult, builtInsResult, profilesResult, skillsResult, sharedResult] = await Promise.allSettled([
      getConfig(),
      getRunInstructionTemplateBuiltIns(),
      getAdminWorkerProfiles(),
      getAdminSkills(),
      getWorkerSharedConfiguration()
    ])
    if (configResult.status === 'rejected') throw configResult.reason
    if (profilesResult.status === 'rejected') throw profilesResult.reason
    if (skillsResult.status === 'rejected') throw skillsResult.reason
    if (sharedResult.status === 'rejected') throw sharedResult.reason
    const config = configResult.value
    if (builtInsResult.status === 'fulfilled') {
      builtIns.value = builtInsResult.value
    }
    sharedFormValue.value = mapSharedConfigurationToForm(sharedResult.value)
    lastLoadedShared.value = cloneSharedFormValue(sharedFormValue.value)
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
      sharedFormValue.value,
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
    mode: 'ro',
    source: 'profile_new'
  })
}

function addEnvironmentVariable() {
  workerFormValue.value.environment_variables.unshift({
    key: '',
    value: '',
    is_secret: false,
    value_configured: false,
    source: 'profile_new'
  })
}

function addSharedMount() {
  sharedFormValue.value.mounts.unshift({ host_path: '', container_path: '', mode: 'ro' })
}

function removeSharedMount(index: number) {
  sharedFormValue.value.mounts.splice(index, 1)
}

function addSharedEnvironmentVariable() {
  sharedFormValue.value.environment_variables.unshift({
    key: '',
    value: '',
    is_secret: false,
    value_configured: false,
    source: 'profile_new'
  })
}

function removeSharedEnvironmentVariable(index: number) {
  sharedFormValue.value.environment_variables.splice(index, 1)
}

function emptyRuntimeVerification(): WorkerProfileRuntimeVerification {
  return {
    verified_at: null,
    verified_runtime_configuration_digest: null,
    matches_current_input: false
  }
}

function emptyRuntimeReadiness(): WorkerRuntimeReadiness {
  return { status: 'unknown', checked_at: null, ready_until: null }
}

function createEmptySharedFormValue(): SharedFormValue {
  return {
    revision: 0,
    runtime_mode: 'baked_image',
    worker_kit_version: '',
    worker_kit_path: '',
    mounts: [],
    environment_variables: [],
    pre_script: '',
    post_script: '',
    default_execute_run_instruction_template: '',
    default_plan_run_instruction_template: '',
    ci_auto_repair_run_instruction_template: '',
    updated_at: ''
  }
}

function createEmptyWorkerFormValue(): WorkerFormValue {
  return {
    name: '',
    description: null,
    enabled: true,
    is_default: false,
    image: '',
    worker_kit_source: 'system',
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
    worker_pre_script: null,
    worker_post_script: null,
    default_execute_run_instruction_template: null,
    default_plan_run_instruction_template: null,
    ci_auto_repair_run_instruction_template: null,
    shared_revision: 0,
    runtime_verification: emptyRuntimeVerification(),
    runtime_readiness: emptyRuntimeReadiness()
  }
}

function removeMount(index: number) {
  workerFormValue.value.mounts.splice(index, 1)
}

function overrideMount(index: number) {
  const mount = workerFormValue.value.mounts[index]
  if (!mount || mount.source !== 'system') return
  mount.source = 'profile_override'
}

function maskMount(index: number) {
  const mount = workerFormValue.value.mounts[index]
  if (!mount || mount.source !== 'system') return
  mount.source = 'profile_mask'
}

function restoreMountInheritance(index: number) {
  const mount = workerFormValue.value.mounts[index]
  if (!mount) return
  if (!mount.system_value) {
    workerFormValue.value.mounts.splice(index, 1)
    return
  }
  workerFormValue.value.mounts.splice(index, 1, {
    ...mount.system_value,
    source: 'system',
    system_value: { ...mount.system_value }
  })
}

function removeEnvironmentVariable(index: number) {
  workerFormValue.value.environment_variables.splice(index, 1)
}

function overrideEnvironmentVariable(index: number) {
  const variable = workerFormValue.value.environment_variables[index]
  if (!variable || variable.source !== 'system') return
  variable.source = 'profile_override'
  variable.id = undefined
  if (variable.is_secret) {
    variable.value = ''
    variable.value_configured = false
  }
}

function maskEnvironmentVariable(index: number) {
  const variable = workerFormValue.value.environment_variables[index]
  if (!variable || variable.source !== 'system') return
  variable.source = 'profile_mask'
  variable.id = undefined
}

function restoreEnvironmentVariableInheritance(index: number) {
  const variable = workerFormValue.value.environment_variables[index]
  if (!variable) return
  if (!variable.system_value) {
    workerFormValue.value.environment_variables.splice(index, 1)
    return
  }
  workerFormValue.value.environment_variables.splice(
    index,
    1,
    toEnvironmentVariableFormItem(variable.system_value, 'system', variable.system_value)
  )
}

function setWorkerKitFollowsSystem(followsSystem: boolean) {
  workerFormValue.value.worker_kit_source = followsSystem ? 'system' : 'profile'
  if (!followsSystem) {
    workerFormValue.value.runtime_mode = sharedFormValue.value.runtime_mode
    workerFormValue.value.worker_kit_version = sharedFormValue.value.worker_kit_version
    workerFormValue.value.worker_kit_path = sharedFormValue.value.worker_kit_path
  }
}

function setScriptFollowsSystem(kind: 'pre' | 'post', followsSystem: boolean) {
  if (kind === 'pre') {
    workerFormValue.value.worker_pre_script = followsSystem
      ? null
      : sharedFormValue.value.pre_script
    return
  }
  workerFormValue.value.worker_post_script = followsSystem
    ? null
    : sharedFormValue.value.post_script
}

function setTemplateFollowsSystem(
  kind: 'execute' | 'plan' | 'ci_auto_repair',
  followsSystem: boolean
) {
  if (kind === 'execute') {
    workerFormValue.value.default_execute_run_instruction_template = followsSystem
      ? null
      : sharedFormValue.value.default_execute_run_instruction_template
  } else if (kind === 'plan') {
    workerFormValue.value.default_plan_run_instruction_template = followsSystem
      ? null
      : sharedFormValue.value.default_plan_run_instruction_template
  } else {
    workerFormValue.value.ci_auto_repair_run_instruction_template = followsSystem
      ? null
      : sharedFormValue.value.ci_auto_repair_run_instruction_template
  }
}

function sourceLabel(source: ProfileCollectionSource): string {
  if (source === 'system') return t('config.sourceSystem')
  if (source === 'profile_mask') return t('config.sourceProfileMask')
  if (source === 'profile_override') return t('config.sourceProfileOverride')
  return t('config.sourceProfileAdded')
}

function readinessLabel(status?: WorkerRuntimeReadiness['status']): string {
  if (status === 'ready') return t('config.runtimeReady')
  if (status === 'unavailable') return t('config.runtimeUnavailable')
  return t('config.runtimeUnknown')
}

function readinessTagType(
  status?: WorkerRuntimeReadiness['status']
): 'success' | 'warning' | 'error' {
  if (status === 'ready') return 'success'
  if (status === 'unavailable') return 'error'
  return 'warning'
}

function runtimeModeLabel(mode: 'baked_image' | 'mounted_kit'): string {
  return mode === 'mounted_kit'
    ? t('config.workerRuntimeModeMountedKit')
    : t('config.workerRuntimeModeBakedImage')
}

function formatTimestamp(value: string): string {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString()
}

function usePromptOnly(mode: 'execute' | 'plan') {
  if (mode === 'execute') {
    workerFormValue.value.default_execute_run_instruction_template = '{{user_prompt}}'
    return
  }
  workerFormValue.value.default_plan_run_instruction_template = '{{user_prompt}}'
}

function useSharedPromptOnly(mode: 'execute' | 'plan') {
  if (mode === 'execute') {
    sharedFormValue.value.default_execute_run_instruction_template = '{{user_prompt}}'
    return
  }
  sharedFormValue.value.default_plan_run_instruction_template = '{{user_prompt}}'
}

function selectProfile(profileId: number) {
  const profile = workerProfiles.value.find((item) => item.id === profileId)
  if (!profile) return
  editorMode.value = 'profile'
  creatingWorkerProfile.value = false
  selectedProfileId.value = profileId
  workerFormValue.value = mapProfileToWorkerFormValue(
    profile,
    sharedFormValue.value,
    workerFormValue.value.worker_workspace_retention_days,
    workerFormValue.value.worker_workspace_host_path
  )
  lastLoadedWorker.value = cloneWorkerFormValue(workerFormValue.value)
}

function selectSharedConfiguration() {
  editorMode.value = 'shared'
}

function buildWorkerProfilePayload(): WorkerProfilePayload {
  return {
    name: workerFormValue.value.name,
    description: workerFormValue.value.description,
    enabled: workerFormValue.value.enabled,
    image: workerFormValue.value.image,
    worker_kit_source: workerFormValue.value.worker_kit_source,
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
    volume_mounts: serializeMounts(
      workerFormValue.value.mounts.filter((mount) =>
        mount.source === 'profile_override' || mount.source === 'profile_new'
      )
    ),
    volume_mount_masks: workerFormValue.value.mounts
      .filter((mount) => mount.source === 'profile_mask')
      .map((mount) => mount.container_path)
      .filter(Boolean)
      .sort(),
    environment_variables: serializeProfileEnvironmentVariables(
      workerFormValue.value.environment_variables
    ),
    default_skill_ids:
      effectiveRuntimeMode.value === 'mounted_kit'
        ? [...workerFormValue.value.default_skill_ids]
        : [],
    pre_script: workerFormValue.value.worker_pre_script,
    post_script: workerFormValue.value.worker_post_script,
    enabled_harnesses: [...workerFormValue.value.enabled_harnesses],
    default_harness_key: workerFormValue.value.default_harness_key,
    harness_constraints: { ...workerFormValue.value.harness_constraints },
    default_execute_run_instruction_template:
      workerFormValue.value.default_execute_run_instruction_template,
    default_plan_run_instruction_template: workerFormValue.value.default_plan_run_instruction_template,
    ci_auto_repair_run_instruction_template: workerFormValue.value.ci_auto_repair_run_instruction_template,
    expected_shared_revision: workerFormValue.value.shared_revision
  }
}

function buildSharedConfigurationPayload(): WorkerSharedConfigurationPayload {
  return {
    expected_revision: sharedFormValue.value.revision,
    runtime_mode: sharedFormValue.value.runtime_mode,
    worker_kit_version:
      sharedFormValue.value.runtime_mode === 'mounted_kit'
        ? sharedFormValue.value.worker_kit_version
        : null,
    worker_kit_path:
      sharedFormValue.value.runtime_mode === 'mounted_kit'
        ? sharedFormValue.value.worker_kit_path
        : null,
    volume_mounts: serializeMounts(sharedFormValue.value.mounts),
    environment_variables: serializeSharedEnvironmentVariables(
      sharedFormValue.value.environment_variables
    ),
    pre_script: sharedFormValue.value.pre_script,
    post_script: sharedFormValue.value.post_script,
    default_execute_run_instruction_template:
      sharedFormValue.value.default_execute_run_instruction_template,
    default_plan_run_instruction_template:
      sharedFormValue.value.default_plan_run_instruction_template,
    ci_auto_repair_run_instruction_template:
      sharedFormValue.value.ci_auto_repair_run_instruction_template
  }
}

async function refreshAdminProfiles() {
  const profiles = await getAdminWorkerProfiles()
  workerProfiles.value = profiles
  const selected =
    profiles.find((profile) => profile.id === selectedProfileId.value) ??
    profiles.find((profile) => profile.is_default) ??
    profiles[0] ??
    null
  selectedProfileId.value = selected?.id ?? null
  workerFormValue.value = mapProfileToWorkerFormValue(
    selected,
    sharedFormValue.value,
    workerFormValue.value.worker_workspace_retention_days,
    workerFormValue.value.worker_workspace_host_path
  )
  lastLoadedWorker.value = cloneWorkerFormValue(workerFormValue.value)
}

function isSharedRevisionConflict(error: any): boolean {
  return error?.response?.status === 409 &&
    error?.response?.data?.detail === 'shared_configuration_changed'
}

async function handleSaveSharedConfiguration() {
  sharedSaving.value = true
  try {
    const saved = await updateWorkerSharedConfiguration(buildSharedConfigurationPayload())
    sharedFormValue.value = mapSharedConfigurationToForm(saved)
    lastLoadedShared.value = cloneSharedFormValue(sharedFormValue.value)
    await refreshAdminProfiles()
    message.success(t('config.sharedConfigurationSaved'))
  } catch (error: any) {
    if (isSharedRevisionConflict(error)) {
      message.error(t('config.sharedConfigurationChanged'))
    } else {
      message.error(error?.response?.data?.detail || t('config.saveError'))
    }
  } finally {
    sharedSaving.value = false
  }
}

function resetSharedConfiguration() {
  sharedFormValue.value = cloneSharedFormValue(lastLoadedShared.value)
}

async function handleVerifyProfileRuntime() {
  if (selectedProfileId.value === null) return
  runtimeVerifying.value = true
  try {
    await verifyWorkerProfileRuntime(selectedProfileId.value)
    await refreshAdminProfiles()
    message.success(t('config.runtimeVerificationSucceeded'))
  } catch (error: any) {
    const detail = error?.response?.data?.detail
    if (detail && typeof detail === 'object' && detail.code === 'worker_runtime_unavailable') {
      workerFormValue.value.runtime_readiness = {
        status: 'unavailable',
        failure_code: detail.failure_code ?? null,
        failure_message: detail.failure_message ?? detail.message ?? null,
        checked_at: detail.checked_at ?? null,
        ready_until: null
      }
      const loadedProfile = workerProfiles.value.find(
        (profile) => profile.id === selectedProfileId.value
      )
      if (loadedProfile) {
        loadedProfile.runtime_readiness = { ...workerFormValue.value.runtime_readiness }
      }
      message.error(detail.failure_message || detail.message)
    } else {
      message.error(
        typeof detail === 'string'
          ? detail
          : detail?.message || t('config.runtimeVerificationFailed')
      )
    }
  } finally {
    runtimeVerifying.value = false
  }
}

function hasInheritedCreateTemplates(payload: WorkerProfilePayload): boolean {
  return payload.default_execute_run_instruction_template === null ||
    payload.default_plan_run_instruction_template === null ||
    payload.ci_auto_repair_run_instruction_template === null
}

async function createProfileWithInheritedTemplates(
  payload: WorkerProfilePayload
): Promise<WorkerProfile> {
  if (!hasInheritedCreateTemplates(payload)) {
    return createWorkerProfile(payload)
  }

  // The create contract currently requires concrete template strings. Create a
  // disabled, unassigned Profile with the visible shared values, then normalize
  // inherited fields through the nullable PATCH contract before it can be used.
  const bootstrapProfile = await createWorkerProfile({
    ...payload,
    enabled: false,
    default_execute_run_instruction_template:
      payload.default_execute_run_instruction_template ??
      sharedFormValue.value.default_execute_run_instruction_template,
    default_plan_run_instruction_template:
      payload.default_plan_run_instruction_template ??
      sharedFormValue.value.default_plan_run_instruction_template,
    ci_auto_repair_run_instruction_template:
      payload.ci_auto_repair_run_instruction_template ??
      sharedFormValue.value.ci_auto_repair_run_instruction_template
  })

  try {
    return await updateWorkerProfile(bootstrapProfile.id, payload)
  } catch (error) {
    // The bootstrap row is disabled and has no assignments. Best-effort cleanup
    // keeps a failed revision check from leaving a misleading partial Profile.
    try {
      await deleteWorkerProfile(bootstrapProfile.id)
    } catch {
      await refreshAdminProfiles().catch(() => undefined)
    }
    throw error
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
    const payload = buildWorkerProfilePayload()
    const savedProfile = creatingWorkerProfile.value
      ? await createProfileWithInheritedTemplates(payload)
      : await updateWorkerProfile(
          selectedProfileId.value as number,
          payload
        )
    replaceLoadedProfile(savedProfile)
    selectedProfileId.value = savedProfile.id
    creatingWorkerProfile.value = false
    workerFormValue.value = mapProfileToWorkerFormValue(
      savedProfile,
      sharedFormValue.value,
      workerFormValue.value.worker_workspace_retention_days,
      workerFormValue.value.worker_workspace_host_path
    )
    lastLoadedWorker.value = cloneWorkerFormValue(workerFormValue.value)
    message.success(t('config.saved'))
  } catch (error: any) {
    if (isSharedRevisionConflict(error)) {
      message.error(t('config.sharedConfigurationChanged'))
    } else {
      message.error(error?.response?.data?.detail || t('config.saveError'))
    }
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
  draft.runtime_mode = sharedFormValue.value.runtime_mode
  draft.worker_kit_version = sharedFormValue.value.worker_kit_version
  draft.worker_kit_path = sharedFormValue.value.worker_kit_path
  draft.shared_revision = sharedFormValue.value.revision
  draft.mounts = composeProfileMounts(sharedFormValue.value.mounts, [], [])
  draft.environment_variables = composeProfileEnvironmentVariables(
    sharedFormValue.value.environment_variables.map((item) => ({
      id: item.id,
      key: item.key,
      value: item.value,
      is_secret: item.is_secret,
      value_configured: item.value_configured
    })),
    []
  )
  draft.worker_workspace_retention_days = workerFormValue.value.worker_workspace_retention_days
  draft.worker_workspace_host_path = workerFormValue.value.worker_workspace_host_path

  editorMode.value = 'profile'
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
      sharedFormValue.value,
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

function restoreSharedBuiltIn(kind: keyof RunInstructionTemplateBuiltIns) {
  if (!builtIns.value) return
  if (kind === 'execute') {
    sharedFormValue.value.default_execute_run_instruction_template = builtIns.value.execute.content
  } else if (kind === 'plan') {
    sharedFormValue.value.default_plan_run_instruction_template = builtIns.value.plan.content
  } else {
    sharedFormValue.value.ci_auto_repair_run_instruction_template =
      builtIns.value.ci_auto_repair.content
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

.worker-shared-entry {
  display: grid;
  gap: 4px;
  width: 100%;
  min-width: 0;
  min-height: 84px;
  padding: 12px;
  color: rgba(15, 23, 42, 0.82);
  text-align: left;
  cursor: pointer;
  background: rgba(2, 132, 199, 0.045);
  border: 1px solid rgba(2, 132, 199, 0.18);
  border-radius: 10px;
}

.worker-shared-entry--active {
  background: rgba(2, 132, 199, 0.09);
  border-color: rgba(2, 132, 199, 0.52);
  box-shadow: 0 0 0 2px rgba(2, 132, 199, 0.08);
}

.worker-shared-entry__eyebrow,
.worker-editor-heading__eyebrow {
  color: #0369a1;
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.worker-shared-entry small {
  color: rgba(15, 23, 42, 0.54);
  line-height: 1.4;
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

.worker-editor-heading {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}

.worker-editor-heading__copy {
  display: grid;
  gap: 5px;
  min-width: 0;
}

.worker-editor-heading__copy p,
.worker-editor-heading__revision {
  margin: 0;
  color: rgba(15, 23, 42, 0.54);
  font-size: 12px;
  line-height: 1.5;
}

.worker-shared-meta {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: flex-end;
  gap: 8px;
  color: rgba(15, 23, 42, 0.52);
  font-size: 12px;
}

.worker-runtime-status {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px 16px;
  padding: 12px;
  margin-bottom: 8px;
  background: rgba(15, 23, 42, 0.025);
  border: 1px solid rgba(15, 23, 42, 0.08);
  border-radius: 10px;
}

.worker-runtime-status__item {
  display: inline-flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  color: rgba(15, 23, 42, 0.6);
  font-size: 12px;
}

.worker-runtime-status__details {
  display: flex;
  flex: 1 1 320px;
  flex-wrap: wrap;
  gap: 6px 12px;
  min-width: 0;
  color: rgba(15, 23, 42, 0.56);
  font-size: 12px;
}

.worker-runtime-status__details code,
.inherited-value-card code {
  min-width: 0;
  overflow-wrap: anywhere;
}

.worker-runtime-status__error {
  flex-basis: 100%;
  color: #b42318;
  overflow-wrap: anywhere;
}

.inherited-value-card {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px 12px;
  min-width: 0;
  padding: 10px 12px;
  background: rgba(2, 132, 199, 0.045);
  border: 1px solid rgba(2, 132, 199, 0.14);
  border-radius: 8px;
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
  overflow-x: auto;
  overflow-y: hidden;
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
  grid-template-columns: 112px minmax(150px, 1fr) minmax(150px, 1fr) 110px minmax(178px, auto);
}

.config-compact-table--environment .config-compact-table__header,
.config-compact-row--environment {
  grid-template-columns: 112px minmax(130px, 0.8fr) 108px minmax(190px, 1.2fr) minmax(178px, auto);
}

.config-compact-table--shared.config-compact-table--mounts .config-compact-table__header,
.config-compact-row--shared.config-compact-row--mount {
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr) 130px 76px;
}

.config-compact-table--shared.config-compact-table--environment .config-compact-table__header,
.config-compact-row--shared.config-compact-row--environment {
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

.config-source-cell {
  min-width: 0;
}

.source-label {
  display: inline-flex;
  align-items: center;
  min-height: 24px;
  max-width: 100%;
  padding: 3px 7px;
  color: #475569;
  font-size: 11px;
  font-weight: 650;
  line-height: 1.25;
  overflow-wrap: anywhere;
  background: rgba(100, 116, 139, 0.09);
  border-radius: 999px;
}

.source-label--system {
  color: #0369a1;
  background: rgba(2, 132, 199, 0.1);
}

.source-label--profile_override {
  color: #166534;
  background: rgba(22, 163, 74, 0.1);
}

.source-label--profile_mask {
  color: #92400e;
  background: rgba(217, 119, 6, 0.1);
}

.config-compact-row--profile_mask {
  color: rgba(15, 23, 42, 0.52);
  background: rgba(148, 163, 184, 0.055);
}

.config-row-actions {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 6px;
  min-width: 0;
}

.config-row-actions :deep(.n-button) {
  min-height: 36px;
  white-space: normal;
}

.inheritable-field {
  display: grid;
  gap: 10px;
  min-width: 0;
  height: 100%;
  padding: 12px;
  border: 1px solid rgba(15, 23, 42, 0.08);
  border-radius: 10px;
}

.inheritable-field__header,
.inheritable-field__toolbar,
.inheritance-toggle {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}

.inheritable-field__header,
.inheritable-field__toolbar {
  justify-content: space-between;
}

.inheritable-field__toolbar {
  margin-bottom: 10px;
}

.inheritance-toggle {
  min-height: 36px;
  color: rgba(15, 23, 42, 0.64);
  font-size: 12px;
}

.inherited-preview {
  min-width: 0;
  min-height: 86px;
  max-height: 240px;
  padding: 10px;
  margin: 0;
  overflow: auto;
  color: rgba(15, 23, 42, 0.65);
  font: 12px/1.55 ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  background: rgba(2, 132, 199, 0.035);
  border-radius: 7px;
}

.inherited-preview--template {
  max-height: 320px;
}

.explicit-empty-note {
  color: #92400e;
  font-size: 12px;
}

.config-card-actions--safe-area {
  padding-bottom: max(16px, env(safe-area-inset-bottom));
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

  .worker-editor-heading {
    display: grid;
  }

  .worker-shared-meta,
  .config-row-actions {
    justify-content: flex-start;
  }

  .worker-runtime-status {
    align-items: flex-start;
  }

  .config-row-actions :deep(.n-button) {
    min-height: 44px;
  }
}
</style>
