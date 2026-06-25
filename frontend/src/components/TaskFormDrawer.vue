<template>
  <!-- Template Picker Sub-Drawer -->
  <n-drawer v-model:show="showTemplateDrawer" :width="isMobile ? '100%' : 480" placement="right">
    <div class="template-drawer-layout">
      <div class="template-drawer-layout__header">
        <span class="template-drawer-layout__title">{{ t('createTask.selectTemplate') }}</span>
        <n-button quaternary circle @click="showTemplateDrawer = false">
          <template #icon><n-icon size="18"><CloseOutline /></n-icon></template>
        </n-button>
      </div>
      <Transition name="banner-slide">
        <div v-if="pendingTemplate" class="template-overwrite-banner">
          <span class="template-overwrite-banner__text">{{ t('createTask.templateOverwriteConfirm') }}</span>
          <div class="template-overwrite-banner__actions">
            <n-button size="small" @click="cancelTemplateOverwrite">{{ t('common.cancel') }}</n-button>
            <n-button size="small" type="primary" @click="confirmTemplateOverwrite">{{ t('common.confirm') }}</n-button>
          </div>
        </div>
      </Transition>
      <n-scrollbar class="template-drawer-layout__body" trigger="hover" content-style="padding: 8px 0;">
        <div v-if="activePromptTemplates.length > 0" class="template-tag-filter">
          <n-select
            :value="selectedTemplateTags"
            :show="templateTagFilterVisible"
            multiple
            clearable
            :options="templateTagOptions"
            :placeholder="t('createTask.filterTemplatesByTags')"
            @update:value="handleTemplateTagFilterUpdate"
            @update:show="templateTagFilterVisible = $event"
          />
        </div>
        <div v-if="activePromptTemplates.length === 0" class="prompt-template-dropdown__empty">
          {{ t('createTask.noPromptTemplates') }}
        </div>
        <div v-else-if="filteredPromptTemplates.length === 0" class="prompt-template-dropdown__empty">
          {{ t('createTask.noMatchingPromptTemplates') }}
        </div>
        <div
          v-for="tmpl in filteredPromptTemplates"
          :key="tmpl.id"
          class="prompt-template-dropdown__item"
          :class="{ 'prompt-template-dropdown__item--pending': pendingTemplate?.id === tmpl.id }"
          @click="handleTemplateItemClick(tmpl)"
        >
          <div class="prompt-template-dropdown__item-name">{{ tmpl.name }}</div>
          <div v-if="(tmpl.tags ?? []).length > 0" class="prompt-template-dropdown__tags">
            <n-tag
              v-for="tag in tmpl.tags ?? []"
              :key="tag"
              size="small"
              round
            >
              {{ tag }}
            </n-tag>
          </div>
          <div class="prompt-template-dropdown__item-preview">{{ tmpl.content.substring(0, 80) }}...</div>
        </div>
      </n-scrollbar>
    </div>
  </n-drawer>

  <!-- Schedule Heatmap Sub-Drawer (create mode only) -->
  <n-drawer v-if="mode === 'create'" v-model:show="showHeatmapDrawer" :width="isMobile ? '100%' : 580" placement="right">
    <n-drawer-content :title="t('createTask.schedulePreviewTitle')" :native-scrollbar="false" closable>
      <n-spin v-if="scheduledTasksLoading" :description="t('createTask.schedulePreviewLoading')" />
      <template v-else>
        <p style="margin-bottom: 12px; color: var(--n-text-color-3); font-size: 13px;">
          {{ t('createTask.schedulePreviewHint') }}
        </p>
        <HeatmapChart
          :tasks="scheduledTasksForPreview"
          :selected-ms="scheduledAt"
          :max-per-slot="slotMaxTasks"
          :enforce-capacity="slotEnforce"
          @cell-click="handleHeatmapCellClick"
        />
      </template>
    </n-drawer-content>
  </n-drawer>

  <!-- Main Drawer -->
  <n-drawer v-model:show="showProxy" :width="isMobile ? '100%' : 640" placement="right" :data-testid="drawerTestId">
    <n-drawer-content
      :title="mode === 'edit' ? t('taskView.editTask') : t('issue.createTask')"
      :native-scrollbar="false"
      closable
    >
      <n-form label-placement="top" class="task-form-drawer__form">
        <!-- Prompt + require changes -->
        <div class="prompt-form-section">
          <div class="prompt-section-header">
            <div class="prompt-label-left">
              <span class="prompt-section-label-text">{{ t('issue.prompt') }}</span>
              <n-button
                size="tiny"
                :disabled="promptTemplatesLoading || activePromptTemplates.length === 0"
                :loading="promptTemplatesLoading"
                type="primary"
                ghost
                @click="showTemplateDrawer = true"
              >
                <template #icon>
                  <n-icon :component="DocumentTextOutline" size="12" />
                </template>
                {{ t('createTask.useTemplate') }}
              </n-button>
            </div>
            <div class="prompt-label-right">
            </div>
          </div>
          <VariableEditor
            v-model="prompt"
            :variable-tips="promptVariableTips"
            :placeholder="placeholderText"
          />
          <div v-if="unreplacedVariables.length > 0" class="prompt-variable-warning">
            <n-icon :component="WarningOutline" size="14" />
            <span>{{ t('createTask.unreplacedVariablesHint') }}: {{ unreplacedVariables.join(', ') }}</span>
          </div>
        </div>

        <!-- Task mode + require changes -->
        <n-form-item
          class="task-mode-form-item"
          :validation-status="taskModeErrorVisible ? 'error' : undefined"
        >
          <template #label>
            <div class="task-mode-label-row">
              <span>{{ t('issue.taskMode') }}</span>
              <span
                class="task-mode-label-hint"
                :class="{ 'task-mode-label-hint--error': taskModeErrorVisible }"
              >{{ t('issue.taskModeManualHint') }}</span>
            </div>
          </template>
          <div class="task-mode-section">
            <div class="task-mode-selector" role="radiogroup" :aria-label="t('issue.taskMode')">
              <div
                class="task-mode-card"
                role="radio"
                tabindex="0"
                :aria-checked="taskMode === 'execute'"
                :class="{
                  'task-mode-card--active': taskMode === 'execute',
                  'task-mode-card--error': taskModeErrorVisible
                }"
                @click="selectTaskMode('execute')"
                @keydown.enter.prevent="selectTaskMode('execute')"
                @keydown.space.prevent="selectTaskMode('execute')"
              >
                <n-icon :component="CodeSlashOutline" size="18" class="task-mode-card__icon" />
                <div class="task-mode-card__body">
                  <div class="task-mode-card__label">{{ t('issue.taskModeExecute') }}</div>
                  <div class="task-mode-card__desc">{{ t('issue.taskModeExecuteDesc') }}</div>
                </div>
                <n-icon
                  v-if="taskMode === 'execute'"
                  :component="CheckmarkCircleOutline"
                  size="16"
                  class="task-mode-card__check"
                />
              </div>
              <div
                class="task-mode-card"
                role="radio"
                tabindex="0"
                :aria-checked="taskMode === 'plan'"
                :class="{
                  'task-mode-card--active': taskMode === 'plan',
                  'task-mode-card--error': taskModeErrorVisible
                }"
                @click="selectTaskMode('plan')"
                @keydown.enter.prevent="selectTaskMode('plan')"
                @keydown.space.prevent="selectTaskMode('plan')"
              >
                <n-icon :component="BulbOutline" size="18" class="task-mode-card__icon" />
                <div class="task-mode-card__body">
                  <div class="task-mode-card__label">{{ t('issue.taskModePlan') }}</div>
                  <div class="task-mode-card__desc">{{ t('issue.taskModePlanDesc') }}</div>
                </div>
                <n-icon
                  v-if="taskMode === 'plan'"
                  :component="CheckmarkCircleOutline"
                  size="16"
                  class="task-mode-card__check"
                />
              </div>
            </div>
            <div v-if="taskMode === 'execute'" class="require-changes-row">
              <span class="prompt-label-require-text">{{ t('issue.requireChanges') }}</span>
              <n-tooltip
                trigger="hover"
                placement="top"
                :content-style="issueDetailTooltipContentStyle"
                :theme-overrides="issueDetailTooltipThemeOverrides"
              >
                <template #trigger>
                  <n-icon :component="InformationCircleOutline" size="13" class="require-changes-info-icon" />
                </template>
                {{ t('issue.requireChangesHint') }}
              </n-tooltip>
              <n-switch v-model:value="requireChanges" size="small" />
            </div>
          </div>
        </n-form-item>

        <details
          class="run-instruction-advanced"
          :class="{ 'run-instruction-advanced--disabled': taskMode === null }"
        >
          <summary
            class="run-instruction-advanced__summary"
            :aria-disabled="taskMode === null"
            @click="handleRunInstructionSummaryClick"
          >
            <span class="run-instruction-advanced__icon">
              <n-icon :component="OptionsOutline" size="16" />
            </span>
            <span class="run-instruction-advanced__copy">
              <span class="run-instruction-advanced__title">{{ t('runInstruction.advanced') }}</span>
              <span class="run-instruction-advanced__hint">
                {{ taskMode === null
                  ? t('runInstruction.selectModeHint')
                  : t('runInstruction.advancedHint') }}
              </span>
            </span>
            <span class="run-instruction-advanced__chevron" aria-hidden="true">›</span>
          </summary>
          <div class="run-instruction-advanced__content">
            <n-spin :show="defaultsLoading">
              <n-alert v-if="defaultsError" type="error" :bordered="false">
                {{ defaultsError }}
              </n-alert>
              <n-form-item :label="t('runInstruction.template')">
                <RunInstructionTemplateEditor
                  :model-value="runInstructionTemplate"
                  :available-placeholders="currentAvailablePlaceholders"
                  :known-placeholders="knownRunInstructionPlaceholders"
                  preview-enabled
                  :preview-loading="previewLoading"
                  :preview-result="previewResult"
                  :preview-error="previewError"
                  @update:model-value="handleRunInstructionInput"
                  @use-prompt-only="usePromptOnly"
                  @restore-default="restoreRunInstructionDefault"
                  @preview="handleRunInstructionPreview"
                />
              </n-form-item>
            </n-spin>
          </div>
        </details>

        <!-- Priority cards -->
        <n-form-item :label="t('common.priority')">
          <n-radio-group v-model:value="priority" class="priority-selector">
            <div
              v-for="opt in priorityOptions"
              :key="opt.value"
              class="priority-card"
              :class="[
                `priority-card--p${opt.value}`,
                { 'priority-card--active': priority === opt.value }
              ]"
              @click="priority = opt.value"
            >
              <n-radio :value="opt.value" />
              <div>
                <div class="priority-card__label">{{ opt.label }}</div>
                <div class="priority-card__desc">{{ opt.desc }}</div>
              </div>
            </div>
          </n-radio-group>
        </n-form-item>

        <!-- Schedule (create mode only) -->
        <n-form-item v-if="mode === 'create'" class="schedule-form-item">
          <template #label>
            <div class="execution-field-label">
              <span>{{ t('createTask.schedule') }}</span>
              <span class="execution-field-label__hint">{{ t('createTask.scheduleHint') }}</span>
            </div>
          </template>
          <div class="schedule-section">
            <div class="schedule-mode-selector" role="radiogroup" :aria-label="t('createTask.schedule')">
              <button
                type="button"
                class="schedule-mode-card"
                :class="{ 'schedule-mode-card--active': scheduleType === 'now' }"
                role="radio"
                :aria-checked="scheduleType === 'now'"
                @click="selectScheduleType('now')"
              >
                <span class="schedule-mode-card__icon">
                  <n-icon :component="FlashOutline" size="17" />
                </span>
                <span class="schedule-mode-card__copy">
                  <span class="schedule-mode-card__title">{{ t('createTask.executeNow') }}</span>
                  <span class="schedule-mode-card__description">{{ t('createTask.executeNowDesc') }}</span>
                </span>
                <n-icon
                  v-if="scheduleType === 'now'"
                  :component="CheckmarkCircleOutline"
                  size="16"
                  class="schedule-mode-card__check"
                />
              </button>
              <button
                type="button"
                class="schedule-mode-card"
                :class="{ 'schedule-mode-card--active': scheduleType === 'scheduled' }"
                role="radio"
                :aria-checked="scheduleType === 'scheduled'"
                @click="selectScheduleType('scheduled')"
              >
                <span class="schedule-mode-card__icon">
                  <n-icon :component="TimeOutline" size="17" />
                </span>
                <span class="schedule-mode-card__copy">
                  <span class="schedule-mode-card__title">{{ t('createTask.scheduleAt') }}</span>
                  <span class="schedule-mode-card__description">{{ t('createTask.scheduleAtDesc') }}</span>
                </span>
                <n-icon
                  v-if="scheduleType === 'scheduled'"
                  :component="CheckmarkCircleOutline"
                  size="16"
                  class="schedule-mode-card__check"
                />
              </button>
            </div>
            <Transition name="schedule-detail">
              <div v-if="scheduleType === 'scheduled'" class="schedule-detail-panel">
                <n-date-picker
                  v-model:value="scheduledAt"
                  class="schedule-detail-panel__picker"
                  type="datetime"
                  clearable
                  :placeholder="t('createTask.selectDateTime')"
                  :is-date-disabled="isScheduleDateDisabled"
                />
                <n-button
                  class="schedule-detail-panel__heatmap"
                  size="small"
                  secondary
                  :loading="scheduledTasksLoading"
                  @click="openHeatmapDrawer"
                >
                  <template #icon><n-icon :component="CalendarOutline" /></template>
                  {{ t('createTask.viewScheduleHeatmap') }}
                </n-button>
              </div>
            </Transition>
          </div>
        </n-form-item>

        <!-- AI Provider -->
        <n-form-item class="provider-form-item">
          <template #label>
            <div class="execution-field-label">
              <span>{{ t('createTask.workerProfile') }}</span>
              <span class="execution-field-label__hint">{{ t('createTask.workerProfileHint') }}</span>
            </div>
          </template>
          <div class="provider-control" :class="{ 'provider-control--empty': !effectiveWorkerProfile }">
            <span class="provider-control__icon">
              <n-icon :component="HardwareChipOutline" size="18" />
            </span>
            <div class="provider-control__body">
              <n-select
                v-model:value="selectedWorkerProfileId"
                class="provider-control__select"
                :options="workerProfileOptions"
                clearable
                :placeholder="t('createTask.selectWorkerProfile')"
                @update:value="handleWorkerProfileChange"
              />
              <div v-if="effectiveWorkerProfile" class="provider-control__summary">
                <span class="provider-control__status">
                  {{ selectedWorkerProfileId === null
                    ? t('createTask.workerUsesDefault')
                    : t('createTask.workerUsesSelected') }}
                </span>
                <span aria-hidden="true">·</span>
                <span class="provider-control__model">
                  {{ effectiveWorkerProfile.name }} / {{ effectiveWorkerProfile.image }}
                </span>
              </div>
            </div>
          </div>
        </n-form-item>

        <n-form-item class="provider-form-item">
          <template #label>
            <div class="execution-field-label">
              <span>{{ t('config.providers.providerLabel') }}</span>
              <span class="execution-field-label__hint">{{ t('createTask.providerHint') }}</span>
            </div>
          </template>
          <div class="provider-control" :class="{ 'provider-control--empty': !effectiveProvider }">
            <span class="provider-control__icon">
              <n-icon :component="HardwareChipOutline" size="18" />
            </span>
            <div class="provider-control__body">
              <n-select
                v-model:value="selectedProviderId"
                class="provider-control__select"
                :options="providerOptions"
                clearable
                :placeholder="t('config.providers.systemDefault')"
              />
              <div v-if="effectiveProvider" class="provider-control__summary">
                <span class="provider-control__status">
                  {{ selectedProviderId === null
                    ? t('createTask.providerUsesDefault')
                    : t('createTask.providerUsesSelected') }}
                </span>
                <span aria-hidden="true">·</span>
                <span class="provider-control__model">{{ effectiveProvider.name }} / {{ effectiveProvider.model }}</span>
              </div>
              <div v-else class="provider-control__summary provider-control__summary--warning">
                {{ t('config.providers.noEnabledProvider') }}
              </div>
            </div>
          </div>
        </n-form-item>
      </n-form>

      <!-- Slot capacity alert (create mode only) -->
      <n-alert
        v-if="mode === 'create' && slotCapacity?.is_full"
        :type="slotCapacity.enforce ? 'error' : 'warning'"
        style="margin-bottom: 16px;"
      >
        {{ slotCapacity.enforce
          ? t('createTask.slotFullError', {
              start: formatDateTimeUtc8Compact(slotCapacity.hour_start),
              end: formatTimeUtc8(slotCapacity.hour_end),
              count: slotCapacity.count,
              max: slotCapacity.max
            })
          : t('createTask.slotFullWarning', {
              start: formatDateTimeUtc8Compact(slotCapacity.hour_start),
              end: formatTimeUtc8(slotCapacity.hour_end),
              count: slotCapacity.count,
              max: slotCapacity.max
            })
        }}
      </n-alert>

      <!-- Usage limit alert (create mode only) -->
      <n-alert
        v-if="mode === 'create' && usageLimitDetail"
        type="warning"
        style="margin-bottom: 16px;"
        data-testid="issue-create-task-usage-alert"
      >
        <div class="task-form-drawer__usage-limit-alert">
          <div class="task-form-drawer__usage-limit-title">{{ t('createTask.usageLimitExceededTitle') }}</div>
          <div
            v-for="item in usageLimitDetail.exceeded_items"
            :key="`${item.field}-${item.reset_at}`"
            class="task-form-drawer__usage-limit-row"
          >
            <span>{{ t(`createTask.usageWindow.${item.window}`) }}</span>
            <span>{{ t(`createTask.usageMetric.${item.metric}`) }}</span>
            <span>{{ t('createTask.usageLimitUsed') }} {{ item.used }}/{{ item.limit }}</span>
            <span>{{ t('createTask.usageLimitReset') }} {{ formatUsageResetAt(item.reset_at) }}</span>
          </div>
        </div>
      </n-alert>

      <template #footer>
        <div style="display: flex; justify-content: flex-end;">
          <n-button
            type="primary"
            :loading="submitLoading"
            :data-testid="mode === 'create' ? 'issue-create-task-button' : 'task-form-save-button'"
            @click="mode === 'create' ? handleCreate() : handleEdit()"
          >
            {{ mode === 'create' ? t('issue.createTask') : t('common.save') }}
          </n-button>
        </div>
      </template>
    </n-drawer-content>
  </n-drawer>
