<template>
  <!-- AI provider -->
  <div v-if="hasProviderSummary" class="metadata-row">
    <span class="metadata-label">
      <n-icon size="14" class="metadata-label-icon"><ServerOutline /></n-icon>
      {{ t('taskView.provider') }}
    </span>
    <span class="metadata-value">
      <n-popover
        :show="providerPopoverVisible"
        trigger="click"
        :placement="providerPopoverLayout.placement"
        :width="runtimePopoverWidth"
        scrollable
        :style="{ maxHeight: `${providerPopoverLayout.maxHeight}px` }"
        @update:show="handleProviderPopoverShow"
      >
        <template #trigger>
          <button
            ref="providerTriggerRef"
            type="button"
            class="metadata-summary-trigger metadata-summary-trigger--provider"
            :aria-label="t('taskView.openProviderSummary')"
          >
            <span class="metadata-summary-trigger__body">
              <span class="metadata-summary-trigger__label" :title="providerDisplayName">
                {{ providerDisplayName }}
              </span>
              <span v-if="task.model_name" class="metadata-summary-trigger__meta" :title="task.model_name">
                {{ task.model_name }}
              </span>
            </span>
            <n-icon size="14" class="metadata-summary-trigger__arrow"><ChevronForwardOutline /></n-icon>
          </button>
        </template>

        <div class="metadata-summary-popover" data-testid="provider-summary-popover">
          <div class="metadata-summary-popover__heading">
            <div class="metadata-summary-popover__title-wrap">
              <n-icon size="16" class="metadata-summary-popover__icon"><ServerOutline /></n-icon>
              <span class="metadata-summary-popover__title">{{ providerSummaryDisplayName }}</span>
            </div>
            <span class="metadata-summary-popover__tag-list">
              <n-tag v-if="providerSummary" size="tiny" :bordered="false" :type="providerSourceTagType">
                {{ providerSourceLabel }}
              </n-tag>
              <n-tag v-if="providerSummaryId" size="small" :bordered="false">
                #{{ providerSummaryId }}
              </n-tag>
            </span>
          </div>

          <div v-if="providerSummaryState === 'loading'" class="metadata-summary-popover__state">
            <n-spin :size="18" />
            <span>{{ t('taskView.runtimeSummaryLoading') }}</span>
          </div>
          <div v-else-if="providerSummaryState === 'error'" class="metadata-summary-popover__state metadata-summary-popover__state--error">
            <span>{{ t('taskView.providerSummaryLoadFailed') }}</span>
            <n-button text size="tiny" type="primary" @click.stop="retryProviderSummary">
              {{ t('common.retry') }}
            </n-button>
          </div>
          <template v-else-if="providerSummary">
            <div v-if="!providerSummary.provider_config_available" class="metadata-summary-popover__notice">
              {{ t('taskView.providerConfigUnavailable') }}
            </div>

            <dl class="metadata-summary-popover__list">
              <div v-if="providerSummary.provider_config_available" class="metadata-summary-popover__item">
                <dt>{{ t('taskView.providerConfiguredModel') }}</dt>
                <dd :class="{ 'metadata-summary-popover__muted': !providerSummary.configured_model }">
                  {{ providerSummary.configured_model || t('common.notAvailable') }}
                </dd>
              </div>
              <div class="metadata-summary-popover__item">
                <dt>{{ t('taskView.providerActualModel') }}</dt>
                <dd :class="{ 'metadata-summary-popover__muted': !providerSummary.actual_model }">
                  {{ providerSummary.actual_model || t('taskView.providerModelPending') }}
                </dd>
              </div>
              <div v-if="providerSummary.provider_config_available" class="metadata-summary-popover__item">
                <dt>{{ t('taskView.providerBaseUrl') }}</dt>
                <dd class="metadata-summary-popover__mono" :class="{ 'metadata-summary-popover__muted': !providerSummary.base_url }">
                  {{ providerSummary.base_url || t('common.notAvailable') }}
                </dd>
              </div>
              <div v-if="providerSummary.provider_config_available" class="metadata-summary-popover__item">
                <dt>{{ t('taskView.providerMaxTurns') }}</dt>
                <dd :class="{ 'metadata-summary-popover__muted': providerSummary.max_turns == null }">
                  {{ providerSummary.max_turns ?? t('common.notAvailable') }}
                </dd>
              </div>
              <div v-if="providerSummary.provider_config_available" class="metadata-summary-popover__item">
                <dt>{{ t('taskView.providerApiKey') }}</dt>
                <dd>
                  <n-tag size="tiny" :bordered="false" :type="providerSummary.api_key_configured ? 'success' : 'default'">
                    {{ providerSummary.api_key_configured ? t('taskView.runtimeConfigured') : t('taskView.runtimeNotConfigured') }}
                  </n-tag>
                </dd>
              </div>
              <div v-if="providerSummary.configuration_captured_at" class="metadata-summary-popover__item">
                <dt>{{ t('taskView.providerConfigCapturedAt') }}</dt>
                <dd>{{ formatDate(providerSummary.configuration_captured_at) }}</dd>
              </div>
            </dl>

            <section v-if="providerSummary.provider_config_available" class="metadata-summary-popover__section">
              <div class="metadata-summary-popover__section-title">
                {{ t('taskView.providerSystemPrompt') }}
              </div>
              <pre v-if="providerSummary.system_prompt" class="metadata-summary-popover__prompt">{{ providerSummary.system_prompt }}</pre>
              <div v-else class="metadata-summary-popover__empty">
                {{ t('taskView.providerSystemPromptEmpty') }}
              </div>
            </section>

            <p v-if="providerSummary.provider_config_available" class="metadata-summary-popover__hint">
              {{ providerSummaryHint }}
            </p>
          </template>
        </div>
      </n-popover>
    </span>
  </div>

  <!-- Worker -->
  <div v-if="hasWorkerSummary" class="metadata-row">
    <span class="metadata-label">
      <n-icon size="14" class="metadata-label-icon"><ServerOutline /></n-icon>
      {{ t('taskView.workerProfile') }}
    </span>
    <span class="metadata-value">
      <n-popover
        :show="workerPopoverVisible"
        trigger="click"
        :placement="workerPopoverLayout.placement"
        :width="runtimePopoverWidth"
        scrollable
        :style="{ maxHeight: `${workerPopoverLayout.maxHeight}px` }"
        @update:show="handleWorkerPopoverShow"
      >
        <template #trigger>
          <button
            ref="workerTriggerRef"
            type="button"
            class="metadata-summary-trigger metadata-summary-trigger--worker"
            :aria-label="t('taskView.openWorkerSummary')"
          >
            <span class="metadata-summary-trigger__body">
              <span class="metadata-summary-trigger__label" :title="workerDisplayName">
                {{ workerDisplayName }}
              </span>
              <span v-if="task.worker_image" class="metadata-summary-trigger__meta" :title="task.worker_image">
                {{ task.worker_image }}
              </span>
            </span>
            <n-icon size="14" class="metadata-summary-trigger__arrow"><ChevronForwardOutline /></n-icon>
          </button>
        </template>

        <div class="metadata-summary-popover" data-testid="worker-summary-popover">
          <div class="metadata-summary-popover__heading">
            <div class="metadata-summary-popover__title-wrap">
              <n-icon size="16" class="metadata-summary-popover__icon"><ServerOutline /></n-icon>
              <span class="metadata-summary-popover__title">{{ workerSummaryDisplayName }}</span>
            </div>
            <n-tag v-if="workerSummaryId" size="small" :bordered="false">
              #{{ workerSummaryId }}
            </n-tag>
          </div>

          <div v-if="workerSummaryState === 'loading'" class="metadata-summary-popover__state">
            <n-spin :size="18" />
            <span>{{ t('taskView.runtimeSummaryLoading') }}</span>
          </div>
          <div v-else-if="workerSummaryState === 'error'" class="metadata-summary-popover__state metadata-summary-popover__state--error">
            <span>{{ t('taskView.workerSummaryLoadFailed') }}</span>
            <n-button text size="tiny" type="primary" @click.stop="retryWorkerSummary">
              {{ t('common.retry') }}
            </n-button>
          </div>
          <template v-else-if="workerSummary">
            <div v-if="!workerSummary.snapshot_available" class="metadata-summary-popover__notice">
              {{ t('taskView.workerSnapshotUnavailable') }}
            </div>

            <template v-else>
              <dl class="metadata-summary-popover__list">
                <div class="metadata-summary-popover__item">
                  <dt>{{ t('taskView.workerImage') }}</dt>
                  <dd class="metadata-summary-popover__mono">{{ workerSummary.image }}</dd>
                </div>
                <div class="metadata-summary-popover__item">
                  <dt>{{ t('taskView.workerRuntimeMode') }}</dt>
                  <dd>{{ workerRuntimeModeLabel }}</dd>
                </div>
                <div v-if="workerSummary.runtime_mode === 'mounted_kit'" class="metadata-summary-popover__item">
                  <dt>{{ t('taskView.workerKitVersion') }}</dt>
                  <dd class="metadata-summary-popover__mono">{{ workerSummary.worker_kit_version }}</dd>
                </div>
                <div v-if="workerSummary.runtime_mode === 'mounted_kit'" class="metadata-summary-popover__item">
                  <dt>{{ t('taskView.workerKitPath') }}</dt>
                  <dd class="metadata-summary-popover__mono">{{ workerSummary.worker_kit_path }}</dd>
                </div>
                <div class="metadata-summary-popover__item">
                  <dt>{{ t('taskView.workerCodegraph') }}</dt>
                  <dd>
                    <n-tag size="tiny" :bordered="false" :type="workerSummary.codegraph_enabled ? 'success' : 'default'">
                      {{ workerSummary.codegraph_enabled ? t('common.enabled') : t('common.disabled') }}
                    </n-tag>
                  </dd>
                </div>
                <div class="metadata-summary-popover__item">
                  <dt>{{ t('taskView.workerCustomScripts') }}</dt>
                  <dd class="metadata-summary-popover__tag-list">
                    <n-tag size="tiny" :bordered="false" :type="workerSummary.pre_script_configured ? 'success' : 'default'">
                      {{ t('taskView.workerPreScript') }} · {{ workerSummary.pre_script_configured ? t('taskView.runtimeConfigured') : t('taskView.runtimeNotConfigured') }}
                    </n-tag>
                    <n-tag size="tiny" :bordered="false" :type="workerSummary.post_script_configured ? 'success' : 'default'">
                      {{ t('taskView.workerPostScript') }} · {{ workerSummary.post_script_configured ? t('taskView.runtimeConfigured') : t('taskView.runtimeNotConfigured') }}
                    </n-tag>
                  </dd>
                </div>
                <div v-if="workerSummary.snapshot_created_at" class="metadata-summary-popover__item">
                  <dt>{{ t('taskView.workerSnapshot') }}</dt>
                  <dd>{{ formatDate(workerSummary.snapshot_created_at) }}</dd>
                </div>
              </dl>

              <section class="metadata-summary-popover__section">
                <div class="metadata-summary-popover__section-title">
                  <span>{{ t('taskView.workerSkills') }}</span>
                  <span class="metadata-summary-popover__count">{{ (workerSummary.skills ?? []).length }}</span>
                </div>
                <div v-if="(workerSummary.skills ?? []).length" class="metadata-summary-popover__entries metadata-summary-popover__entries--compact">
                  <div v-for="skill in workerSummary.skills ?? []" :key="skill.name" class="metadata-summary-popover__entry">
                    <div class="metadata-summary-popover__entry-heading">
                      <n-tooltip
                        trigger="hover"
                        placement="right"
                        :content-style="issueDetailTooltipContentStyle"
                        :theme-overrides="issueDetailTooltipThemeOverrides"
                        :disabled="!skill.description"
                      >
                        <template #trigger>
                          <code class="metadata-summary-popover__entry-name">{{ skill.name }}</code>
                        </template>
                        {{ skill.description }}
                      </n-tooltip>
                      <n-tag size="tiny" :bordered="false">
                        {{ workerSummary.skill_selection_source === 'task'
                          ? t('taskView.workerSkillsTaskOverride')
                          : t('taskView.workerSkillsProfileDefault') }}
                      </n-tag>
                    </div>
                    <n-tooltip
                      trigger="hover"
                      placement="right"
                      :content-style="issueDetailTooltipContentStyle"
                      :theme-overrides="issueDetailTooltipThemeOverrides"
                      :disabled="!skill.description"
                    >
                      <template #trigger>
                        <div class="metadata-summary-popover__entry-detail metadata-summary-popover__entry-detail--skill">
                          {{ skill.description }}
                        </div>
                      </template>
                      {{ skill.description }}
                    </n-tooltip>
                  </div>
                </div>
                <div v-else class="metadata-summary-popover__empty">
                  {{ t('taskView.workerSkillsEmpty') }}
                </div>
              </section>

              <section class="metadata-summary-popover__section">
                <div class="metadata-summary-popover__section-title">
                  <span>{{ t('taskView.workerMounts') }}</span>
                  <span class="metadata-summary-popover__count">{{ workerSummary.mounts.length }}</span>
                </div>
                <div v-if="workerSummary.mounts.length" class="metadata-summary-popover__entries">
                  <div v-for="mount in workerSummary.mounts" :key="`${mount.source}:${mount.host_path}:${mount.container_path}`" class="metadata-summary-popover__entry">
                    <div class="metadata-summary-popover__entry-heading">
                      <code :title="mount.container_path">{{ mount.container_path }}</code>
                      <span class="metadata-summary-popover__tag-list">
                        <n-tag size="tiny" :bordered="false">
                          {{ mount.source === 'worker_kit' ? t('taskView.workerMountSourceKit') : t('taskView.workerMountSourceProfile') }}
                        </n-tag>
                        <n-tag size="tiny" :bordered="false">{{ mount.mode.toUpperCase() }}</n-tag>
                      </span>
                    </div>
                    <div class="metadata-summary-popover__entry-detail" :title="mount.host_path">
                      {{ mount.host_path }}
                    </div>
                  </div>
                </div>
                <div v-else class="metadata-summary-popover__empty">
                  {{ t('taskView.workerMountsEmpty') }}
                </div>
              </section>

              <section class="metadata-summary-popover__section">
                <div class="metadata-summary-popover__section-title">
                  <span>{{ t('taskView.workerEnvironmentVariables') }}</span>
                  <span class="metadata-summary-popover__count">{{ workerSummary.environment_variables.length }}</span>
                </div>
                <div v-if="workerSummary.environment_variables.length" class="metadata-summary-popover__entries metadata-summary-popover__entries--compact">
                  <div v-for="variable in workerSummary.environment_variables" :key="variable.key" class="metadata-summary-popover__entry metadata-summary-popover__entry--inline">
                    <code :title="variable.key">{{ variable.key }}</code>
                    <span class="metadata-summary-popover__tag-list">
                      <n-tag size="tiny" :bordered="false" :type="variable.is_secret ? 'warning' : 'default'">
                        {{ variable.is_secret ? t('taskView.workerEnvironmentSecret') : t('taskView.workerEnvironmentPlain') }}
                      </n-tag>
                      <n-tag size="tiny" :bordered="false" :type="variable.value_configured ? 'success' : 'default'">
                        {{ variable.value_configured ? t('taskView.runtimeConfigured') : t('taskView.runtimeNotConfigured') }}
                      </n-tag>
                    </span>
                  </div>
                </div>
                <div v-else class="metadata-summary-popover__empty">
                  {{ t('taskView.workerEnvironmentEmpty') }}
                </div>
              </section>
            </template>

            <p v-if="workerSummary.snapshot_available" class="metadata-summary-popover__hint">
              {{ t('taskView.workerSummaryHint') }}
            </p>
          </template>
        </div>
      </n-popover>
    </span>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useWindowSize } from '@vueuse/core'