</template>

<script setup lang="ts">
import { ref, computed, watch, onMounted, onUnmounted, useAttrs } from 'vue'
import {
  NButton, NDrawer, NDrawerContent, NForm, NFormItem, NRadio, NRadioGroup,
  NDatePicker, NSelect, NAlert, NTooltip, NSwitch, NSpin, NIcon, NScrollbar, NTag,
  useMessage
} from 'naive-ui'
import { useI18n } from 'vue-i18n'
import {
  DocumentTextOutline,
  WarningOutline,
  CalendarOutline,
  CloseOutline,
  InformationCircleOutline,
  CodeSlashOutline,
  BulbOutline,
  CheckmarkCircleOutline,
  OptionsOutline,
  FlashOutline,
  TimeOutline,
  HardwareChipOutline
} from '@vicons/ionicons5'
import VariableEditor from './VariableEditor.vue'
import HeatmapChart from './HeatmapChart.vue'
import RunInstructionTemplateEditor from './RunInstructionTemplateEditor.vue'
import {
  createTask, updateTask, getPromptTemplates, getProviders, getScheduledTasks, getSlotCapacity, getConfig,
  getRunInstructionTemplateDefaults, getWorkerProfiles, previewRunInstructionTemplate,
  type Task, type PromptTemplate, type SlotCapacityInfo, type AIProvider, type UpdateTaskRequest,
  type RunInstructionTemplateDefaults, type WorkerProfile
} from '../api'
import { useBreakpoints } from '../composables/useBreakpoints'
import { formatDateTimeUtc8Compact, formatTimeUtc8 } from '../utils/datetime'
import {
  filterPromptTemplatesByTags,
  getActivePromptTemplates,
  getPromptTemplateTags
} from '../utils/promptTemplates'
import { extractSlotErrorMessage } from '../utils/slotError'
import { formatUsageResetAt, isUsageLimitExceededDetail, type UsageLimitExceededDetail } from '../utils/usageLimits'
import { issueDetailTooltipContentStyle, issueDetailTooltipThemeOverrides } from './issue-detail/tooltip'