import { NButton, NIcon, NPopover, NSpin, NTag, NTooltip } from 'naive-ui'
import { ChevronForwardOutline, ServerOutline } from '@vicons/ionicons5'
import { useI18n } from 'vue-i18n'
import {
  getTaskModelServiceSummary,
  getTaskWorkerRuntimeSummary,
  type Task,
  type TaskModelServiceSummary,
  type TaskWorkerRuntimeSummary
} from '../api'
import { formatDateTimeUtc8 } from '../utils/datetime'
import { issueDetailTooltipContentStyle, issueDetailTooltipThemeOverrides } from './issue-detail/tooltip'

type SummaryLoadState = 'idle' | 'loading' | 'loaded' | 'error'
type RuntimePopoverPlacement = 'left-start' | 'left-end'

interface RuntimePopoverLayout {
  placement: RuntimePopoverPlacement
  maxHeight: number
}

const RUNTIME_POPOVER_MAX_HEIGHT = 680
const RUNTIME_POPOVER_VIEWPORT_GAP = 24

const props = defineProps<{
  task: Task
}>()

const { t } = useI18n()
const { width: viewportWidth, height: viewportHeight } = useWindowSize()
const providerTriggerRef = ref<HTMLButtonElement | null>(null)
const providerPopoverVisible = ref(false)
const providerSummary = ref<TaskModelServiceSummary | null>(null)
const providerSummaryState = ref<SummaryLoadState>('idle')
const providerPopoverLayout = ref<RuntimePopoverLayout>({
  placement: 'left-start',
  maxHeight: RUNTIME_POPOVER_MAX_HEIGHT
})
const workerTriggerRef = ref<HTMLButtonElement | null>(null)
const workerPopoverVisible = ref(false)
const workerSummary = ref<TaskWorkerRuntimeSummary | null>(null)
const workerSummaryState = ref<SummaryLoadState>('idle')
const workerPopoverLayout = ref<RuntimePopoverLayout>({
  placement: 'left-start',
  maxHeight: RUNTIME_POPOVER_MAX_HEIGHT
})

const runtimePopoverWidth = computed(() =>
  Math.min(440, Math.max(1, viewportWidth.value - 24))
)

const providerDisplayName = computed(() =>
  props.task.provider_name
  || (props.task.provider_id ? `#${props.task.provider_id}` : t('config.providers.systemDefault'))
)

const workerDisplayName = computed(() =>
  props.task.worker_profile_name
  || (props.task.worker_profile_id ? `#${props.task.worker_profile_id}` : t('common.notAvailable'))
)

const providerSummaryDisplayName = computed(() =>
  providerSummary.value?.provider_name || providerDisplayName.value
)

const providerSummaryId = computed(() =>
  providerSummary.value?.provider_id ?? props.task.provider_id
)

const workerSummaryDisplayName = computed(() =>
  workerSummary.value?.worker_profile_name || workerDisplayName.value
)

const workerSummaryId = computed(() =>
  workerSummary.value?.worker_profile_id ?? props.task.worker_profile_id
)

const hasProviderSummary = computed(() =>
  !!props.task.provider_name || !!props.task.provider_id || !!props.task.model_name
)

const hasWorkerSummary = computed(() =>
  !!props.task.worker_profile_name || !!props.task.worker_profile_id || !!props.task.worker_image
)

const providerSourceLabel = computed(() => {
  if (providerSummary.value?.configuration_source === 'execution_snapshot') {
    return t('taskView.providerSourceExecutionSnapshot')
  }
  if (providerSummary.value?.configuration_source === 'current_provider') {
    return t('taskView.providerSourceCurrentConfig')
  }
  return t('common.notAvailable')
})