defineOptions({ inheritAttrs: false })

const props = withDefaults(defineProps<{
  show: boolean
  mode?: 'create' | 'edit'
  issueId?: number
  issueDescription?: string
  task?: Task
}>(), {
  mode: 'create'
})

const emit = defineEmits<{
  'update:show': [value: boolean]
  created: [task: Task]
  updated: [task: Task]
}>()

const { t } = useI18n()
const message = useMessage()
const { isMobile } = useBreakpoints()
const attrs = useAttrs()

const showProxy = computed({
  get: () => props.show,
  set: (val) => emit('update:show', val)
})

const drawerTestId = computed(() => {
  const testId = attrs['data-testid']
  return typeof testId === 'string' ? testId : 'task-form-drawer'
})

// Form state
const prompt = ref('')
const priority = ref(1)
const requireChanges = ref(true)
const taskMode = ref<'execute' | 'plan' | null>(null)
const taskModeErrorVisible = ref(false)
const selectedProviderId = ref<number | null>(null)
const selectedWorkerProfileId = ref<number | null>(null)
const scheduleType = ref<'now' | 'scheduled'>('now')
const scheduledAt = ref<number | null>(null)
const submitLoading = ref(false)
const usageLimitDetail = ref<UsageLimitExceededDetail | null>(null)
const runInstructionTemplate = ref('')
const initialRunInstructionTemplate = ref('')
const runInstructionDirty = ref(false)
const runInstructionDefaults = ref<RunInstructionTemplateDefaults | null>(null)
const defaultsLoading = ref(false)
const defaultsError = ref('')
const previewLoading = ref(false)
const previewResult = ref('')
const previewError = ref('')

// Template picker state
const showTemplateDrawer = ref(false)
const promptTemplates = ref<PromptTemplate[]>([])
const promptTemplatesLoading = ref(false)
const selectedTemplateTags = ref<string[]>([])
const templateTagFilterVisible = ref(false)
const pendingTemplate = ref<PromptTemplate | null>(null)
const promptVariableTips = ref<Record<string, string> | undefined>(undefined)

// Providers state
const providers = ref<AIProvider[]>([])
const workerProfiles = ref<WorkerProfile[]>([])

// Schedule heatmap state (create mode)
const showHeatmapDrawer = ref(false)
const scheduledTasksForPreview = ref<Task[]>([])
const scheduledTasksLoading = ref(false)
const slotMaxTasks = ref(0)
const slotEnforce = ref(false)
const slotCapacity = ref<SlotCapacityInfo | null>(null)
const slotCapacityLoading = ref(false)
let slotCheckTimeout: ReturnType<typeof setTimeout> | undefined
let slotCheckGeneration = 0
let previewRequestGeneration = 0

const priorityOptions = [
  { label: 'P0', value: 0, desc: t('createTask.priorityP0Desc') },
  { label: 'P1', value: 1, desc: t('createTask.priorityP1Desc') },
  { label: 'P2', value: 2, desc: t('createTask.priorityP2Desc') }
]

const placeholderText = computed(() =>
  props.issueDescription || t('issue.promptPlaceholder')
)

const unreplacedVariables = computed(() => {
  const content = prompt.value || ''
  const matches = content.match(/\{\{([^}]+)\}\}/g)
  if (!matches) return []
  return matches.map(m => m.replace(/\{\{|\}\}/g, ''))
})

const hasExistingPrompt = computed(() => Boolean(prompt.value && prompt.value.trim()))

const selectableProviders = computed(() =>
  providers.value.filter((provider) => {
    if (!provider.is_disabled) return true
    return props.mode === 'edit' && provider.id === props.task?.provider_id
  })
)

const providerOptions = computed(() =>
  selectableProviders.value.map(p => ({
    label: `${p.name} (${p.model})${p.is_default ? ' ★' : ''}${p.is_disabled ? ` - ${t('config.providers.disabled')}` : ''}`,
    value: p.id,
    disabled: p.is_disabled,
  }))
)
const selectableWorkerProfiles = computed(() =>
  workerProfiles.value.filter((profile) => {
    if (profile.enabled) return true
    return props.mode === 'edit' && profile.id === props.task?.worker_profile_id
  })
)
const workerProfileOptions = computed(() =>
  selectableWorkerProfiles.value.map(profile => ({
    label: `${profile.name} (${profile.image})${profile.is_default ? ' ★' : ''}${!profile.enabled ? ` - ${t('config.disabled')}` : ''}`,
    value: profile.id,
    disabled: !profile.enabled,
  }))
)
const effectiveProvider = computed(() => {
  if (selectedProviderId.value !== null) {
    return selectableProviders.value.find(provider => provider.id === selectedProviderId.value) ?? null
  }
  return selectableProviders.value.find(provider => provider.is_default && !provider.is_disabled) ?? null
})
const effectiveWorkerProfile = computed(() => {
  if (selectedWorkerProfileId.value !== null) {
    return selectableWorkerProfiles.value.find(profile => profile.id === selectedWorkerProfileId.value) ?? null
  }
  return selectableWorkerProfiles.value.find(profile => profile.is_default && profile.enabled) ?? null
})
const currentAvailablePlaceholders = computed(() => {
  if (!runInstructionDefaults.value || !taskMode.value) return []
  return runInstructionDefaults.value[taskMode.value].available_placeholders
})
const knownRunInstructionPlaceholders = computed(() => [
  ...new Set(runInstructionDefaults.value?.execute.known_placeholders ?? [
    ...(runInstructionDefaults.value?.execute.available_placeholders ?? []),
    ...(runInstructionDefaults.value?.plan.available_placeholders ?? [])
  ])
])

const activePromptTemplates = computed(() => getActivePromptTemplates(promptTemplates.value))
const templateTagOptions = computed(() =>
  getPromptTemplateTags(activePromptTemplates.value).map(tag => ({ label: tag, value: tag }))
)
const filteredPromptTemplates = computed(() =>
  filterPromptTemplatesByTags(activePromptTemplates.value, selectedTemplateTags.value)
)

// --- Watchers ---
watch(showTemplateDrawer, (val) => {
  if (!val) pendingTemplate.value = null
})

watch(scheduleType, (val) => {
  if (val === 'now') scheduledAt.value = null
})

watch(scheduledAt, () => {
  if (props.mode === 'create') checkSlotCapacity()
})

watch(taskMode, (val) => {
  invalidateRunInstructionPreview()
  if (val !== null) {
    taskModeErrorVisible.value = false
    if (!runInstructionTemplate.value && runInstructionDefaults.value) {
      runInstructionTemplate.value = getDefaultRunInstructionTemplate(val)
    }
  }
}, { flush: 'sync' })

watch([prompt, requireChanges], () => {
  invalidateRunInstructionPreview()
}, { flush: 'sync' })