const providerSourceTagType = computed(() =>
  providerSummary.value?.configuration_source === 'execution_snapshot'
    ? 'success'
    : 'default'
)

const providerSummaryHint = computed(() =>
  providerSummary.value?.configuration_source === 'execution_snapshot'
    ? t('taskView.providerExecutionSnapshotHint')
    : t('taskView.providerCurrentConfigHint')
)

const workerRuntimeModeLabel = computed(() => {
  if (workerSummary.value?.runtime_mode === 'mounted_kit') {
    return t('config.workerRuntimeModeMountedKit')
  }
  if (workerSummary.value?.runtime_mode === 'baked_image') {
    return t('config.workerRuntimeModeBakedImage')
  }
  return workerSummary.value?.runtime_mode || t('common.notAvailable')
})

async function loadProviderSummary(force = false): Promise<void> {
  if (providerSummaryState.value === 'loading') return
  if (!force && providerSummaryState.value === 'loaded') return
  const taskId = props.task.id
  providerSummaryState.value = 'loading'
  try {
    const summary = await getTaskModelServiceSummary(taskId)
    if (props.task.id !== taskId) return
    providerSummary.value = summary
    providerSummaryState.value = 'loaded'
  } catch (error) {
    if (props.task.id !== taskId) return
    console.error('Failed to load task model service summary:', error)
    providerSummaryState.value = 'error'
  }
}