watch(() => props.show, (val) => {
  invalidateRunInstructionPreview()
  if (val) {
    if (props.mode === 'edit' && props.task) {
      prompt.value = props.task.user_prompt ?? ''
      priority.value = props.task.priority ?? 1
      requireChanges.value = props.task.require_changes ?? true
      taskMode.value = (props.task.task_mode as 'execute' | 'plan') ?? 'execute'
      selectedProviderId.value = props.task.provider_id ?? null
      selectedWorkerProfileId.value = props.task.worker_profile_id ?? null
      const snapshot = props.task.run_instruction_template
        ?? getDefaultRunInstructionTemplate(taskMode.value)
        ?? ''
      runInstructionTemplate.value = snapshot
      initialRunInstructionTemplate.value = snapshot
      runInstructionDirty.value = false
    } else if (props.mode === 'create') {
      if (!prompt.value && props.issueDescription) {
        prompt.value = props.issueDescription
      }
      taskMode.value = null
      selectedProviderId.value = null
      selectedWorkerProfileId.value = null
      runInstructionTemplate.value = ''
      initialRunInstructionTemplate.value = ''
      runInstructionDirty.value = false
      requireChanges.value = true
      scheduleType.value = 'now'
      scheduledAt.value = null
      void loadScheduleContext()
    }
    usageLimitDetail.value = null
    taskModeErrorVisible.value = false
  }
})

// --- Data loading ---
async function loadProviders() {
  try {
    providers.value = await getProviders()
  } catch { /* non-critical */ }
}

async function loadWorkerProfiles() {
  try {
    workerProfiles.value = await getWorkerProfiles()
  } catch { /* non-critical */ }
}

async function loadTemplates() {
  promptTemplatesLoading.value = true
  try {
    promptTemplates.value = await getPromptTemplates()
  } catch { /* non-critical */ } finally {
    promptTemplatesLoading.value = false
  }
}

async function loadRunInstructionDefaults() {
  defaultsLoading.value = true
  defaultsError.value = ''
  try {
    runInstructionDefaults.value = await getRunInstructionTemplateDefaults()
    if (props.show && props.mode === 'edit' && props.task && !runInstructionTemplate.value) {
      const mode = (props.task.task_mode ?? 'execute') as 'execute' | 'plan'
      const snapshot = props.task.run_instruction_template ?? getDefaultRunInstructionTemplate(mode)
      runInstructionTemplate.value = snapshot
      initialRunInstructionTemplate.value = snapshot
    }
    if (props.show && props.mode === 'create' && taskMode.value && !runInstructionTemplate.value) {
      runInstructionTemplate.value = getDefaultRunInstructionTemplate(taskMode.value)
      initialRunInstructionTemplate.value = runInstructionTemplate.value
    }
  } catch {
    defaultsError.value = t('runInstruction.defaultsLoadFailed')
  } finally {
    defaultsLoading.value = false
  }
}

async function loadScheduleContext() {
  scheduledTasksLoading.value = true
  try {
    scheduledTasksForPreview.value = await getScheduledTasks()
  } catch {
    scheduledTasksForPreview.value = []
  } finally {
    scheduledTasksLoading.value = false
  }
  try {
    const config = await getConfig()
    slotMaxTasks.value = config.runtime?.slot_max_tasks ?? 0
    slotEnforce.value = config.runtime?.slot_max_tasks_enforce ?? false
  } catch { /* ignore */ }
}

function checkSlotCapacity() {
  slotCapacity.value = null
  if (slotCheckTimeout) clearTimeout(slotCheckTimeout)
  slotCheckGeneration++
  const ms = scheduledAt.value
  if (!ms) return
  const gen = slotCheckGeneration
  slotCheckTimeout = setTimeout(async () => {
    slotCapacityLoading.value = true
    try {
      const result = await getSlotCapacity(new Date(ms).toISOString())
      if (gen !== slotCheckGeneration) return
      slotCapacity.value = result
    } catch {
      if (gen !== slotCheckGeneration) return
      slotCapacity.value = null
    } finally {
      if (gen === slotCheckGeneration) slotCapacityLoading.value = false
    }
  }, 300)
}

async function openHeatmapDrawer() {
  showHeatmapDrawer.value = true
  if (scheduledTasksForPreview.value.length === 0) {
    await loadScheduleContext()
  }
}

function handleHeatmapCellClick(startMs: number) {
  scheduledAt.value = startMs
  showHeatmapDrawer.value = false
}

function selectScheduleType(type: 'now' | 'scheduled') {
  scheduleType.value = type
}

function selectTaskMode(mode: 'execute' | 'plan') {
  if (taskMode.value === mode) return
  const nextDefault = getDefaultRunInstructionTemplate(mode)
  if (runInstructionDirty.value && runInstructionTemplate.value) {
    const replace = window.confirm(t('runInstruction.modeSwitchConfirm'))
    if (replace) runInstructionTemplate.value = nextDefault
  } else {
    runInstructionTemplate.value = nextDefault
  }
  taskMode.value = mode
}

function handleRunInstructionInput(value: string) {
  runInstructionTemplate.value = value
  runInstructionDirty.value = true
  invalidateRunInstructionPreview()
}

function handleRunInstructionSummaryClick(event: MouseEvent) {
  if (taskMode.value === null) event.preventDefault()
}

function restoreRunInstructionDefault() {
  if (!taskMode.value) return
  runInstructionTemplate.value = getDefaultRunInstructionTemplate(taskMode.value)
  runInstructionDirty.value = true
  invalidateRunInstructionPreview()
}

function getDefaultRunInstructionTemplate(mode: 'execute' | 'plan' | null): string {
  if (!mode) return ''
  const profile = effectiveWorkerProfile.value
  if (profile) {
    return mode === 'plan'
      ? profile.default_plan_run_instruction_template
      : profile.default_execute_run_instruction_template
  }
  return runInstructionDefaults.value?.[mode].content ?? ''
}

function handleWorkerProfileChange(profileId: number | null) {
  selectedWorkerProfileId.value = profileId
  if (!taskMode.value || runInstructionDirty.value) return
  const nextTemplate = getDefaultRunInstructionTemplate(taskMode.value)
  if (!nextTemplate) return
  runInstructionTemplate.value = nextTemplate
  invalidateRunInstructionPreview()
}

function usePromptOnly() {
  runInstructionTemplate.value = '{{user_prompt}}'
  runInstructionDirty.value = true
  invalidateRunInstructionPreview()
}

function invalidateRunInstructionPreview() {
  previewRequestGeneration += 1
  previewLoading.value = false
  previewResult.value = ''
  previewError.value = ''
}

async function handleRunInstructionPreview() {
  if (!props.issueId && !props.task) return
  if (!taskMode.value) return
  const requestGeneration = ++previewRequestGeneration
  previewLoading.value = true
  previewError.value = ''
  try {
    const result = await previewRunInstructionTemplate({
      issue_id: props.issueId ?? props.task!.issue_id,
      task_mode: taskMode.value,
      user_prompt: prompt.value.trim() || props.issueDescription || '',
      run_instruction_template: runInstructionTemplate.value,
      require_changes: taskMode.value === 'plan' ? false : requireChanges.value
    })
    if (requestGeneration !== previewRequestGeneration) return
    previewResult.value = result.rendered_prompt
  } catch (error: any) {
    if (requestGeneration !== previewRequestGeneration) return
    previewError.value = error?.response?.data?.detail || error?.apiError?.detail || String(error)
  } finally {
    if (requestGeneration === previewRequestGeneration) previewLoading.value = false
  }
}

function handleTemplateTagFilterUpdate(tags: string[] | null) {
  selectedTemplateTags.value = tags ?? []
  templateTagFilterVisible.value = false
}

function isScheduleDateDisabled(timestamp: number): boolean {
  const candidate = new Date(timestamp)
  const today = new Date()
  candidate.setHours(0, 0, 0, 0)
  today.setHours(0, 0, 0, 0)
  return candidate.getTime() < today.getTime()
}

// --- Template actions ---
function applyPromptTemplate(tmpl: PromptTemplate) {
  prompt.value = tmpl.content
  if (tmpl.variable_tips) {
    promptVariableTips.value = tmpl.variable_tips
  }
}

function handleTemplateItemClick(tmpl: PromptTemplate) {
  if (!hasExistingPrompt.value) {
    applyPromptTemplate(tmpl)
    showTemplateDrawer.value = false
  } else {
    pendingTemplate.value = tmpl
  }
}

function confirmTemplateOverwrite() {
  if (pendingTemplate.value) {
    applyPromptTemplate(pendingTemplate.value)
    pendingTemplate.value = null
    showTemplateDrawer.value = false
  }
}

function cancelTemplateOverwrite() {
  pendingTemplate.value = null
}

// --- Submit actions ---
async function handleCreate() {
  if (taskMode.value === null) {
    taskModeErrorVisible.value = true
    message.warning(t('issue.pleaseSelectTaskMode'))
    return
  }
  if (!runInstructionTemplate.value) {
    runInstructionTemplate.value = getDefaultRunInstructionTemplate(taskMode.value)
  }
  if (!runInstructionTemplate.value.trim()) {
    message.warning(defaultsError.value || t('runInstruction.defaultsLoadFailed'))
    return
  }
  if (scheduleType.value === 'scheduled') {
    if (!scheduledAt.value) {
      message.warning(t('createTask.pleaseSelectScheduledTime'))
      return
    }
    if (scheduledAt.value <= Date.now()) {
      message.warning(t('createTask.scheduledTimeFuture'))
      return
    }
  }

  submitLoading.value = true
  usageLimitDetail.value = null
  try {
    const req: Parameters<typeof createTask>[0] = {
      issue_id: props.issueId!,
      priority: priority.value,
      require_changes: taskMode.value === 'plan' ? false : requireChanges.value
    }
    if (taskMode.value !== null) req.task_mode = taskMode.value
    if (runInstructionDirty.value) {
      req.run_instruction_template = runInstructionTemplate.value
    }
    if (prompt.value.trim()) req.user_prompt = prompt.value.trim()
    if (scheduleType.value === 'scheduled' && scheduledAt.value) {
      req.scheduled_datetime = new Date(scheduledAt.value).toISOString()
    }
    if (selectedProviderId.value !== null) {
      req.provider_id = selectedProviderId.value
    }
    if (selectedWorkerProfileId.value !== null) {
      req.worker_profile_id = selectedWorkerProfileId.value
    }
    const created = await createTask(req)
    message.success(t('issue.taskCreated'))
    prompt.value = ''
    scheduledAt.value = null
    selectedProviderId.value = null
    selectedWorkerProfileId.value = null
    scheduleType.value = 'now'
    scheduledTasksForPreview.value = []
    emit('update:show', false)
    emit('created', created)
  } catch (error: unknown) {
    const anyError = error as { response?: { data?: { detail?: unknown } } }
    const detail = anyError?.response?.data?.detail
    if (isUsageLimitExceededDetail(detail)) {
      usageLimitDetail.value = detail
    } else {
      message.error(extractSlotErrorMessage(error, t, 'createTask.failedToCreateTask'))
    }
  } finally {
    submitLoading.value = false
  }
}

async function handleEdit() {
  if (!props.task) return
  const trimmedPrompt = prompt.value.trim()
  if (!trimmedPrompt) {
    message.warning(t('createTask.pleaseEnterPrompt'))
    return
  }
  // Build a partial payload: only include fields that actually changed.
  const orig = props.task
  const payload: UpdateTaskRequest = {}
  if (trimmedPrompt !== orig.user_prompt) payload.user_prompt = trimmedPrompt
  if (priority.value !== orig.priority) payload.priority = priority.value
  if ((selectedProviderId.value ?? null) !== (orig.provider_id ?? null)) {
    payload.provider_id = selectedProviderId.value
  }
  if ((selectedWorkerProfileId.value ?? null) !== (orig.worker_profile_id ?? null)) {
    payload.worker_profile_id = selectedWorkerProfileId.value
  }
  if (requireChanges.value !== orig.require_changes) payload.require_changes = requireChanges.value
    if (taskMode.value !== null && taskMode.value !== (orig.task_mode ?? 'execute')) {
    payload.task_mode = taskMode.value
    // Switching to plan forces require_changes=false; switching back to execute
    // restores whatever the toggle says (already captured above if changed).
    if (taskMode.value === 'plan' && orig.require_changes !== false) {
      payload.require_changes = false
    }
  }
  if (runInstructionTemplate.value !== initialRunInstructionTemplate.value) {
    payload.run_instruction_template = runInstructionTemplate.value
  }

  if (Object.keys(payload).length === 0) {
    emit('update:show', false)
    return
  }
  submitLoading.value = true
  try {
    const updated = await updateTask(orig.id, payload)
    message.success(t('taskView.taskUpdated'))
    emit('update:show', false)
    emit('updated', updated)
  } catch (error: unknown) {
    const anyError = error as { response?: { data?: { detail?: unknown } } }
    const detail = anyError?.response?.data?.detail
    if (typeof detail === 'string') {
      message.error(detail)
    } else {
      message.error(t('taskView.failedToUpdateTask'))
    }
  } finally {
    submitLoading.value = false
  }
}

// --- Lifecycle ---
onMounted(() => {
  void loadProviders()
  void loadWorkerProfiles()
  void loadTemplates()
  void loadRunInstructionDefaults()
})

onUnmounted(() => {
  if (slotCheckTimeout) clearTimeout(slotCheckTimeout)
  slotCheckGeneration++
})
</script>

<style scoped>
.task-form-drawer__form {
  max-width: 100%;
}

.task-form-drawer__form :deep(.variable-editor__codemirror .cm-editor) {
  min-height: 200px;
}

/* Prompt section */
.prompt-form-section {
  margin-bottom: 18px;
}

.prompt-section-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  min-width: 0;
  margin-bottom: 6px;
}

.prompt-section-label-text {
  font-size: 14px;
  color: var(--n-text-color);
}

.prompt-label-left {
  display: flex;
  align-items: center;
  gap: 8px;
}

.prompt-label-right {
  display: flex;
  align-items: center;
  gap: 6px;
}