async function loadWorkerSummary(): Promise<void> {
  if (workerSummaryState.value === 'loading' || workerSummaryState.value === 'loaded') return
  const taskId = props.task.id
  workerSummaryState.value = 'loading'
  try {
    const summary = await getTaskWorkerRuntimeSummary(taskId)
    if (props.task.id !== taskId) return
    workerSummary.value = summary
    workerSummaryState.value = 'loaded'
  } catch (error) {
    if (props.task.id !== taskId) return
    console.error('Failed to load task worker runtime summary:', error)
    workerSummaryState.value = 'error'
  }
}

function handleProviderPopoverShow(show: boolean): void {
  if (show) {
    providerPopoverLayout.value = resolveRuntimePopoverLayout(providerTriggerRef.value)
  }
  providerPopoverVisible.value = show
  if (show) void loadProviderSummary(true)
}

function handleWorkerPopoverShow(show: boolean): void {
  if (show) {
    workerPopoverLayout.value = resolveRuntimePopoverLayout(workerTriggerRef.value)
  }
  workerPopoverVisible.value = show
  if (show) void loadWorkerSummary()
}

function resolveRuntimePopoverLayout(trigger: HTMLButtonElement | null): RuntimePopoverLayout {
  const windowHeight = Number.isFinite(viewportHeight.value)
    ? viewportHeight.value
    : RUNTIME_POPOVER_MAX_HEIGHT + RUNTIME_POPOVER_VIEWPORT_GAP * 2
  const viewportMaxHeight = Math.max(
    1,
    Math.min(
      RUNTIME_POPOVER_MAX_HEIGHT,
      windowHeight - RUNTIME_POPOVER_VIEWPORT_GAP * 2
    )
  )

  if (!trigger) {
    return {
      placement: 'left-start',
      maxHeight: viewportMaxHeight
    }
  }

  const triggerRect = trigger.getBoundingClientRect()
  const availableBelow = Math.max(
    1,
    windowHeight - triggerRect.top - RUNTIME_POPOVER_VIEWPORT_GAP
  )
  const availableAbove = Math.max(
    1,
    triggerRect.bottom - RUNTIME_POPOVER_VIEWPORT_GAP
  )
  const placement: RuntimePopoverPlacement = availableBelow >= availableAbove
    ? 'left-start'
    : 'left-end'

  return {
    placement,
    maxHeight: Math.min(
      viewportMaxHeight,
      placement === 'left-start' ? availableBelow : availableAbove
    )
  }
}