.task-mode-label-row {
  display: inline-flex;
  align-items: baseline;
  gap: 8px;
}

.task-mode-label-hint {
  color: var(--n-text-color-3);
  font-size: 12px;
  font-weight: 400;
}

.task-mode-label-hint--error {
  color: var(--n-feedback-text-color-error, #d03050);
}

.task-mode-section {
  display: flex;
  flex-direction: column;
  width: 100%;
  gap: 0;
}

.run-instruction-advanced {
  width: 100%;
  margin-bottom: 16px;
  overflow: hidden;
  border: 1px solid var(--n-border-color);
  border-radius: 10px;
  background: var(--n-color);
  transition: border-color 0.15s ease, box-shadow 0.15s ease;
}

.run-instruction-advanced[open] {
  border-color: var(--n-primary-color);
  box-shadow: 0 0 0 2px rgba(99, 226, 183, 0.06);
}

.run-instruction-advanced--disabled {
  border-color: var(--n-border-color);
  background: var(--n-color-disabled);
  box-shadow: none;
}

.run-instruction-advanced__summary {
  display: flex;
  align-items: center;
  gap: 10px;
  min-height: 48px;
  padding: 8px 12px;
  cursor: pointer;
  list-style: none;
  user-select: none;
}

.run-instruction-advanced__summary::-webkit-details-marker {
  display: none;
}

.run-instruction-advanced--disabled .run-instruction-advanced__summary {
  cursor: not-allowed;
}

.run-instruction-advanced__icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  flex: 0 0 28px;
  border-radius: 7px;
  color: var(--n-primary-color);
  background: rgba(99, 226, 183, 0.1);
}

.run-instruction-advanced--disabled .run-instruction-advanced__icon {
  color: var(--n-text-color-disabled);
  background: var(--n-action-color);
}

.run-instruction-advanced__copy {
  display: flex;
  min-width: 0;
  flex: 1;
  flex-direction: column;
  gap: 1px;
}

.run-instruction-advanced__title {
  color: var(--n-text-color);
  font-size: 14px;
  font-weight: 600;
  line-height: 20px;
}