function retryProviderSummary(): void {
  providerSummaryState.value = 'idle'
  void loadProviderSummary(true)
}

function retryWorkerSummary(): void {
  workerSummaryState.value = 'idle'
  void loadWorkerSummary()
}

watch(
  () => props.task.id,
  () => {
    providerPopoverVisible.value = false
    providerSummary.value = null
    providerSummaryState.value = 'idle'
    workerPopoverVisible.value = false
    workerSummary.value = null
    workerSummaryState.value = 'idle'
  }
)

watch(() => viewportHeight.value, () => {
  if (providerPopoverVisible.value) {
    providerPopoverLayout.value = resolveRuntimePopoverLayout(providerTriggerRef.value)
  }
  if (workerPopoverVisible.value) {
    workerPopoverLayout.value = resolveRuntimePopoverLayout(workerTriggerRef.value)
  }
})

function formatDate(dateStr: string): string {
  return formatDateTimeUtc8(dateStr)
}
</script>

<style scoped>
.metadata-row {
  display: contents;
}

.metadata-label {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  color: var(--n-text-color-3, #999);
  font-size: 13px;
  white-space: nowrap;
}

.metadata-label-icon {
  flex: 0 0 auto;
  opacity: 0.65;
}

.metadata-row > :last-child {
  min-width: 0;
}

.metadata-value {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
  min-width: 0;
  color: var(--n-text-color-1);
  font-size: 14px;
  overflow-wrap: anywhere;
  word-break: break-word;
}

.metadata-summary-trigger {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
  max-width: 100%;
  padding: 3px 7px;
  border: 1px solid rgba(100, 116, 139, 0.2);
  border-radius: 6px;
  background: rgba(100, 116, 139, 0.06);
  color: var(--n-text-color-1);
  font: inherit;
  text-align: left;
  cursor: pointer;
  transition: border-color 0.15s ease, background-color 0.15s ease;
}

.metadata-summary-trigger:hover,
.metadata-summary-trigger:focus-visible {
  border-color: rgba(59, 130, 246, 0.42);
  background: rgba(59, 130, 246, 0.08);
}

.metadata-summary-trigger:focus-visible {
  outline: 2px solid rgba(59, 130, 246, 0.26);
  outline-offset: 1px;
}

.metadata-summary-trigger__body {
  display: grid;
  gap: 1px;
  min-width: 0;
  max-width: 100%;
}

.metadata-summary-trigger__label,
.metadata-summary-trigger__meta {
  min-width: 0;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.metadata-summary-trigger__label {
  color: var(--n-text-color-1);
  font-size: 13px;
  line-height: 1.35;
}

.metadata-summary-trigger__meta {
  color: var(--n-text-color-3, #8a8f98);
  font-family: var(--n-font-family-mono, 'JetBrains Mono', monospace);
  font-size: 11px;
  line-height: 1.3;
}

.metadata-summary-trigger__arrow {
  flex: 0 0 auto;
  color: var(--n-text-color-3, #8a8f98);
}

.metadata-summary-popover {
  display: grid;
  box-sizing: border-box;
  gap: 12px;
  width: min(440px, calc(100vw - 24px));
  max-width: 100%;
}

.metadata-summary-popover__heading {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 10px;
}

.metadata-summary-popover__title-wrap {
  display: flex;
  align-items: flex-start;
  gap: 7px;
  min-width: 0;
}

.metadata-summary-popover__icon {
  flex: 0 0 auto;
  margin-top: 2px;
  color: var(--n-primary-color, #18a058);
}

.metadata-summary-popover__title {
  min-width: 0;
  color: var(--n-text-color-1);
  font-size: 14px;
  font-weight: 600;
  line-height: 1.45;
  overflow-wrap: anywhere;
}

.metadata-summary-popover__list {
  display: grid;
  gap: 8px;
  margin: 0;
}

.metadata-summary-popover__item {
  display: grid;
  grid-template-columns: minmax(70px, max-content) minmax(0, 1fr);
  align-items: baseline;
  gap: 10px;
  min-width: 0;
}

.metadata-summary-popover__item dt {
  color: var(--n-text-color-3, #8a8f98);
  font-size: 11px;
  line-height: 1.45;
}

.metadata-summary-popover__item dd {
  min-width: 0;
  margin: 0;
  color: var(--n-text-color-2);
  font-size: 12px;
  line-height: 1.5;
  overflow-wrap: anywhere;
  word-break: break-word;
}

.metadata-summary-popover__mono {
  font-family: var(--n-font-family-mono, 'JetBrains Mono', monospace);
}

.metadata-summary-popover__tag-list {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}

.metadata-summary-popover__muted {
  color: var(--n-text-color-3, #8a8f98) !important;
}

.metadata-summary-popover__state {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  min-height: 88px;
  color: var(--n-text-color-3, #8a8f98);
  font-size: 12px;
}

.metadata-summary-popover__state--error {
  flex-direction: column;
  color: var(--n-error-color, #d03050);
}

.metadata-summary-popover__notice {
  padding: 8px 10px;
  border: 1px solid rgba(245, 158, 11, 0.2);
  border-radius: 7px;
  background: rgba(245, 158, 11, 0.07);
  color: var(--n-text-color-2);
  font-size: 11px;
  line-height: 1.5;
}

.metadata-summary-popover__section {
  display: grid;
  gap: 7px;
  min-width: 0;
  padding-top: 10px;
  border-top: 1px solid rgba(148, 163, 184, 0.18);
}

.metadata-summary-popover__section-title {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  color: var(--n-text-color-2);
  font-size: 11px;
  font-weight: 600;
  line-height: 1.4;
}

.metadata-summary-popover__count {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 18px;
  height: 18px;
  padding: 0 5px;
  border-radius: 999px;
  background: rgba(100, 116, 139, 0.1);
  color: var(--n-text-color-3, #8a8f98);
  font-size: 10px;
  font-weight: 500;
}

.metadata-summary-popover__prompt {
  box-sizing: border-box;
  max-height: 180px;
  margin: 0;
  padding: 9px 10px;
  overflow: auto;
  border: 1px solid rgba(148, 163, 184, 0.18);
  border-radius: 7px;
  background: rgba(100, 116, 139, 0.06);
  color: var(--n-text-color-2);
  font-family: var(--n-font-family-mono, 'JetBrains Mono', monospace);
  font-size: 11px;
  line-height: 1.55;
  overflow-wrap: anywhere;
  white-space: pre-wrap;
  word-break: break-word;
}

.metadata-summary-popover__entries {
  display: grid;
  gap: 6px;
}

.metadata-summary-popover__entries--compact {
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

.metadata-summary-popover__entry {
  display: grid;
  gap: 3px;
  min-width: 0;
  padding: 7px 8px;
  border: 1px solid rgba(148, 163, 184, 0.16);
  border-radius: 7px;
  background: rgba(100, 116, 139, 0.045);
}

.metadata-summary-popover__entry--inline {
  align-content: space-between;
}

.metadata-summary-popover__entry-heading {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 8px;
  min-width: 0;
}

.metadata-summary-popover__entry code,
.metadata-summary-popover__entry-heading code {
  min-width: 0;
  color: var(--n-text-color-2);
  font-family: var(--n-font-family-mono, 'JetBrains Mono', monospace);
  font-size: 11px;
  line-height: 1.45;
  overflow-wrap: anywhere;
  word-break: break-word;
}

.metadata-summary-popover__entry-heading .metadata-summary-popover__entry-name {
  font-size: 12px;
  line-height: 1.5;
}

.metadata-summary-popover__entry-detail {
  min-width: 0;
  color: var(--n-text-color-3, #8a8f98);
  font-family: var(--n-font-family-mono, 'JetBrains Mono', monospace);
  font-size: 10px;
  line-height: 1.4;
  overflow-wrap: anywhere;
  word-break: break-word;
}

.metadata-summary-popover__entry-detail--skill {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  overflow-wrap: normal;
  word-break: normal;
  font-size: 12px;
  line-height: 1.5;
}

.metadata-summary-popover__empty {
  padding: 8px 10px;
  border-radius: 7px;
  background: rgba(100, 116, 139, 0.045);
  color: var(--n-text-color-3, #8a8f98);
  font-size: 11px;
  line-height: 1.5;
}

.metadata-summary-popover__hint {
  margin: 0;
  padding-top: 9px;
  border-top: 1px solid rgba(148, 163, 184, 0.18);
  color: var(--n-text-color-3, #8a8f98);
  font-size: 11px;
  line-height: 1.5;
}

@media (max-width: 420px) {
  .metadata-row {
    display: grid;
    grid-template-columns: 1fr;
    gap: 3px;
  }

  .metadata-value,
  .metadata-summary-trigger {
    width: 100%;
  }

  .metadata-summary-popover__item,
  .metadata-summary-popover__entries--compact {
    grid-template-columns: 1fr;
  }

  .metadata-summary-popover__item {
    gap: 2px;
  }
}
</style>