.run-instruction-advanced__hint {
  overflow: hidden;
  color: var(--n-text-color-3);
  font-size: 12px;
  line-height: 18px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.run-instruction-advanced--disabled .run-instruction-advanced__title,
.run-instruction-advanced--disabled .run-instruction-advanced__hint,
.run-instruction-advanced--disabled .run-instruction-advanced__chevron {
  color: var(--n-text-color-disabled);
}

.run-instruction-advanced__chevron {
  color: var(--n-text-color-3);
  font-size: 22px;
  line-height: 1;
  transform: rotate(0deg);
  transition: transform 0.15s ease, color 0.15s ease;
}

.run-instruction-advanced[open] .run-instruction-advanced__chevron {
  color: var(--n-primary-color);
  transform: rotate(90deg);
}

.run-instruction-advanced__content {
  padding: 12px 12px 4px;
  border-top: 1px solid var(--n-border-color);
  background: rgba(255, 255, 255, 0.015);
}

@media (hover: hover) and (pointer: fine) {
  .run-instruction-advanced:not([open], .run-instruction-advanced--disabled):hover {
    border-color: var(--n-primary-color);
  }
}

@media (prefers-reduced-motion: reduce) {
  .run-instruction-advanced,
  .run-instruction-advanced__chevron {
    transition: none;
  }
}

.task-mode-selector {
  display: flex;
  gap: 8px;
  width: 100%;
}

:deep(.n-form-item-blank) {
  flex-direction: column;
  align-items: flex-start;
}

.task-mode-card {
  flex: 1;
  display: flex;
  align-items: flex-start;
  gap: 10px;
  position: relative;
  padding: 10px 32px 10px 12px;
  border: 1px solid var(--n-border-color);
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.15s;
}

.task-mode-card:hover {
  border-color: var(--n-primary-color);
}

.task-mode-card--error {
  border-color: var(--n-feedback-text-color-error, #d03050);
}

.task-mode-card--error:hover {
  border-color: var(--n-feedback-text-color-error, #d03050);
}

.task-mode-card--active {
  border-color: var(--n-primary-color);
  background: rgba(99, 226, 183, 0.06);
}

.task-mode-card__icon {
  margin-top: 2px;
  flex-shrink: 0;
  color: var(--n-text-color-3);
}

.task-mode-card--active .task-mode-card__icon {
  color: var(--n-primary-color);
}

.task-mode-card__check {
  position: absolute;
  top: 10px;
  right: 10px;
  color: var(--n-primary-color);
}

.task-mode-card__body {
  flex: 1;
  min-width: 0;
}

.task-mode-card__label {
  font-weight: 600;
  font-size: 13px;
}

.task-mode-card__desc {
  font-size: 11px;
  color: var(--n-text-color-3);
  margin-top: 2px;
}

.require-changes-row {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 8px;
  padding-left: 12px;
}

.prompt-label-require-text {
  font-size: 12px;
  color: var(--n-label-text-color, #888);
}

.require-changes-info-icon {
  color: var(--n-label-text-color, #aaa);
  cursor: help;
  flex-shrink: 0;
}

.prompt-variable-warning {
  display: flex;
  align-items: center;
  gap: 4px;
  color: #f0a020;
  font-size: 12px;
  margin-top: 4px;
}

/* Priority selector */
.priority-selector {
  display: flex;
  gap: 8px;
  width: 100%;
}

.priority-card {
  flex: 1;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  border: 1px solid var(--n-border-color);
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.15s;
}

.priority-card:hover {
  border-color: var(--n-primary-color);
}

.priority-card--active.priority-card--p0 {
  border-color: #e88080;
  background: rgba(232, 128, 128, 0.06);
}

.priority-card--active.priority-card--p1 {
  border-color: #f0a020;
  background: rgba(240, 160, 32, 0.06);
}

.priority-card--active.priority-card--p2 {
  border-color: #63e2b7;
  background: rgba(99, 226, 183, 0.06);
}

.priority-card--p0 .priority-card__label { color: #d03050; }
.priority-card--p1 .priority-card__label { color: #f0a020; }
.priority-card--p2 .priority-card__label { color: #18a058; }
.priority-card__label { font-weight: 600; font-size: 13px; }
.priority-card__desc { font-size: 11px; color: var(--n-text-color-3); }

/* Execution fields */
.execution-field-label {
  display: inline-flex;
  align-items: baseline;
  gap: 8px;
}

.execution-field-label__hint {
  color: var(--n-text-color-3);
  font-size: 12px;
  font-weight: 400;
}

/* Schedule section */
.schedule-section {
  display: flex;
  flex-direction: column;
  gap: 10px;
  width: 100%;
}

.schedule-mode-selector {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
  width: 100%;
}

.schedule-mode-card {
  position: relative;
  display: flex;
  align-items: flex-start;
  gap: 10px;
  width: 100%;
  min-width: 0;
  min-height: 66px;
  padding: 10px 32px 10px 11px;
  border: 1px solid var(--n-border-color);
  border-radius: 9px;
  background: var(--n-color);
  color: var(--n-text-color);
  font: inherit;
  text-align: left;
  cursor: pointer;
  transition: border-color 0.15s ease, background-color 0.15s ease, transform 0.15s ease;
}

.schedule-mode-card--active {
  border-color: var(--n-primary-color);
  background: color-mix(in srgb, var(--n-primary-color) 6%, transparent);
}

.schedule-mode-card:focus-visible {
  outline: 2px solid var(--n-primary-color);
  outline-offset: 2px;
}

.schedule-mode-card__icon,
.provider-control__icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex: 0 0 30px;
  width: 30px;
  height: 30px;
  border-radius: 8px;
  background: rgba(128, 128, 128, 0.09);
  color: var(--n-text-color-3);
  transition: color 0.15s ease, background-color 0.15s ease;
}

.schedule-mode-card--active .schedule-mode-card__icon {
  background: color-mix(in srgb, var(--n-primary-color) 12%, transparent);
  color: var(--n-primary-color);
}

.schedule-mode-card__copy {
  display: flex;
  flex: 1;
  flex-direction: column;
  min-width: 0;
}

.schedule-mode-card__title {
  font-size: 13px;
  font-weight: 600;
  line-height: 20px;
}

.schedule-mode-card__description {
  color: var(--n-text-color-3);
  font-size: 11px;
  line-height: 16px;
}

.schedule-mode-card__check {
  position: absolute;
  top: 10px;
  right: 10px;
  color: var(--n-primary-color);
}

.schedule-detail-panel {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px;
  border: 1px solid var(--n-border-color);
  border-radius: 9px;
  background: rgba(128, 128, 128, 0.035);
}

.schedule-detail-panel__picker {
  flex: 1;
  min-width: 0;
}

.schedule-detail-panel__heatmap {
  flex-shrink: 0;
}

.schedule-detail-enter-active,
.schedule-detail-leave-active {
  transition: opacity 0.16s ease, transform 0.16s ease;
}

.schedule-detail-enter-from,
.schedule-detail-leave-to {
  opacity: 0;
  transform: translateY(-4px);
}

/* Provider section */
.provider-control {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  width: 100%;
  padding: 10px;
  border: 1px solid var(--n-border-color);
  border-radius: 9px;
  background: rgba(128, 128, 128, 0.035);
  transition: border-color 0.15s ease, background-color 0.15s ease;
}

.provider-control:focus-within {
  border-color: var(--n-primary-color);
  background: color-mix(in srgb, var(--n-primary-color) 4%, transparent);
}

.provider-control--empty {
  border-color: rgba(240, 160, 32, 0.55);
}

.provider-control__icon {
  margin-top: 1px;
}

.provider-control:focus-within .provider-control__icon {
  background: color-mix(in srgb, var(--n-primary-color) 12%, transparent);
  color: var(--n-primary-color);
}

.provider-control__body {
  flex: 1;
  min-width: 0;
}

.provider-control__select {
  width: 100%;
}

.provider-control__summary {
  display: flex;
  align-items: center;
  gap: 5px;
  min-width: 0;
  margin-top: 6px;
  color: var(--n-text-color-3);
  font-size: 11px;
  line-height: 16px;
}

.provider-control__status {
  color: var(--n-primary-color);
  white-space: nowrap;
}

.provider-control__model {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.provider-control__summary--warning {
  color: #f0a020;
}

@media (hover: hover) and (pointer: fine) {
  .schedule-mode-card:not(.schedule-mode-card--active):hover,
  .provider-control:hover {
    border-color: var(--n-primary-color);
  }

  .schedule-mode-card:not(.schedule-mode-card--active):hover {
    transform: translateY(-1px);
  }
}

@media (max-width: 520px) {
  .schedule-mode-selector {
    grid-template-columns: 1fr;
  }

  .schedule-detail-panel {
    align-items: stretch;
    flex-direction: column;
  }

  .schedule-detail-panel__heatmap {
    width: 100%;
  }

  .execution-field-label {
    align-items: flex-start;
    flex-direction: column;
    gap: 1px;
  }
}

@media (prefers-reduced-motion: reduce) {
  .schedule-mode-card,
  .schedule-mode-card__icon,
  .provider-control,
  .provider-control__icon,
  .schedule-detail-enter-active,
  .schedule-detail-leave-active {
    transition: none;
  }
}

/* Template picker drawer */
.template-drawer-layout {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: var(--n-color, #fff);
}

.template-drawer-layout__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 20px;
  border-bottom: 1px solid rgba(0, 0, 0, 0.09);
  flex-shrink: 0;
}

.template-drawer-layout__title {
  font-size: 18px;
  font-weight: 500;
  color: rgba(15, 23, 42, 0.9);
}

.template-drawer-layout__body {
  flex: 1;
  min-height: 0;
}

.template-tag-filter {
  padding: 8px 16px 12px;
}

.prompt-template-dropdown__empty {
  padding: 16px;
  text-align: center;
  color: var(--n-text-color-3);
}

.prompt-template-dropdown__item {
  padding: 12px 16px;
  cursor: pointer;
  border-bottom: 1px solid rgba(128, 128, 128, 0.1);
}

.prompt-template-dropdown__item:hover {
  background: rgba(128, 128, 128, 0.05);
}

.prompt-template-dropdown__item--pending {
  background-color: rgba(32, 128, 240, 0.08);
  border-left: 3px solid #2080f0;
  padding-left: 9px;
}

.prompt-template-dropdown__item-name {
  font-weight: 600;
  margin-bottom: 4px;
}

.prompt-template-dropdown__tags {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  margin-bottom: 6px;
}

.prompt-template-dropdown__item-preview {
  font-size: 12px;
  color: var(--n-text-color-3);
}

.template-overwrite-banner {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 14px;
  margin: 0 12px;
  background: rgba(255, 160, 32, 0.1);
  border: 1px solid rgba(255, 160, 32, 0.4);
  border-radius: 10px;
  flex-shrink: 0;
}

.banner-slide-enter-active,
.banner-slide-leave-active {
  transition: opacity 0.22s ease, transform 0.22s ease, max-height 0.22s ease, margin 0.22s ease, padding 0.22s ease;
  overflow: hidden;
  max-height: 80px;
}

.banner-slide-enter-from,
.banner-slide-leave-to {
  opacity: 0;
  transform: translateY(-6px);
  max-height: 0;
  margin-top: 0;
  margin-bottom: 0;
  padding-top: 0;
  padding-bottom: 0;
}

.template-overwrite-banner__text {
  flex: 1;
  font-size: 13px;
  color: rgba(15, 23, 42, 0.82);
}

.template-overwrite-banner__actions {
  display: flex;
  gap: 8px;
  flex-shrink: 0;
}

/* Usage limit */
.task-form-drawer__usage-limit-alert {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.task-form-drawer__usage-limit-row {
  display: flex;
  gap: 8px;
  font-size: 13px;
  flex-wrap: wrap;
}
</style>
